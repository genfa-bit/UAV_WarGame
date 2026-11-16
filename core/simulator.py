"""仿真主控模块。

第十阶段集成：
- 每帧更新交战状态机
- 攻击改为队列模式，统一结算
- 反应延迟消除先手优势
"""

from __future__ import annotations

import math
from dataclasses import replace
from numbers import Real

from config import (BASE_DEFENSE_RADIUS, BASE_REPAIR_PER_STEP, BASE_REPAIR_RADIUS,
                     COMM_DELAY_FACTOR, CRIT_CHANCE, CRIT_DAMAGE_MULTIPLIER,
                     DETECTION_TIMEOUT_STEPS, EVADE_ATTACK_RANGE_FACTOR,
                     MAX_CONFIGURABLE_STEPS, MAX_SIMULATION_STEPS,
                     MAX_STEP_DURATION_SECONDS, MIN_STEP_DURATION_SECONDS,
                     SIMULATION_INTERVAL_MS, STATUS_DESTROYED, STATUS_EVADE,
                     TARGET_LOCK_TIME, TEAM_BLUE, TEAM_RED,
                     UNIT_SEPARATION_DISTANCE, UNIT_SEPARATION_PUSH)
from core.battlefield import Battlefield
from core.behavior import BEHAVIOR_LABELS
from core.combat import AttackEvent, CombatSystem, calculate_hit_probability
from core.cooperative_allocator import AssignmentResult, CooperativeAllocator
from core.damage_ledger import DamageLedger
from core.engagement import EngagementPhase
from core.entity import stable_unit_angle
from core.pathfinding import cleanup_destroyed
from core.replay import BASE_IDS, FrameBuffer
from core.strategy import StrategyEngine
from core.strike_planner import StrikePlanner
from core.target_pool import TargetPool
from core.threat import (priority_targets, situation_label, tactics_label,
                         team_strength, threat_score)
from core.time_coordination import (FirePlan, FireWindow, TaskDeferralBudget,
                                    estimate_eta, estimate_eta_interval,
                                    staging_standoff)
from core.unit_config_loader import (get_cooperative_assignment_config,
                                     get_unit_stats)
from core.units import CommandNode, Unit, UnitDomain


class Simulator:
    """按时间步推进侦察、集火、规避、攻击和胜负判断。"""

    def __init__(self, battlefield: Battlefield, units: list[Unit],
                 max_steps: int = MAX_SIMULATION_STEPS,
                 step_duration_seconds: float = SIMULATION_INTERVAL_MS / 1000,
                 cooperative_config: dict | None = None):
        self._validate_timing(step_duration_seconds, max_steps, current_step=0)
        # 绕障缓存按单位 ID 保存；新局必须清理上一局同名单位的状态。
        cleanup_destroyed(set())
        self.battlefield = battlefield
        self.units = units
        self.time_step = 0
        self.max_steps = max_steps
        self.step_duration_seconds = float(step_duration_seconds)
        self.elapsed_seconds = 0.0
        self.strategy = StrategyEngine()
        self.combat = CombatSystem()

        self.shared_targets: dict[str, TargetPool] = {TEAM_RED: TargetPool(), TEAM_BLUE: TargetPool()}
        self.red_detected_targets = self.shared_targets[TEAM_RED]
        self.blue_detected_targets = self.shared_targets[TEAM_BLUE]
        # 基地是战略目标，单独建池，避免改变 focus_targets / 旧界面语义。
        self.strategic_targets: dict[str, TargetPool] = {
            TEAM_RED: TargetPool(), TEAM_BLUE: TargetPool()}
        self._base_own_sightings: dict[str, set[str]] = {}

        self.focus_targets: dict[str, Unit | None] = {TEAM_RED: None, TEAM_BLUE: None}
        self.priority_targets: dict[str, list[Unit]] = {TEAM_RED: [], TEAM_BLUE: []}
        self.red_strength: float = 0.0
        self.blue_strength: float = 0.0
        self.focus_lock: dict[str, str | None] = {TEAM_RED: None, TEAM_BLUE: None}
        self.destroyed_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.kill_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.attack_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.hit_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.total_damage = {TEAM_RED: 0, TEAM_BLUE: 0}
        # 名义伤害超出剩余血量的部分（过杀）。total_damage 只累计实际扣血，
        # 单看它无法发现“34 点打 5 点血”的浪费。
        self.overkill_damage = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.winner: str | None = None
        self.finish_reason: str | None = None
        self.attack_events: list[AttackEvent] = []
        self.combat_logs: list[str] = []
        # 完整结构化历史独立于界面的最近 12 条日志，直到重启本局才清空。
        self.records: list[dict] = []
        self.destroyed_units: list[dict] = []

        self.show_wrecks = True
        self._own_sightings: dict[str, set[str]] = {}
        self._destroyed_record: set[str] = set()
        self._kill_credit_record: set[str] = set()
        self._evading_units: set[str] = set()
        self._last_ammo_resupply: dict[str, int] = {}
        self._result_logged = False
        self._last_scout_sightings: dict[str, set[str]] = {}
        self._base_sightings: set[tuple[str, str]] = set()
        self._sharing_sources: dict[tuple[str, str], str] = {}
        self._sharing_delivered: set[tuple[str, str]] = set()
        self._destruction_ids: set[str] = set()
        self._unit_tactical_state: dict[str, tuple] = {}
        self._team_tactical_state: dict[str, tuple] = {}
        # 协同动态边际拍卖（RDMA）。分配结果只约束移动/攻击授权；旧
        # focus_targets 仍保留给 UI 和兼容路径。
        self.cooperative_config = (cooperative_config
                                   if cooperative_config is not None
                                   else get_cooperative_assignment_config())
        self.cooperative_enabled = bool(self.cooperative_config.get("enabled", True))
        # 算法模式由配置决定；缺省 htcs（2026-11-16 基准选定）。HTCS 所需的
        # 账本、火力计划与再攻击状态只在 htcs 模式下创建和使用。
        self.cooperative_mode = str(self.cooperative_config.get("mode", "htcs"))
        self.htcs_config = dict(self.cooperative_config.get("htcs", {}))
        self._htcs_configured = self.cooperative_mode == "htcs"
        self.allocator = CooperativeAllocator(self.cooperative_config)
        self.strike_planner = (StrikePlanner(self.cooperative_config)
                               if self._htcs_configured else None)
        self.damage_ledger = DamageLedger()
        self.fire_plans: dict[str, dict[str, list[FirePlan]]] = {
            TEAM_RED: {}, TEAM_BLUE: {}}
        # 再攻击目标：当前波次未能达成效果的活目标，供下一波次加权。
        self._htcs_reattack: dict[str, set[str]] = {
            TEAM_RED: set(), TEAM_BLUE: set()}
        # 重规划会整体替换任务对象。上一波次的任务如果直接被丢弃，它承诺
        # 的火力就再也没人核对，BDA 只能对“恰好活过窗口”的任务生效。
        # 因此把未判定的旧任务挪到退役列表，继续按各自窗口判定，判完即弃。
        self._htcs_retired: dict[str, list] = {
            TEAM_RED: [], TEAM_BLUE: []}
        self._bda_assessed: set[str] = set()
        self._htcs_hold_logged: set[tuple[str, str, int]] = set()
        # 迟到计划被拦截后，单位在 hold_until 之前不得对同一目标机会
        # 射击，防止“计划超时→下一步补枪”绕过火力门。
        self._htcs_target_hold: dict[tuple[str, str], int] = {}
        self._htcs_miss_logged: set[str] = set()
        # 自适应迟到策略的分类日志：挂起/再定时每任务只记一次。
        self._htcs_defer_logged: set[str] = set()
        self._htcs_retime_logged: set[str] = set()
        # 任务级延期账本：按 task_id 记录原始 TOT、累计延期与再定时次数。
        # 计划跨波次保持时仍使用同一份预算，重定时不会重新获得额度。
        self._htcs_task_budgets: dict[str, dict[str, TaskDeferralBudget]] = {
            TEAM_RED: {}, TEAM_BLUE: {}}
        self.assignments: dict[str, AssignmentResult] = {
            TEAM_RED: AssignmentResult(), TEAM_BLUE: AssignmentResult()}
        # 只有本步真正执行过分配，才允许 RDMA 路由；直接调用旧阶段方法的
        # 测试/兼容代码没有这个标记，会自然回退到旧目标选择。
        self._assignment_ready_step: dict[str, int | None] = {
            TEAM_RED: None, TEAM_BLUE: None}
        self._assignment_synced_step: dict[str, int] = {}
        # 事件触发重规划：基地/可见目标血量显著变化时不必等周期。
        self._assignment_base_hp = {
            TEAM_RED: battlefield.base_obj(TEAM_RED).hp,
            TEAM_BLUE: battlefield.base_obj(TEAM_BLUE).hp}
        self._assignment_target_hp: dict[str, int] = {}
        # 逐帧采样供运行记录回放；基地不在 self.units 里，单独追加在队尾。
        self.frame_buffer = FrameBuffer([unit.id for unit in self.units] + list(BASE_IDS))
        self._capture_replay_frame()
        self.record_event("lifecycle", "本局仿真已建立", event="created",
                          step_duration_seconds=self.step_duration_seconds,
                          max_steps=self.max_steps)
        self._record_unit_tactical_changes(initial=True)
        self._record_team_tactical_changes(initial=True)

    @staticmethod
    def _validate_timing(step_duration_seconds: float, max_steps: int,
                         current_step: int) -> None:
        if (isinstance(step_duration_seconds, bool)
                or not isinstance(step_duration_seconds, Real)
                or not MIN_STEP_DURATION_SECONDS <= step_duration_seconds <= MAX_STEP_DURATION_SECONDS
                or not math.isfinite(step_duration_seconds)):
            raise ValueError("单步时长必须为 0.01 至 60 秒的有限数值")
        if (isinstance(max_steps, bool) or not isinstance(max_steps, int)
                or not 0 < max_steps <= MAX_CONFIGURABLE_STEPS):
            raise ValueError(f"最大运行步数必须为 1 至 {MAX_CONFIGURABLE_STEPS} 的正整数")
        if max_steps <= current_step:
            raise ValueError("最大运行步数必须大于当前已完成步数")

    def configure_timing(self, step_duration_seconds: float, max_steps: int) -> None:
        """原子更新后续时间步；既有事件的累计模拟时间保持原值。

        移动、反应、通信和补给规则仍按步计算；时长控制模拟时钟与运行节奏。
        调用方负责只在部署或暂停时开放该设置。
        """
        self._validate_timing(step_duration_seconds, max_steps, self.time_step)
        if self.winner:
            raise ValueError("本局已经结束，请重启后修改时间步")
        duration = float(step_duration_seconds)
        if (duration, max_steps) == (self.step_duration_seconds, self.max_steps):
            return
        old_duration, old_max = self.step_duration_seconds, self.max_steps
        self.step_duration_seconds, self.max_steps = duration, max_steps
        self.record_event("settings", "时间步设置已修改", event="timing_changed",
                          previous_step_duration_seconds=old_duration,
                          previous_max_steps=old_max,
                          step_duration_seconds=duration, max_steps=max_steps)

    def record_event(self, category: str, message: str, **fields) -> dict:
        """追加一条带序号、时间步和累计模拟秒数的完整记录。"""
        row = dict(fields)
        row.update(seq=len(self.records) + 1, step=self.time_step,
                   elapsed_seconds=round(self.elapsed_seconds, 9),
                   category=category.lower(), message=message)
        self.records.append(row)
        return row

    def step(self) -> None:
        """推进一个仿真时间步。

        流程：
        1. 清理已摧毁单位和无效目标；
        2. 更新战力/优先级；
        3. 侦察（重建当前视野并更新共享目标池）；
        4. 更新交战状态机并通知已可见目标；
        5. 选择集火目标；
        6. 移动/规避；
        7. 攻击基地（加入意图队列，优先于单位攻击）；
        8. 攻击单位（加入意图队列）；
        9. 统一结算所有攻击意图；
        10. 补给、统计、胜负。
        """
        if self.winner:
            self._tick_attack_events()
            return

        self.time_step += 1
        self.elapsed_seconds = round(self.elapsed_seconds + self.step_duration_seconds, 9)
        self._update_strength()
        self._update_priority_targets()
        self.strategy.behavior_mgr.tick_target_locks()
        self.strategy.behavior_mgr.tick_cooldowns()
        self._cleanup_target_pools()
        self._reconnaissance_phase()
        self._record_shared_deliveries()
        if self.htcs_enabled:
            # 战损评估必须在重规划之前：否则本步的新任务会覆盖上一波次的
            # 任务，BDA 永远看不到“窗口已结束但仍未达成”的任务。
            self._bda_phase()
        self._update_assignments()
        self._update_engagement_states()
        self._record_unit_tactical_changes()
        self._select_focus_targets()
        self._record_team_tactical_changes()
        self._movement_phase()
        self._separate_overlapping_units()
        self._record_unit_tactical_changes()
        self._attack_base_phase()   # 基地攻击优先
        self._attack_phase()
        self._resolve_attacks()
        self._replenish_phase()
        self._update_destroyed_stats()
        self._record_unit_tactical_changes()
        self._cleanup_target_pools()
        self._select_focus_targets()
        self._record_team_tactical_changes()
        self._judge_winner()
        self._tick_attack_events()
        self._capture_replay_frame()

    # ═══════════════════════════════════════════════════════════
    #  协同分配（RDMA）
    # ═══════════════════════════════════════════════════════════

    @property
    def htcs_enabled(self) -> bool:
        """当前是否实际运行 HTCS（配置为 htcs 且协同分配已启用）。"""
        return self.cooperative_enabled and self._htcs_configured

    def _assignment_mode_active(self, team: str) -> bool:
        """本步是否已执行 RDMA 分配。

        直接调用旧阶段方法的兼容代码不会设置该标记，因此仍走旧目标逻辑；
        Simulator.step() 中完成分配后，移动和攻击严格按分配授权。
        """
        return (self.cooperative_enabled
                and self._assignment_ready_step.get(team) == self.time_step)

    def _assigned_target_id(self, unit: Unit) -> str | None:
        if not self._assignment_mode_active(unit.team):
            return None
        return self.assignments[unit.team].assignments.get(unit.id)

    def _visible_target_ids_by_unit(self) -> dict[str, set[str]]:
        """每个单位自己的可见目标集合：本单位观测 ∪ 已送达共享池。

        基地也遵守同一规则：只有本单位亲自发现，或战略目标池已送达，
        才进入该单位的可见集合。未收到通信的队友不能获得私有基地侦察。
        """
        delivered = {
            team: {target.id for target in pool.values_available(self.time_step)}
            for team, pool in self.shared_targets.items()
        }
        delivered_bases = {
            team: {target.id for target in pool.values_available(self.time_step)}
            for team, pool in self.strategic_targets.items()
        }
        connected = None
        if (self.htcs_enabled
                and bool(self.htcs_config.get("distributed_fallback", False))):
            connected = self._htcs_connected_units()
        result: dict[str, set[str]] = {}
        for unit in self.active_units():
            own = (set(self._own_sightings.get(unit.id, set()))
                   | self._base_own_sightings.get(unit.id, set()))
            # 分布式降级：与指挥节点失去联系的单位只能使用自身观测，
            # 不再接收共享池与战略目标池的广播。
            if connected is None or unit.id in connected:
                own |= delivered[unit.team] | delivered_bases[unit.team]
            result[unit.id] = own
        return result

    def _htcs_connected_units(self) -> set[str]:
        """HTCS 分布式降级：仍处于本方指挥链内的单位集合。

        当前模型用指挥节点的 ``comm_range`` 作为连通半径；指挥节点自身
        始终在链内，其余单位只要靠近任意一个存活指挥节点即可接收共享
        信息。失去全部指挥节点时，所有单位退化为本地观测。
        """
        connected: set[str] = set()
        for team in (TEAM_RED, TEAM_BLUE):
            commands = [unit for unit in self.active_units(team)
                        if isinstance(unit, CommandNode)]
            for unit in self.active_units(team):
                if unit.domain == UnitDomain.COMMAND:
                    connected.add(unit.id)
                    continue
                radius = max((getattr(command, "comm_range", 250.0)
                              for command in commands), default=0.0)
                if any(unit.distance_to(command) <= radius
                       for command in commands):
                    connected.add(unit.id)
        return connected

    def _refresh_strategic_targets(self) -> None:
        """刷新已确认基地的最近观测，但不推迟首次交付时间。

        基地是静态战略目标，一经该阵营确认就保留到摧毁；没有当前观察者
        时仍需维持目标记录，因此只刷新 ``last_seen_step``，不改
        ``available_step``。
        """
        for team, pool in self.strategic_targets.items():
            base = self.battlefield.base_obj(
                TEAM_BLUE if team == TEAM_RED else TEAM_RED)
            if not base.is_destroyed and base.id in pool:
                pool.refresh(base.id, self.time_step)

    def _base_visible_to(self, unit: Unit) -> bool:
        """该单位是否知道敌方基地（亲自发现或已收到战略目标池交付）。"""
        base = self.battlefield.base_obj(
            TEAM_BLUE if unit.team == TEAM_RED else TEAM_RED)
        if base.is_destroyed:
            return False
        if base.id in self._base_own_sightings.get(unit.id, set()):
            return True
        return any(
            record.target.id == base.id and record.available_step <= self.time_step
            for record in self.strategic_targets[unit.team].records())

    def _update_assignments(self) -> None:
        """按重规划周期执行 RDMA，并同步每个单位的交战目标。"""
        if not self.cooperative_enabled:
            self._assignment_ready_step = {TEAM_RED: None, TEAM_BLUE: None}
            return

        visible_by_unit = self._visible_target_ids_by_unit()
        unit_map = {unit.id: unit for unit in self.units}
        unit_map[self.battlefield.base_obj(TEAM_RED).id] = \
            self.battlefield.base_obj(TEAM_RED)
        unit_map[self.battlefield.base_obj(TEAM_BLUE).id] = \
            self.battlefield.base_obj(TEAM_BLUE)
        interval = int(self.cooperative_config["replan_interval_steps"])

        for team in (TEAM_RED, TEAM_BLUE):
            previous = self.assignments[team]
            enemy_team = TEAM_BLUE if team == TEAM_RED else TEAM_RED
            enemy_base = self.battlefield.base_obj(enemy_team)
            invalid = False
            target_hp_changed = False
            for unit_id, target_id in list(previous.assignments.items()):
                unit = unit_map.get(unit_id)
                target = unit_map.get(target_id)
                visible = target_id in visible_by_unit.get(unit_id, set())
                if (unit is None or unit.is_destroyed or unit.status == STATUS_EVADE
                        or target is None or target.is_destroyed or not visible
                        or not unit.can_engage(target)):
                    invalid = True
                    if (unit is not None
                            and unit.engagement_state.current_target_id == target_id):
                        unit.engagement_state.on_target_lost()
                elif target is not None:
                    old_hp = self._assignment_target_hp.get(target.id)
                    if old_hp is not None and target.hp != old_hp:
                        ratio = abs(target.hp - old_hp) / max(1, target.max_hp)
                        target_hp_changed = target_hp_changed or ratio >= 0.20

            base_hp_changed = False
            if not enemy_base.is_destroyed:
                old_base_hp = self._assignment_base_hp[team]
                base_hp_changed = (abs(enemy_base.hp - old_base_hp)
                                   >= max(1, round(enemy_base.max_hp * 0.10)))
                self._assignment_base_hp[team] = enemy_base.hp

            has_visible = any(
                visible_by_unit.get(unit.id) for unit in self.active_units(team))
            # 首次发现目标时不能等到下一个重规划周期，否则会空转数步。
            newly_detected = not previous.assignments and has_visible
            wave_length = max(1, int(self.htcs_config.get(
                "wave_length_steps", interval)))
            wave_boundary = (self.htcs_enabled
                             and self.time_step % wave_length == 0)
            due = (previous.updated_step == 0
                   or invalid
                   or newly_detected
                   or target_hp_changed
                   or base_hp_changed
                   or wave_boundary
                   or self.time_step - previous.updated_step >= interval)
            context = {
                "enemy_combat_units": len([
                    unit for unit in self.enemy_units(team)
                    if unit.attack_power > 0
                    and unit.unit_type != "command_node"]),
            }
            if due and self.htcs_enabled:
                context.update(
                    enemy_units=list(self.enemy_units(team)),
                    own_strength=team_strength(self.active_units(team)),
                    enemy_strength=team_strength(self.enemy_units(team)),
                    reattack_targets=set(self._htcs_reattack[team]),
                )
                result = self.strike_planner.plan(
                    self.active_units(team),
                    list(self.shared_targets[team].records())
                    + list(self.strategic_targets[team].records()),
                    self.time_step,
                    self.battlefield,
                    previous=previous,
                    visible_ids_by_unit=visible_by_unit,
                    context=context,
                    ledger=self.damage_ledger,
                )
            elif due:
                result = self.allocator.allocate(
                    self.active_units(team),
                    list(self.shared_targets[team].records())
                    + list(self.strategic_targets[team].records()),
                    self.time_step,
                    self.battlefield,
                    previous=previous,
                    visible_ids_by_unit=visible_by_unit,
                    context=context,
                )
            else:
                result = previous

            if self.htcs_enabled:
                if due:
                    self._install_fire_plans(team, result)
                else:
                    self._prune_fire_plans(team)

            if self.htcs_enabled and due and result is not previous:
                # 旧任务束退役：未判定的承诺继续走 BDA，不随对象替换消失。
                self._htcs_retired[team].extend(
                    task for task in previous.tasks.values()
                    if task.state not in ("done", "failed"))

            old_assignments = dict(previous.assignments)
            self.assignments[team] = result

            # 分配目标变化时，让交战状态机重新进入 REACTING/ATTACK；
            # 不继承旧目标反应进度，冷却期保留冷却计时。
            for unit in self.active_units(team):
                eng = unit.engagement_state
                new_target_id = result.assignments.get(unit.id)
                if new_target_id:
                    if eng.current_target_id != new_target_id:
                        eng.on_assignment_changed(new_target_id)
                        if (eng.current_target_id == new_target_id
                                and eng.phase != EngagementPhase.COOLDOWN):
                            self._assignment_synced_step[unit.id] = self.time_step
                else:
                    old_target_id = old_assignments.get(unit.id)
                    if (old_target_id
                            and eng.current_target_id == old_target_id):
                        eng.on_target_lost()

            self._assignment_ready_step[team] = self.time_step
            if due and old_assignments != result.assignments:
                self._log_assignment_change(team, previous, result)

        # 记录本步可见目标的血量快照，供下一步事件触发比较。
        for target in self.enemy_units(TEAM_RED) + self.enemy_units(TEAM_BLUE):
            self._assignment_target_hp[target.id] = target.hp
        for base in (self.battlefield.base_obj(TEAM_RED),
                     self.battlefield.base_obj(TEAM_BLUE)):
            self._assignment_target_hp[base.id] = base.hp

    def _log_assignment_change(self, team: str, previous: AssignmentResult,
                               result: AssignmentResult) -> None:
        target_names = {unit.id: unit.name for unit in self.units}
        for base_team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(base_team)
            target_names[base.id] = base.name
        changed = sorted(set(previous.assignments) | set(result.assignments))
        for unit_id in changed:
            old_id = previous.assignments.get(unit_id)
            new_id = result.assignments.get(unit_id)
            if old_id == new_id:
                continue
            self.record_event(
                "coordination",
                f"{team.title()} {unit_id} 协同目标："
                f"{target_names.get(old_id, old_id) if old_id else '无'} → "
                f"{target_names.get(new_id, new_id) if new_id else '无'}",
                event="assignment_changed", team=team, unit_id=unit_id,
                previous_target_id=old_id, target_id=new_id,
                reason=result.reasons.get(unit_id),
            )
        primary = target_names.get(result.primary_target_id or "",
                                   result.primary_target_id)
        self._add_log(
            "Assign",
            f"{team.title()} assignment updated: {len(result.assignments)} assigned, "
            f"primary={primary or 'none'}",
            record_category="coordination", event="assignment_updated",
            team=team, assigned_count=len(result.assignments),
            unassigned_count=len(self.active_units(team)) - len(result.assignments),
            primary_target_id=result.primary_target_id,
            replanned=True,
            algorithm=self.cooperative_mode,
            wave_id=result.wave_id,
            doctrine=result.doctrine,
        )

    # ═══════════════════════════════════════════════════════════
    #  HTCS：火力计划、火力门、BDA 与再攻击
    # ═══════════════════════════════════════════════════════════

    def _entity(self, entity_id: str | None) -> Unit | None:
        """按 ID 查找单位或基地。"""
        if not entity_id:
            return None
        for unit in self.units:
            if unit.id == entity_id:
                return unit
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if base.id == entity_id:
                return base
        return None

    def _install_fire_plans(self, team: str,
                            result: AssignmentResult) -> None:
        """把任务束展开为单位级火力计划（每发一个 FirePlan）。

        重规划不再整体替换所有计划：TOT 可能远在一个波次之后（慢速单位
        的反应 + 冷却周期可达 61 步），若每次波次边界都把未执行的计划
        丢弃，计划永远等不到自己的窗口。``plan_persistence`` 打开时，
        只保留“目标与角色仍在新任务束中”的旧计划，再追加新任务；目标
        或角色已变化的旧计划照常被替换。
        """
        tolerance = int(self.htcs_config.get("tot_tolerance_steps", 1))
        late = int(self.htcs_config.get("tot_late_steps", 3))
        late_max = max(late, int(
            self.htcs_config.get("late_fire_late_max_steps", late)))
        adaptive = str(self.htcs_config.get(
            "late_fire_policy", "strict")) == "adaptive"
        persist = bool(self.htcs_config.get("plan_persistence", True))
        previous_plans = self.fire_plans.get(team, {})
        plans: dict[str, list[FirePlan]] = {}
        for unit in self.active_units(team):
            unit_plans: list[FirePlan] = []
            for task_id in result.bundles.get(unit.id, []):
                task = result.tasks.get(task_id)
                if task is None:
                    continue
                shots = max(1, int(task.shots.get(unit.id, 1)))
                cycle = max(1, int(unit.reaction_delay)
                            + int(unit.attack_cooldown) + 1)
                eta_nominal = int(task.eta_by_unit.get(
                    unit.id, task.eta_best))
                eta_upper = int(task.eta_upper_by_unit.get(
                    unit.id, eta_nominal))
                original_tot = int(task.original_tot or task.tot_step)
                plan_late = late
                if adaptive:
                    # 标称 ETA 只负责把 TOT 摆到位；地形/绕障/目标运动
                    # 带来的额外不确定性进入宽限。这样 TOT 不被过度推后，
                    # 合法但慢一点的射击又不会被误判迟到。
                    plan_late = min(
                        late_max, late + max(0, eta_upper - eta_nominal))
                for index in range(shots):
                    # 同一任务的多发按冷却周期顺延 TOT，形成波次内的
                    # 连续射击，而不是所有发数挤在同一帧。
                    window = FireWindow(
                        tot=task.tot_step + index * cycle,
                        tolerance=tolerance, late=plan_late)
                    unit_plans.append(FirePlan(
                        task_id=task.task_id,
                        target_id=task.target_id,
                        wave=task.wave,
                        role=task.role,
                        window=window,
                        eta_nominal=eta_nominal,
                        eta_upper=eta_upper,
                        original_tot=original_tot,
                    ))
            if persist:
                unit_plans = self._merge_fire_plans(
                    previous_plans.get(unit.id, []), unit_plans)
            plans[unit.id] = unit_plans
        self.fire_plans[team] = plans
        if adaptive:
            self._htcs_sync_plans_and_tasks(team, result)

    def _merge_fire_plans(self, old: list[FirePlan],
                          new: list[FirePlan]) -> list[FirePlan]:
        """保留仍然有效的旧计划，只追加新任务的火力计划。

        旧计划按 ``(目标, 角色)`` 与新任务束对齐。仍被计划的旧任务继续
        使用原来的 TOT 序列（承诺不因重规划漂移）；新任务（例如本波次
        才出现的 SEAD 目标）追加在后面。同一 ``(目标, 角色)`` 不会同时
        保留新旧两份计划，避免重复扣弹药。
        """
        if not old or not new:
            return new
        new_keys = {(plan.target_id, plan.role) for plan in new}
        kept = [plan for plan in old if (plan.target_id, plan.role) in new_keys]
        if not kept:
            return new
        kept_keys = {(plan.target_id, plan.role) for plan in kept}
        return kept + [plan for plan in new
                       if (plan.target_id, plan.role) not in kept_keys]

    def _htcs_task_by_id(self, team: str, task_id: str):
        """按 task_id 查找当前任务，找不到时回退到退役任务。

        跨波次保留的 FirePlan 仍指向旧 task_id；重规划会把旧任务移入
        ``_htcs_retired``。统一查找保证再定时/挂起能同步到真正的任务对象，
        而不是丢失字段后让 BDA 用过期的 late_until 判定。
        """
        result = self.assignments.get(team)
        if result is not None and task_id in result.tasks:
            return result.tasks[task_id]
        for task in self._htcs_retired.get(team, []):
            if task.task_id == task_id:
                return task
        return None

    def _htcs_budget(self, team: str, plan: FirePlan) -> TaskDeferralBudget:
        """取得（或创建）某条计划所属任务的延期预算。

        预算按 task_id 持久保存：只要同一条计划跨波次保留，就沿用原来的
        原始 TOT 与累计延期，重定时不会重新获得完整额度。
        """
        table = self._htcs_task_budgets.setdefault(team, {})
        budget = table.get(plan.task_id)
        if budget is None:
            task = self._htcs_task_by_id(team, plan.task_id)
            original = int(
                (getattr(task, "original_tot", 0) if task is not None else 0)
                or plan.original_tot or plan.tot)
            budget = TaskDeferralBudget(
                original_tot=original,
                max_delay_steps=int(self.htcs_config.get(
                    "late_fire_task_delay_max_steps", 60)))
            table[plan.task_id] = budget
        return budget

    def _htcs_sync_plans_and_tasks(self, team: str,
                                   result: AssignmentResult) -> None:
        """重规划后把 StrikeTask 与真正保留的 FirePlan 对齐。

        ``plan_persistence`` 可能保留旧计划，而新任务对象带着重新计算的
        TOT；若不回写，任务窗口会与计划窗口脱节。这里以保留计划为唯一
        事实来源，同步任务时间字段与 ``attack_steps``。
        """
        per_task: dict[str, list[FirePlan]] = {}
        for plans in self.fire_plans.get(team, {}).values():
            for plan in plans:
                per_task.setdefault(plan.task_id, []).append(plan)
        for task_id, task_plans in per_task.items():
            task = result.tasks.get(task_id)
            if task is None:
                continue
            base = min(task_plans, key=lambda item: item.tot)
            task.tot_step = int(base.tot)
            task.window_start = int(base.window_start)
            task.late_until = int(base.late_until)
            budget = self._htcs_budget(team, base)
            task.original_tot = budget.original_tot
            task.retimes = budget.retimes
            task.deferred_steps = budget.deferred_steps
        for unit_id, plans in self.fire_plans.get(team, {}).items():
            # 保留计划可能仍属于已退役的旧任务；attack_steps 必须反映
            # 单位真正会执行的队首计划，而不是新任务对象重新计算的 TOT。
            if plans:
                result.attack_steps[unit_id] = int(plans[0].tot)

    def _htcs_shift_headroom(self, team: str, task_id: str) -> int | None:
        """同一单位后续任务允许本次计划最多后移多少步。

        取所有持有该任务的单位中，最早的一条“后续任务 window_start”与
        当前任务最后一条计划 ``late_until`` 之间的空隙。返回 None 表示
        没有后续任务，只受延期预算约束。
        """
        room: int | None = None
        for plans in self.fire_plans.get(team, {}).values():
            indices = [index for index, item in enumerate(plans)
                       if item.task_id == task_id]
            if not indices:
                continue
            last = plans[indices[-1]]
            later = plans[indices[-1] + 1:]
            if not later:
                continue
            candidate = min(item.window_start for item in later) - 1 \
                - int(last.late_until)
            room = candidate if room is None else min(room, candidate)
        return room

    def _prune_fire_plans(self, team: str) -> None:
        """非重规划步：丢弃目标已摧毁/消失的队首计划。"""
        for unit_id, plans in list(self.fire_plans.get(team, {}).items()):
            unit = self._entity(unit_id)
            if unit is None or unit.is_destroyed:
                self.fire_plans[team].pop(unit_id, None)
                continue
            while plans:
                target = self._entity(plans[0].target_id)
                if target is None or target.is_destroyed:
                    self._htcs_consume_plan(unit, plans[0])
                    continue
                break

    def _drop_plans_for_target(self, target_id: str) -> None:
        """目标被摧毁后移除所有针对它的队首计划并同步分配。"""
        for team in (TEAM_RED, TEAM_BLUE):
            for unit_id, plans in list(self.fire_plans.get(team, {}).items()):
                unit = self._entity(unit_id)
                if unit is None:
                    continue
                while plans and plans[0].target_id == target_id:
                    self._htcs_consume_plan(unit, plans[0])

    def _htcs_consume_plan(self, unit: Unit, plan: FirePlan) -> None:
        """消耗一条火力计划，并把分配同步到任务束中的下一目标。"""
        plans = self.fire_plans.get(unit.team, {}).get(unit.id)
        if plans:
            if plans[0] is plan:
                plans.pop(0)
            else:
                try:
                    plans.remove(plan)
                except ValueError:
                    pass
        result = self.assignments.get(unit.team)
        next_plan = plans[0] if plans else None
        if result is not None:
            if next_plan is not None:
                result.assignments[unit.id] = next_plan.target_id
                result.reasons[unit.id] = f"htcs:{next_plan.role}"
                result.attack_steps[unit.id] = next_plan.tot
            else:
                result.assignments.pop(unit.id, None)
                result.reasons.pop(unit.id, None)
                result.attack_steps.pop(unit.id, None)
        eng = unit.engagement_state
        if next_plan is not None:
            if eng.current_target_id != next_plan.target_id:
                eng.on_assignment_changed(next_plan.target_id)
        elif eng.current_target_id == plan.target_id:
            eng.on_target_lost()

    def _htcs_head_plan(self, unit: Unit,
                        visible_ids: set[str]) -> FirePlan | None:
        """返回单位当前有效队首计划，顺带清理失效/迟到计划。"""
        plans = self.fire_plans.get(unit.team, {}).get(unit.id)
        if not plans:
            return None
        policy = str(self.htcs_config.get("late_fire_policy", "strict"))
        while plans:
            plan = plans[0]
            target = self._entity(plan.target_id)
            if (target is None or target.is_destroyed
                    or plan.target_id not in visible_ids):
                self._htcs_consume_plan(unit, plan)
                continue
            # 记录“至少到达过一次可开火位置”：迟到分类用它区分“没赶到”
            # 与“赶到了但被压制/纪律挡住/没执行”。
            if unit.can_attack(target):
                plan.reached = True
            if plan.window.expired(self.time_step):
                if policy == "strict":
                    # 硬性拦截：超过 late_until 的计划不再补射。消耗计划并
                    # 对同一目标设置停火保持，防止下一步从机会射击通道打出去。
                    self._htcs_miss_plan(unit, plan, target)
                    continue
                if policy == "adaptive":
                    self._htcs_adaptive_expired(unit, plan, target)
                    continue
                # lenient：保留旧行为，计划继续留在队首，下一步会补射。
            return plan
        return None

    def _htcs_adaptive_expired(self, unit: Unit, plan: FirePlan,
                               target: Unit) -> None:
        """自适应迟到处理：先分类，再决定再定时/挂起/拦截。

        - ``covered``：账本已覆盖目标效果 → 不必再打，静默消耗；
        - ``discipline``：己方在途火力已覆盖/会过杀 → 顺延一个保持周期，
          等账本结算后重新开火；
        - ``temporary``：单位规避/被 SEAD 压制 → 顺延，不判失败；
        - ``deliverable``：标称 ETA 仍在再定时视野内 → 推迟到能赶到的
          时刻，保持任务承诺；
        - ``infeasible``：根本到不了/没弹药 → 任务挂起，不触发再攻击；
        - ``late``：已经到位却没打出去 → 仍按迟到拦截，维持火力纪律。
        """
        reason = self._htcs_classify_expired(unit, plan, target)
        if reason == "covered":
            # 账本已经覆盖目标效果：同一任务后续的发数也没有意义，
            # 全部取消但不设停火保持（否则会挡住下一波次的新任务）。
            self._htcs_cancel_task_plans(unit, plan)
            return
        if reason in ("discipline", "temporary", "deliverable"):
            if self._htcs_try_retime(unit, plan, target, reason):
                return
            if reason == "temporary":
                self._htcs_defer_plan(unit, plan, target, reason)
                return
            self._htcs_miss_plan(unit, plan, target, reason=reason)
            return
        if reason == "infeasible":
            self._htcs_defer_plan(unit, plan, target, reason)
            return
        self._htcs_miss_plan(unit, plan, target, reason=reason)

    def _htcs_classify_expired(self, unit: Unit, plan: FirePlan,
                               target: Unit) -> str:
        """对一条过期计划做可行性分类，返回原因字符串。"""
        desired = self._desired_effect(target)
        if self.damage_ledger.remaining_need(
                target.id, target.hp, desired) <= 0.5:
            return "covered"
        if self._htcs_discipline_blocks(
                target, self._htcs_expected_damage(unit, target)):
            return "discipline"
        horizon = int(self.htcs_config.get(
            "late_fire_retime_horizon_steps", 60))
        if (unit.status == STATUS_EVADE
                or unit.suppressed_until > self.time_step):
            return "temporary"
        # 已经到位但还在反应/冷却：计划到点时单位尚未获得开火权。这是
        # 执行节奏问题，不是“没赶到”，顺延剩余射击周期即可。
        ready_delay = self._htcs_ready_delay(unit)
        if ready_delay > 0:
            return "temporary" if ready_delay <= horizon else "infeasible"
        if unit.ammo <= 0 or not unit.can_engage(target):
            return "infeasible"
        estimate = estimate_eta_interval(
            unit, target, self.battlefield,
            target_speed=max(0.0, float(getattr(target, "speed", 0.0))) * 0.5,
            sample_px=float(self.htcs_config.get(
                "eta_terrain_sample_px", 8.0)),
            detour_factor=float(self.htcs_config.get(
                "eta_detour_factor", 0.5)),
            slack_ratio=float(self.htcs_config.get(
                "eta_upper_slack_ratio", 1.10)))
        if estimate.nominal <= horizon:
            if estimate.nominal > 0:
                return "deliverable"
            # 当前已在射程内：到达过但没打出去，属于执行迟到。
            return "late"
        # 当前 ETA 已超出再定时视野：无论过去是否到过射程，都不能再按
        # “已到位迟到”拦截。``plan.reached`` 只是历史事实，目标移动后
        # 可能早已离开射程，这里按当前不可行处理（挂起，等待下波次规划）。
        return "infeasible"

    @staticmethod
    def _htcs_ready_delay(unit: Unit) -> int:
        """单位还要多久才能开火（剩余反应/冷却 + 1 步状态推进）。"""
        eng = unit.engagement_state
        if eng.phase.name == "COOLDOWN":
            remaining = max(0, int(eng.attack_cooldown)
                            - int(eng.cooldown_progress))
            return remaining + max(0, int(eng.reaction_delay)) + 1
        if eng.phase.name == "REACTING":
            remaining = max(0, int(eng.reaction_delay)
                            - int(eng.reaction_progress))
            return remaining + 1
        return 0

    def _htcs_try_retime(self, unit: Unit, plan: FirePlan, target: Unit,
                         reason: str) -> bool:
        """有界推迟任务内的全部火力计划；返回是否成功推迟。

        两个限制同时生效、互相独立：

        - ``late_fire_retime_max``：任务被再定时的**次数**；
        - ``late_fire_task_delay_max_steps``：任务**累计**延期步数。

        任一用尽都会停止再定时，由调用方转为挂起或迟到拦截。
        """
        budget = self._htcs_budget(unit.team, plan)
        max_retimes = int(self.htcs_config.get("late_fire_retime_max", 1))
        if budget.retimes >= max_retimes:
            return False
        hold = max(1, int(self.htcs_config.get("late_fire_hold_steps", 6)))
        estimate = estimate_eta_interval(
            unit, target, self.battlefield,
            target_speed=max(0.0, float(getattr(target, "speed", 0.0))) * 0.5,
            sample_px=float(self.htcs_config.get(
                "eta_terrain_sample_px", 8.0)),
            detour_factor=float(self.htcs_config.get(
                "eta_detour_factor", 0.5)),
            slack_ratio=float(self.htcs_config.get(
                "eta_upper_slack_ratio", 1.10)))
        horizon = int(self.htcs_config.get(
            "late_fire_retime_horizon_steps", 60))
        if reason == "discipline":
            delay = hold
        elif reason == "temporary":
            delay = max(hold, int(estimate.nominal),
                        self._htcs_ready_delay(unit))
        else:
            if estimate.nominal > horizon:
                return False
            delay = max(1, int(estimate.nominal))
        delay = min(max(1, delay), max(1, horizon))
        new_tot = max(int(plan.tot), self.time_step + delay)
        delta = new_tot - int(plan.tot)
        if delta <= 0:
            return False
        return self._htcs_shift_task(
            unit, plan, delta, reason=reason,
            eta_nominal=int(estimate.nominal),
            eta_upper=int(estimate.upper)) > 0

    def _htcs_shift_task(self, unit: Unit, plan: FirePlan, delta: int,
                         *, reason: str, eta_nominal: int,
                         eta_upper: int) -> int:
        """把同一任务的所有计划整体平移，返回实际平移步数。

        平移量同时受三层约束：

        1. 任务累计延期预算（``late_fire_task_delay_max_steps``）；
        2. 同一单位后续任务的时间窗，避免延期任务与已承诺任务重叠；
        3. 只修改 ``task_id`` 完全相同的计划与任务，不触碰无关任务。
        """
        team = unit.team
        budget = self._htcs_budget(team, plan)
        applied = budget.clamp_delta(delta)
        headroom = self._htcs_shift_headroom(team, plan.task_id)
        if headroom is not None:
            applied = min(applied, max(0, headroom))
        if applied <= 0:
            return 0
        budget.deferred_steps += applied
        budget.retimes += 1
        old_tot = int(plan.tot)
        for unit_id, plans in list(self.fire_plans.get(team, {}).items()):
            for index, item in enumerate(plans):
                if item.task_id != plan.task_id:
                    continue
                plans[index] = replace(
                    item,
                    window=FireWindow(
                        tot=item.tot + applied,
                        tolerance=item.window.tolerance,
                        late=item.window.late),
                    retimes=item.retimes + 1,
                    original_tot=item.original_tot or budget.original_tot)
        # 旧任务可能已经退役；统一查找后再同步时间字段与预算计数。
        task = self._htcs_task_by_id(team, plan.task_id)
        if task is not None:
            task.tot_step += applied
            task.window_start += applied
            task.late_until += applied
            task.retimes = budget.retimes
            task.original_tot = budget.original_tot
            task.deferred_steps = budget.deferred_steps
        result = self.assignments.get(team)
        if result is not None:
            for unit_id, plans in self.fire_plans.get(team, {}).items():
                if plans and plans[0].task_id == plan.task_id:
                    result.attack_steps[unit_id] = plans[0].tot
        if plan.task_id not in self._htcs_retime_logged:
            self._htcs_retime_logged.add(plan.task_id)
            current_target = self._entity(plan.target_id)
            in_range_now = bool(current_target is not None
                                and unit.can_attack(current_target))
            self.record_event(
                "coordination",
                f"{team.title()} {unit.name} 火力计划再定时："
                f"{plan.task_id} 的 TOT 从第 {old_tot} 步推到 "
                f"第 {old_tot + applied} 步（{reason}）",
                event="fire_window_retimed", team=team,
                unit_id=unit.id, target_id=plan.target_id,
                task_id=plan.task_id, reason=reason,
                old_tot=old_tot, new_tot=old_tot + applied,
                original_tot=budget.original_tot,
                deadline_tot=budget.deadline_tot,
                deferred_steps=budget.deferred_steps,
                remaining_steps=budget.remaining_steps,
                retimes=budget.retimes,
                ever_in_range=bool(plan.reached),
                in_range_now=in_range_now,
                eta_nominal=eta_nominal, eta_upper=eta_upper)
        return applied

    def _htcs_defer_plan(self, unit: Unit, plan: FirePlan,
                         target: Unit, reason: str) -> None:
        """挂起不可执行的任务：不设停火保持，也不触发再攻击。"""
        team = unit.team
        task = self._htcs_task_by_id(team, plan.task_id)
        if task is not None:
            task.state = "deferred"
            task.deferred = True
            budget = self._htcs_task_budgets.get(team, {}).get(plan.task_id)
            if budget is not None:
                task.retimes = budget.retimes
                task.deferred_steps = budget.deferred_steps
        if plan.task_id not in self._htcs_defer_logged:
            self._htcs_defer_logged.add(plan.task_id)
            self.record_event(
                "coordination",
                f"{team.title()} {unit.name} 任务挂起："
                f"{target.name} 在本波次不可达/不可执行（{reason}）",
                event="fire_window_deferred", team=team,
                unit_id=unit.id, target_id=target.id,
                task_id=plan.task_id, reason=reason,
                eta_nominal=plan.eta_nominal, eta_upper=plan.eta_upper,
                ever_in_range=bool(plan.reached),
                in_range_now=unit.can_attack(target))
        self._htcs_cancel_task_plans(unit, plan)

    def _htcs_cancel_task_plans(self, unit: Unit, plan: FirePlan) -> None:
        """取消同一任务的全部剩余计划（不设置停火保持）。

        取消前释放该任务早于当前步、尚未结算的预约伤害；本步已经排队、
        等待同步结算的攻击不受影响，避免把在途伤害误释放。
        """
        team = unit.team
        self.damage_ledger.release_task(
            plan.task_id, before_step=self.time_step)
        for unit_id, plans in list(self.fire_plans.get(team, {}).items()):
            matching = [item for item in list(plans)
                        if item.task_id == plan.task_id]
            owner = self._entity(unit_id)
            if owner is None:
                continue
            for item in matching:
                self._htcs_consume_plan(owner, item)

    def _htcs_miss_plan(self, unit: Unit, plan: FirePlan, target: Unit,
                        *, reason: str = "late") -> None:
        """拦截一条迟到计划：记录事件、设置保持，然后消耗该计划。"""
        hold = max(1, int(self.htcs_config.get("late_fire_hold_steps", 6)))
        self._htcs_target_hold[(unit.id, plan.target_id)] = (
            self.time_step + hold)
        if plan.task_id not in self._htcs_miss_logged:
            self._htcs_miss_logged.add(plan.task_id)
            self.record_event(
                "coordination",
                f"{unit.team.title()} {unit.name} 迟到射击被拦截："
                f"{target.name} 的火力窗口已于第 {plan.late_until} 步结束"
                f"（{reason}）",
                event="fire_window_missed", team=unit.team,
                unit_id=unit.id, target_id=target.id,
                task_id=plan.task_id, tot=plan.tot,
                late_until=plan.late_until, hold_until=self.time_step + hold,
                reason=reason, reached=bool(plan.reached),
                ever_in_range=bool(plan.reached),
                in_range_now=unit.can_attack(target),
                eta_nominal=plan.eta_nominal, eta_upper=plan.eta_upper)
        self._htcs_consume_plan(unit, plan)

    def _desired_effect(self, target: Unit) -> float:
        return float(self.cooperative_config.get(
            "desired_effect_by_type", {}).get(target.unit_type, 1.0))

    def _htcs_expected_damage(self, unit: Unit, target: Unit) -> float:
        """本发攻击的期望伤害（含暴击期望），用于交叉射击纪律。"""
        hit_prob = calculate_hit_probability(
            unit, target, self.battlefield,
            is_evading=(unit.status == STATUS_EVADE))
        crit_factor = 1.0 + CRIT_CHANCE * (CRIT_DAMAGE_MULTIPLIER - 1.0)
        return max(0.0, hit_prob * unit.attack_power * crit_factor)

    def _htcs_discipline_blocks(self, target: Unit,
                                incoming: float | None = None) -> bool:
        """账本是否禁止本发（不记录事件，供迟到分类复用）。"""
        if not bool(self.htcs_config.get("fire_discipline", True)):
            return False
        desired = self._desired_effect(target)
        ratio = float(self.htcs_config.get("overkill_fire_ratio", 1.0))
        saturated = self.damage_ledger.is_saturated(
            target.id, target.hp, desired, ratio)
        crossing = (not saturated and incoming is not None
                    and self.damage_ledger.would_overkill(
                        target.id, target.hp, incoming, desired, ratio))
        return bool(saturated or crossing)

    def _htcs_fire_allowed(self, unit: Unit, target: Unit,
                           incoming: float | None = None) -> bool:
        """火力纪律：账本已覆盖目标效果时停火，等待本波次结算。

        ``incoming`` 给出**本发**的期望伤害时，还会做交叉射击检查：
        已有别人预约、且加上本发会超过过杀阈值时同样停火。这样同一帧
        多个单位不会各自认为“账本还没满”而叠加过杀；账本为空时仍允许
        第一发收掉残血目标。
        """
        if not bool(self.htcs_config.get("fire_discipline", True)):
            return True
        desired = self._desired_effect(target)
        ratio = float(self.htcs_config.get("overkill_fire_ratio", 1.0))
        saturated = self.damage_ledger.is_saturated(
            target.id, target.hp, desired, ratio)
        crossing = (not saturated and incoming is not None
                    and self.damage_ledger.would_overkill(
                        target.id, target.hp, incoming, desired, ratio))
        if saturated or crossing:
            key = (unit.id, target.id, self.time_step // max(
                1, int(self.htcs_config.get("wave_length_steps", 6))))
            if key not in self._htcs_hold_logged:
                self._htcs_hold_logged.add(key)
                reason = "已覆盖效果" if saturated else "会造成交叉射击过杀"
                self.record_event(
                    "coordination",
                    f"{unit.team.title()} {unit.name} 火力纪律："
                    f"{target.name} 的在途期望伤害{reason}，暂缓射击",
                    event="fire_discipline_hold", team=unit.team,
                    unit_id=unit.id, target_id=target.id,
                    reserved=self.damage_ledger.reserved(target.id),
                    incoming=round(float(incoming), 2)
                    if incoming is not None else None,
                    target_hp=target.hp)
        return not (saturated or crossing)

    def _htcs_opportunity_target(self, unit: Unit,
                                 visible: list[Unit]) -> Unit | None:
        """机会射击：未分配单位只打射程内、尚未被账本覆盖的目标。"""
        if not bool(self.htcs_config.get("opportunity_fire", True)):
            return None
        reserve_ratio = float(self.htcs_config.get("ammo_reserve_ratio", 0.2))
        reserve = math.ceil(reserve_ratio * self.allocator.max_ammo(unit))
        # 预留量不能锁死最后几发：至少留 1 发可用于当前交战。
        reserve = min(reserve, max(0, unit.ammo - 1))
        if unit.ammo <= reserve:
            return None
        candidates = [
            target for target in visible
            if not target.is_destroyed and unit.can_attack(target)
            and self._htcs_target_hold.get(
                (unit.id, target.id), -1) < self.time_step
            and self.damage_ledger.remaining_need(
                target.id, target.hp, self._desired_effect(target)) > 0.0
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda target: (
            -threat_score(target, unit), target.id))

    def _bda_phase(self) -> None:
        """战损评估：完结任务、清理账本、标记需要再攻击的目标。"""
        active_ids = {unit.id for unit in self.units if not unit.is_destroyed}
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if not base.is_destroyed:
                active_ids.add(base.id)
        self.damage_ledger.prune(active_ids)
        # 上一步未结算的预约不应继续占用目标；正常路径会在同步结算时
        # 逐发 settle，这里只清理异常残留，不影响本步尚未排队的新攻击。
        self.damage_ledger.release(before_step=self.time_step)
        # 清理已经过期的迟到停火保持，避免字典无限增长。
        self._htcs_target_hold = {
            key: until for key, until in self._htcs_target_hold.items()
            if until >= self.time_step}

        newly_destroyed = set(self._destruction_ids) - self._bda_assessed
        for target_id in sorted(newly_destroyed):
            self._bda_assessed.add(target_id)
            applied = self.damage_ledger.applied(target_id)
            self.damage_ledger.clear_target(target_id)
            self._drop_plans_for_target(target_id)
            for team in (TEAM_RED, TEAM_BLUE):
                self._htcs_reattack[team].discard(target_id)
                self._htcs_retired[team] = [
                    task for task in self._htcs_retired[team]
                    if task.target_id != target_id]
                for task in self.assignments[team].tasks.values():
                    if (task.target_id == target_id
                            and task.state not in ("done", "failed")):
                        task.state = "done"
                        self.record_event(
                            "coordination",
                            f"{team.title()} 任务 {task.task_id} 完成："
                            f"目标已摧毁",
                            event="bda_completed", team=team,
                            task_id=task.task_id, target_id=target_id,
                            planned_damage=round(task.planned_damage, 2),
                            applied_damage=round(applied, 2))

        if bool(self.htcs_config.get("bda_enabled", True)):
            for team in (TEAM_RED, TEAM_BLUE):
                for task in list(self.assignments[team].tasks.values()):
                    self._bda_judge(team, task)
                # 已退役（上一波次被重规划替换）但仍未判定的任务照常核对。
                self._htcs_retired[team] = [
                    task for task in self._htcs_retired[team]
                    if not self._bda_judge(team, task)]
        self._htcs_prune_budgets()

    def _htcs_prune_budgets(self) -> None:
        """丢弃不再被任何计划/任务引用的延期预算，避免字典无限增长。"""
        for team in (TEAM_RED, TEAM_BLUE):
            table = self._htcs_task_budgets.get(team)
            if not table:
                continue
            referenced = {
                plan.task_id
                for plans in self.fire_plans.get(team, {}).values()
                for plan in plans}
            referenced.update(self.assignments[team].tasks)
            referenced.update(
                task.task_id for task in self._htcs_retired.get(team, []))
            self._htcs_task_budgets[team] = {
                task_id: budget for task_id, budget in table.items()
                if task_id in referenced}

    def _bda_judge(self, team: str, task) -> bool:
        """按任务自身的火力窗口判定其承诺是否兑现。

        返回 True 表示已经得出结论（完成/失败），False 表示仍需继续观察。
        """
        if task.state in ("done", "failed", "deferred"):
            # 挂起是“本波次不可执行”，不是执行失败：不触发再攻击，
            # 下一波次由规划器重新评估可达性。
            return True
        target = self._entity(task.target_id)
        if target is None or target.is_destroyed:
            return True
        # 只按任务自己的火力窗口判定，不按波次边界：波次是规划粒度，
        # 而单位反应+冷却可能长于一个波次，TOT 自然会被推到波次之外。
        # 窗口内一律视为“仍在执行”。
        if self.time_step <= task.late_until:
            return False
        need = self.damage_ledger.remaining_need(
            target.id, target.hp, self._desired_effect(target))
        if need <= 0.5:
            task.state = "done"
            return True
        if task.state != "ready":
            # 计划本身未满编（火力不足/单位不够），属于下一波次继续规划，
            # 不是“执行失败”，不触发再攻击加成。
            return True
        delivered = max(
            0.0, self.damage_ledger.applied(target.id) - task.applied_at_plan)
        if (task.planned_damage > 0.0 and delivered >=
                float(self.htcs_config.get("bda_delivery_ratio", 0.6))
                * task.planned_damage):
            # 本波次承诺的火力已经兑现（即使目标还没被消灭），后续波次
            # 由规划器继续追加任务，不算执行失败。
            task.state = "done"
            return True
        self._htcs_reattack[team].add(target.id)
        task.state = "failed"
        self.record_event(
            "coordination",
            f"{team.title()} 战损评估：{target.name} 任务窗口结束，"
            f"仍需 {round(need, 1)} 期望伤害，转入再攻击",
            event="reattack_required", team=team,
            task_id=task.task_id, target_id=target.id,
            remaining_need=round(need, 2),
            target_hp=target.hp,
            reserved=self.damage_ledger.reserved(target.id))
        return True

    def _emergency_attack_target(self, unit: Unit,
                                 visible: list[Unit]) -> Unit | None:
        """RDMA 启用时未分配单位仅保留两类紧急自卫目标。

        1. 规避状态下面临极近距离威胁；
        2. 敌方单位逼近己方基地 250 px。
        普通 focus/最近敌人回退被明确禁止。
        """
        visible_units = [enemy for enemy in visible
                         if enemy.unit_type != "base"]
        if unit.status == STATUS_EVADE:
            nearest = self.strategy.nearest_enemy(unit, visible_units)
            if (nearest and unit.attack_range > 0
                    and unit.distance_to(nearest)
                    <= unit.attack_range * EVADE_ATTACK_RANGE_FACTOR
                    and unit.can_attack(nearest)):
                return nearest
        own_base = self.battlefield.base_obj(unit.team)
        near_base = [
            enemy for enemy in visible_units
            if unit.can_attack(enemy)
            and math.hypot(enemy.x - own_base.x, enemy.y - own_base.y)
            <= BASE_DEFENSE_RADIUS
        ]
        return min(near_base, key=unit.distance_to) if near_base else None

    # ═══════════════════════════════════════════════════════════
    #  交战状态更新
    # ═══════════════════════════════════════════════════════════

    def _update_engagement_states(self) -> None:
        """用本步有效视野推进状态；新发现目标从下一步累计反应期。"""
        for unit in self.active_units():
            eng = unit.engagement_state
            assignment_active = self._assignment_mode_active(unit.team)
            assigned_id = self._assigned_target_id(unit)
            # RDMA 下基地也是分配目标，需要进入该单位的可见集合；旧路径
            # 仍保持 _visible_targets_for() 只返回普通单位。
            visible = self._visible_targets_for(
                unit, include_base=assignment_active)
            visible_units = [target for target in visible
                             if target.unit_type != "base"]
            visible_ids = {target.id for target in visible}
            enemy_base = self.battlefield.base_obj(
                TEAM_BLUE if unit.team == TEAM_RED else TEAM_RED)
            if eng.phase in (EngagementPhase.REACTING, EngagementPhase.ATTACK) and eng.current_target_id:
                tid = eng.current_target_id
                # 基地是固定战略目标：旧路径发现后保持有效；RDMA 下只有
                # 分配目标确实是基地时才保留。
                base_known = (
                    (not assignment_active and tid == enemy_base.id
                     and not enemy_base.is_destroyed)
                    or (assignment_active and assigned_id == enemy_base.id
                        and tid == enemy_base.id
                        and not enemy_base.is_destroyed))
                assigned_mismatch = bool(assignment_active and assigned_id
                                         and tid != assigned_id)
                unassigned_base = bool(assignment_active and not assigned_id
                                       and tid == enemy_base.id)
                if (assigned_mismatch or unassigned_base
                        or (not base_known and tid not in visible_ids)):
                    eng.on_target_lost()
            if self._assignment_synced_step.get(unit.id) != self.time_step:
                eng.tick()
            if eng.phase == EngagementPhase.SEARCH:
                target = None
                if assignment_active and assigned_id:
                    target = next((t for t in visible if t.id == assigned_id), None)
                elif assignment_active:
                    # 未分配作战单位只保留紧急自卫，不回退基地/focus/最近敌人。
                    # HTCS 额外允许“机会射击”：射程内且未被账本覆盖的目标。
                    target = self._emergency_attack_target(unit, visible_units)
                    if self.htcs_enabled and target is None:
                        target = self._htcs_opportunity_target(
                            unit, visible_units)
                    if target is None and unit.attack_power <= 0 and visible_units:
                        focus = self.focus_targets.get(unit.team)
                        target = (focus if focus and focus.id in visible_ids
                                  else min(visible_units, key=unit.distance_to))
                elif not enemy_base.is_destroyed and \
                        unit.distance_to(enemy_base) <= unit.detect_range:
                    target = enemy_base
                elif visible_units:
                    focus = self.focus_targets.get(unit.team)
                    target = (focus if focus and focus.id in visible_ids
                              else min(visible_units, key=unit.distance_to))

                if target is enemy_base:
                    sighting_key = (unit.id, enemy_base.id)
                    if sighting_key not in self._base_sightings:
                        self._base_sightings.add(sighting_key)
                        self._add_log("Scout", f"{unit.team.title()} {unit.name} detected "
                                      f"{enemy_base.team.title()} {enemy_base.name}",
                                      record_category="scout", event="detected",
                                      unit_id=unit.id, source_id=unit.id,
                                      source_name=unit.name, team=unit.team,
                                      target_id=enemy_base.id, target_name=enemy_base.name,
                                      target_team=enemy_base.team, is_base=True)
                if target is not None:
                    eng.on_target_spotted(target.id)

    # ═══════════════════════════════════════════════════════════
    #  攻击结算
    # ═══════════════════════════════════════════════════════════

    def _resolve_attacks(self) -> None:
        """批量结算所有攻击意图，统计伤害和击杀。"""
        events = self.combat.resolve_all_attacks()
        unit_map = {u.id: u for u in self.units}
        # 基地也在 unit_map 中，便于通过 target_id 查找
        unit_map["red_base"] = self.battlefield.base_obj(TEAM_RED)
        unit_map["blue_base"] = self.battlefield.base_obj(TEAM_BLUE)
        for event in events:
            if self.htcs_enabled:
                # 排队时登记的是期望伤害；结算时用实际伤害替换，保证
                # 火力门看到的是“在途 + 已结算”的最新覆盖情况。
                self.damage_ledger.settle(
                    event.attacker_id, event.target_id, event.damage)
            attacker = unit_map.get(event.attacker_id)
            team = attacker.team if attacker else "unknown"
            if team in self.attack_count:
                self.attack_count[team] += 1
            if event.overkill > 0 and team in self.overkill_damage:
                self.overkill_damage[team] += event.overkill
            if event.is_miss:
                self._add_log("Attack",
                    f"{team.title()} {attacker.name if attacker else event.attacker_id} "
                    f"missed", record_category="combat", event="miss",
                    source_id=event.attacker_id, target_id=event.target_id,
                    team=team, damage=0, target_hp=event.target_hp)
                continue
            if team in self.hit_count:
                self.hit_count[team] += 1
                self.total_damage[team] += event.damage
            target = unit_map.get(event.target_id)
            if (self.htcs_enabled and event.role == "sead"
                    and not event.is_miss and target is not None):
                steps = int(self.htcs_config.get("sead_suppression_steps", 0))
                if steps > 0:
                    target.suppressed_until = max(
                        target.suppressed_until, self.time_step + steps)
                    self.record_event(
                        "coordination",
                        f"{team.title()} SEAD 压制 {target.name}："
                        f"{steps} 步内无法开火",
                        event="sead_suppressed", team=team,
                        source_id=attacker.id if attacker else None,
                        target_id=target.id, target_name=target.name,
                        suppressed_until=target.suppressed_until)
            if attacker and target:
                self._add_log("Attack",
                    f"{team.title()} {attacker.name} attacked "
                    f"{target.team.title()} {target.name}, "
                    f"damage={event.damage}, hp={event.target_hp}"
                    + (" (暴击)" if event.is_critical else ""),
                    record_category="combat", event="hit",
                    source_id=attacker.id, source_name=attacker.name,
                    target_id=target.id, target_name=target.name,
                    team=team, damage=event.damage, target_hp=event.target_hp,
                    is_critical=event.is_critical,
                    nominal_damage=event.nominal_damage,
                    overkill=event.overkill)
                if event.target_destroyed and target.id not in self._kill_credit_record:
                    self.kill_count[team] += 1
                    self._kill_credit_record.add(target.id)
                if event.target_destroyed and event.damage > 0:
                    self._record_destruction(target, attacker)
        self.attack_events.extend(events)

    # ═══════════════════════════════════════════════════════════
    #  辅助查询
    # ═══════════════════════════════════════════════════════════

    def active_units(self, team: str | None = None) -> list[Unit]:
        """返回未被摧毁的单位。"""
        units = [unit for unit in self.units if not unit.is_destroyed]
        if team:
            units = [unit for unit in units if unit.team == team]
        return units

    def enemy_units(self, team: str) -> list[Unit]:
        """返回指定阵营的敌方存活单位。"""
        return [unit for unit in self.active_units() if unit.team != team]

    def remaining_count(self, team: str) -> int:
        """返回指定阵营剩余单位数。"""
        return len(self.active_units(team))

    def _reconnaissance_phase(self) -> None:
        """重建即时视野：本人立即可见，其他单位等待广播交付。"""
        self._own_sightings.clear()
        unit_map = {unit.id: unit for unit in self.units}
        for unit in self.active_units():
            enemies = self.enemy_units(unit.team)
            spotted_targets = self.strategy.scan_enemies(unit, enemies)
            spotted_ids = {target.id for target in spotted_targets}
            previous_ids = self._last_scout_sightings.get(unit.id, set())
            self._own_sightings[unit.id] = spotted_ids
            for target_id in sorted(previous_ids - spotted_ids):
                target = unit_map.get(target_id)
                self._record_scout_loss(unit, target, target_id,
                                        "target_destroyed" if target and target.is_destroyed
                                        else "out_of_sight")
            for spotted in spotted_targets:
                delay = self._comm_delay(unit)
                avail_step = self.time_step + int(delay)
                targets = self.shared_targets[unit.team]
                previous_available = next((sighting.available_step for sighting in targets.records()
                                           if sighting.target.id == spotted.id), None)
                was_new = targets.sight(spotted, self.time_step, avail_step)
                if spotted.id not in previous_ids:
                    self._add_log("Scout",
                        f"{unit.team.title()} {unit.name} detected "
                        f"{spotted.team.title()} {spotted.name}",
                        record_category="scout", event="detected",
                        unit_id=unit.id, source_id=unit.id, source_name=unit.name,
                        team=unit.team, target_id=spotted.id,
                        target_name=spotted.name, target_team=spotted.team,
                        is_base=False)
                if was_new:
                    self._sharing_sources[(unit.team, spotted.id)] = unit.id
                    self._add_log("TargetPool",
                        f"{unit.team.title()} target pool add "
                        f"{spotted.team.title()} {spotted.name} "
                        f"(delay={int(delay)} steps)",
                        record_category="sharing", event="queued",
                        team=unit.team, source_id=unit.id, source_name=unit.name,
                        target_id=spotted.id, target_name=spotted.name,
                        delay_steps=int(delay), available_step=avail_step)
                elif (previous_available is not None and avail_step < previous_available
                      and (unit.team, spotted.id) not in self._sharing_delivered):
                    self._sharing_sources[(unit.team, spotted.id)] = unit.id
                    self.record_event("sharing", f"{unit.team.title()} 目标共享交付提前：{spotted.name}",
                                      event="rescheduled", team=unit.team,
                                      source_id=unit.id, source_name=unit.name,
                                      target_id=spotted.id, target_name=spotted.name,
                                      previous_available_step=previous_available,
                                      available_step=avail_step, delay_steps=int(delay))

            # 基地侦察与普通目标同样经过通信延迟，但使用独立战略池。
            # RDMA 关闭时不写入战略池，保持旧日志与旧行为完全不变。
            enemy_base = self.battlefield.base_obj(
                TEAM_BLUE if unit.team == TEAM_RED else TEAM_RED)
            if (self.cooperative_enabled and not enemy_base.is_destroyed
                    and unit.distance_to(enemy_base) <= unit.detect_range):
                own_bases = self._base_own_sightings.setdefault(unit.id, set())
                own_bases.add(enemy_base.id)
                delay = self._comm_delay(unit)
                avail_step = self.time_step + int(delay)
                pool = self.strategic_targets[unit.team]
                was_new = pool.sight(enemy_base, self.time_step, avail_step)
                if was_new:
                    self._sharing_sources[(unit.team, enemy_base.id)] = unit.id
                sighting_key = (unit.id, enemy_base.id)
                if sighting_key not in self._base_sightings:
                    self._base_sightings.add(sighting_key)
                    self._add_log("Scout", f"{unit.team.title()} {unit.name} detected "
                                  f"{enemy_base.team.title()} {enemy_base.name}",
                                  record_category="scout", event="detected",
                                  unit_id=unit.id, source_id=unit.id,
                                  source_name=unit.name, team=unit.team,
                                  target_id=enemy_base.id,
                                  target_name=enemy_base.name,
                                  target_team=enemy_base.team, is_base=True)
        self._refresh_strategic_targets()
        active_ids = set(self._own_sightings)
        for observer_id, previous_ids in self._last_scout_sightings.items():
            if observer_id in active_ids:
                continue
            observer = unit_map.get(observer_id)
            if observer:
                for target_id in sorted(previous_ids):
                    self._record_scout_loss(observer, unit_map.get(target_id),
                                            target_id, "observer_destroyed")
        self._last_scout_sightings = {
            unit_id: set(target_ids) for unit_id, target_ids in self._own_sightings.items()}

    def _record_scout_loss(self, observer: Unit, target: Unit | None,
                           target_id: str, reason: str) -> None:
        self._add_log("Scout", f"{observer.team.title()} {observer.name} lost sight of "
                      f"{target.name if target else target_id}",
                      record_category="scout", event="lost",
                      unit_id=observer.id, source_id=observer.id,
                      source_name=observer.name, team=observer.team,
                      target_id=target_id, target_name=target.name if target else target_id,
                      reason=reason)

    def _record_shared_deliveries(self) -> None:
        """只有共享目标池达到交付步数时才记录实际交付。"""
        unit_map = {unit.id: unit for unit in self.units}
        pools = list(self.shared_targets.items()) + list(
            self.strategic_targets.items())
        for team, targets in pools:
            for sighting in targets.records():
                target = sighting.target
                key = (team, target.id)
                if (sighting.available_step > self.time_step or target.is_destroyed
                        or key in self._sharing_delivered):
                    continue
                self._sharing_delivered.add(key)
                source_id = self._sharing_sources.get(key)
                source = unit_map.get(source_id)
                self._add_log("TargetPool",
                              f"{team.title()} shared target delivered: {target.name}",
                              record_category="sharing", event="delivered", team=team,
                              source_id=source_id, source_name=source.name if source else None,
                              target_id=target.id, target_name=target.name,
                              available_step=sighting.available_step,
                              last_seen_step=sighting.last_seen_step,
                              is_base=(target.unit_type == "base"))

    def _visible_targets_for(self, unit: Unit,
                             include_base: bool = False) -> list[Unit]:
        """该单位当前探测到的目标与已交付共享信息的并集。

        ``include_base`` 只供 RDMA 路径使用；默认 False 保证旧目标选择、
        界面与兼容测试仍只看到普通单位。
        """
        own_ids = self._own_sightings.get(unit.id, set())
        shared_ids = {target.id for target in
                      self.shared_targets[unit.team].values_available(self.time_step)}
        result = [target for target in self.enemy_units(unit.team)
                  if target.id in own_ids or target.id in shared_ids]
        if include_base and self._base_visible_to(unit):
            enemy_base = self.battlefield.base_obj(
                TEAM_BLUE if unit.team == TEAM_RED else TEAM_RED)
            result.append(enemy_base)
        return result

    def _comm_delay(self, unit: Unit) -> float:
        """计算通信延迟（步）：distance × COMM_DELAY_FACTOR。"""
        from core.units import CommandNode
        cmd = next((u for u in self.units if isinstance(u, CommandNode)
                    and u.team == unit.team and not u.is_destroyed), None)
        if cmd is None:
            return 99
        dist = ((unit.x - cmd.x) ** 2 + (unit.y - cmd.y) ** 2) ** 0.5
        return dist * COMM_DELAY_FACTOR

    def _select_focus_targets(self) -> None:
        """选择集火目标（合并立即视野 + 延迟共享池 + 目标锁定）。"""
        for team in (TEAM_RED, TEAM_BLUE):
            old_target = self.focus_targets.get(team)
            locked_id = self.focus_lock.get(team)
            if locked_id and not self.strategy.behavior_mgr.is_locked(team, locked_id):
                locked_id = None
                self.focus_lock[team] = None
            all_enemies = self.enemy_units(team)
            immediate_ids = set()
            for u in self.active_units(team):
                immediate_ids.update(self._own_sightings.get(u.id, set()))
            immediate = [e for e in all_enemies if e.id in immediate_ids]
            pool = list(self.shared_targets[team].values_available(self.time_step))
            merged = {e.id: e for e in pool}
            for e in immediate:
                merged[e.id] = e
            new_target = self.strategy.choose_focus_target(
                list(merged.values()),
                self.active_units(team),
                locked_id,
            )
            self.focus_targets[team] = new_target
            old_id = old_target.id if old_target else None
            new_id = new_target.id if new_target and not new_target.is_destroyed else None
            if old_id != new_id and new_target:
                self.focus_lock[team] = new_target.id
                self.strategy.behavior_mgr.lock_target(team, new_target.id, TARGET_LOCK_TIME)
                self._add_log("Focus",
                    f"{team.title()} focus target changed to {new_target.name}",
                    record_category="tactical", event="focus_changed", team=team,
                    previous_target_id=old_id, target_id=new_id,
                    target_name=new_target.name)
            elif old_id != new_id:
                self.focus_lock[team] = None
                self._add_log("Focus", f"{team.title()} focus target cleared",
                              record_category="tactical", event="focus_changed", team=team,
                              previous_target_id=old_id, target_id=None, target_name=None)

    def _update_strength(self) -> None:
        self.red_strength = team_strength(self.active_units(TEAM_RED))
        self.blue_strength = team_strength(self.active_units(TEAM_BLUE))

    def _update_priority_targets(self) -> None:
        for team in (TEAM_RED, TEAM_BLUE):
            self.priority_targets[team] = priority_targets(
                self.enemy_units(team), self.active_units(team))

    def _movement_phase(self) -> None:
        """移动阶段：协同目标推进、战术规避或巡逻。

        本阶段采用“先决策、后统一落位”：每个单位都基于本步开始时的
        位置快照做决策，决策完成后才把所有新位置一次性写回。否则先移动
        的单位会改变后移动单位看到的目标位置，等于让处理顺序靠后的阵营
        拿到额外信息（此前蓝方胜率偏高就包含这一因素）。快照做法让红蓝
        双方在同一份战场状态上决策，消除处理顺序带来的系统性偏差。
        """
        unit_map = {unit.id: unit for unit in self.units}
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            unit_map[base.id] = base
        active = self.active_units()
        snapshot = {unit.id: (unit.x, unit.y) for unit in active}
        pending: list[tuple[Unit, tuple[float, float]]] = []
        for unit in active:
            # 移动/规避策略仍以普通敌方单位作为威胁集合；基地只作为
            # RDMA 分配目标参与接近，不把静止基地误当成普通威胁。
            visible_for_me = self._visible_targets_for(unit)
            visible_ids = {enemy.id for enemy in visible_for_me}
            assignment_active = self._assignment_mode_active(unit.team)
            target_mode = None
            emergency_target = None
            staging_distance = None
            if assignment_active and self.htcs_enabled:
                plan_visible = self._visible_targets_for(
                    unit, include_base=True)
                plan_visible_ids = {target.id for target in plan_visible}
                plan = self._htcs_head_plan(unit, plan_visible_ids)
                target = (self._entity(plan.target_id)
                          if plan is not None else None)
                if plan is not None and target is not None:
                    eta = estimate_eta(unit, target, self.battlefield)
                    if self.time_step + eta < plan.window_start:
                        # 提前到达：在射程外沿待机，等 TOT 再进入。
                        target_mode = "staging"
                        staging_distance = staging_standoff(
                            unit, float(self.htcs_config.get(
                                "staging_standoff_ratio", 1.15)))
                    else:
                        target_mode = "assigned"
                else:
                    # 任务束耗尽/目标暂不可见：只侦察巡逻或机会射击，
                    # 不追逐新的可见敌人。
                    target = None
                    target_mode = "unassigned"
                    emergency_target = self._emergency_attack_target(
                        unit, visible_for_me)
            elif assignment_active:
                assigned_id = self.assignments[unit.team].assignments.get(unit.id)
                target = unit_map.get(assigned_id or "")
                target_visible = (
                    target is not None and not target.is_destroyed
                    and (target.id in visible_ids
                         or (target.unit_type == "base"
                             and self._base_visible_to(unit))))
                if target_visible:
                    target_mode = "assigned"
                else:
                    # 分配目标暂时不可见时，只做侦察/巡逻，不回退到其他敌人。
                    target = None
                    target_mode = "unassigned"
                    emergency_target = self._emergency_attack_target(
                        unit, visible_for_me)
            else:
                target = self.focus_targets.get(unit.team)
                if target and target.id not in visible_ids:
                    target = None
            was_evading = unit.id in self._evading_units
            start_x, start_y = snapshot[unit.id]
            unit.x, unit.y = start_x, start_y
            is_evading = self.strategy.move_unit(
                unit=unit,
                battlefield=self.battlefield,
                target=target,
                visible_enemies=visible_for_me,
                all_enemies=visible_for_me,
                target_mode=target_mode,
                emergency_target=emergency_target,
                staging_standoff=staging_distance,
            )
            pending.append((unit, (unit.x, unit.y)))
            # 立即还原到快照位置，保证后续单位看到的是同一份初始战场。
            unit.x, unit.y = start_x, start_y

            if is_evading and not was_evading:
                self._add_log("Evade",
                    f"{unit.team.title()} {unit.name} enters evade mode",
                    record_category="tactical", event="evade_started",
                    unit_id=unit.id, team=unit.team,
                    target_id=(target.id if target else
                               emergency_target.id if emergency_target else None))
                self._evading_units.add(unit.id)
            elif not is_evading:
                self._evading_units.discard(unit.id)

        # 所有决策完成后统一落位；落位顺序不再影响任何单位的判断。
        for unit, (x, y) in pending:
            unit.x, unit.y = x, y

    def _separate_overlapping_units(self) -> None:
        """移动后把过于接近的单位缓慢推开，防止同点重叠后互相锁死。

        策略层已改为“停在外围站位点”，本方法只是兜底：即使绕障/卡死恢复等
        路径把两个单位落到同一像素，也能在若干帧内重新分离。
        每帧最多推开 ``UNIT_SEPARATION_PUSH`` 像素，避免位置跳变。
        """
        movable = [unit for unit in self.active_units()
                   if unit.speed > 0 and unit.domain != UnitDomain.COMMAND]
        for index, first in enumerate(movable):
            for second in movable[index + 1:]:
                dx = second.x - first.x
                dy = second.y - first.y
                distance = math.hypot(dx, dy)
                if distance >= UNIT_SEPARATION_DISTANCE:
                    continue
                if distance < 1e-6:
                    angle = stable_unit_angle(first.id + second.id)
                    dx, dy = math.cos(angle), math.sin(angle)
                    distance = 1.0
                push = min(UNIT_SEPARATION_PUSH,
                           (UNIT_SEPARATION_DISTANCE - distance) / 2)
                ux, uy = dx / distance, dy / distance
                self._nudge_unit(first, -ux * push, -uy * push)
                self._nudge_unit(second, ux * push, uy * push)

    def _nudge_unit(self, unit: Unit, offset_x: float, offset_y: float) -> None:
        """小步平移单位；地面单位不能因此进入障碍物。"""
        target_x, target_y = self.battlefield.clamp_position(
            unit.x + offset_x, unit.y + offset_y)
        if unit.domain == UnitDomain.AIR:
            unit.x, unit.y = target_x, target_y
            return
        if self.battlefield.can_move_to(target_x, target_y, unit):
            unit.x, unit.y = target_x, target_y

    def _attack_phase(self) -> None:
        """攻击阶段：优先攻击集火目标，需通过交战状态检查。"""
        for unit in self.active_units():
            # SEAD 压制期：被压制单位不能发起新的攻击。
            if self.htcs_enabled and unit.suppressed_until > self.time_step:
                continue
            if not unit.engagement_state.can_attack:
                continue
            if self.htcs_enabled:
                self._htcs_attack_unit(unit)
                continue
            target = self._attack_target_for(unit)
            if target is None or target.is_destroyed:
                # 无可攻击目标：重置交战状态，避免卡在 ATTACK 无法退出
                unit.engagement_state.reset_to_search()
                continue
            intent = self.combat.queue_attack(
                unit, target, self.battlefield,
                is_evading=(unit.status == STATUS_EVADE))
            if intent:
                unit.engagement_state.on_attack_queued()
            else:
                # 防御：攻击加入队列失败，重置状态避免永久卡死
                unit.engagement_state.reset_to_search()

    def _htcs_plan_fire_ready(self, unit: Unit, plan: FirePlan,
                              target: Unit | None,
                              visible_ids: set[str]) -> bool:
        """真正排队射击前，用当前单位/目标状态重新检查全部开火条件。

        ``plan.reached`` 只记录历史到达，不参与本判断；目标移动后必须按
        当前距离、可见性、弹药与交战目标重新判定。
        """
        return bool(
            target is not None
            and not target.is_destroyed
            and plan.target_id in visible_ids
            and unit.can_attack(target)
            and unit.engagement_state.current_target_id == target.id
            and unit.suppressed_until <= self.time_step
        )

    def _htcs_attack_unit(self, unit: Unit) -> None:
        """HTCS 攻击：火力门 + 伤害账本 + 任务角色。"""
        eng = unit.engagement_state
        visible = self._visible_targets_for(unit, include_base=True)
        visible_ids = {target.id for target in visible}
        plan = self._htcs_head_plan(unit, visible_ids)
        if plan is not None:
            target = self._entity(plan.target_id)
            if plan.is_early(self.time_step):
                # 提前到达：保持待机，等待 TOT 窗口。
                return
            if not self._htcs_plan_fire_ready(
                    unit, plan, target, visible_ids):
                # 仍在接近/目标已不可见；移动阶段负责重新进入射程，
                # 不重置反应状态，也不消耗计划。
                return
            if not self._htcs_fire_allowed(
                    unit, target, self._htcs_expected_damage(unit, target)):
                return
            intent = self.combat.queue_attack(
                unit, target, self.battlefield,
                is_evading=(unit.status == STATUS_EVADE),
                role=plan.role)
            if intent:
                eng.on_attack_queued()
                # 排队时登记期望伤害；实际结算后由账本替换。
                self.damage_ledger.reserve(
                    unit.id, target.id,
                    float(intent.damage) * float(intent.hit_probability),
                    self.time_step, task_id=plan.task_id)
                self._htcs_consume_plan(unit, plan)
            else:
                eng.reset_to_search()
            return

        # 任务束已耗尽：只保留机会射击，不追逐新目标。
        if not bool(self.htcs_config.get("opportunity_fire", True)):
            eng.reset_to_search()
            return
        target = self._attack_target_for(unit)
        if target is None or target.is_destroyed:
            eng.reset_to_search()
            return
        if not self._htcs_fire_allowed(
                unit, target, self._htcs_expected_damage(unit, target)):
            return
        intent = self.combat.queue_attack(
            unit, target, self.battlefield,
            is_evading=(unit.status == STATUS_EVADE),
            role="opportunity")
        if intent:
            eng.on_attack_queued()
            self.damage_ledger.reserve(
                unit.id, target.id,
                float(intent.damage) * float(intent.hit_probability),
                self.time_step)
        else:
            eng.reset_to_search()

    def _attack_target_for(self, unit: Unit) -> Unit | None:
        """根据单位状态确定攻击目标，确保目标可被该单位攻击。

        RDMA 启用且本步已分配时：
        - 已分配：只允许 attack 分配目标，且必须与 EngagementState 当前
          目标一致；
        - 未分配：只允许 _emergency_attack_target() 给出的自卫目标。
        """
        assignment_active = self._assignment_mode_active(unit.team)
        visible = self._visible_targets_for(
            unit, include_base=assignment_active)
        visible_ids = {target.id for target in visible}
        eng = unit.engagement_state
        visible_units = [target for target in visible
                         if target.unit_type != "base"]

        if assignment_active and self.htcs_enabled:
            plans = self.fire_plans.get(unit.team, {}).get(unit.id) or []
            if plans:
                plan = plans[0]
                target = self._entity(plan.target_id)
                if (target is not None and not target.is_destroyed
                        and plan.target_id in visible_ids
                        and unit.can_attack(target)
                        and eng.current_target_id == plan.target_id):
                    return target
                return None
            opportunity = self._htcs_opportunity_target(unit, visible_units)
            if (opportunity is not None
                    and eng.current_target_id == opportunity.id):
                return opportunity
            return None

        if assignment_active:
            assigned_id = self.assignments[unit.team].assignments.get(unit.id)
            if assigned_id:
                if eng.current_target_id != assigned_id:
                    return None
                target = next((e for e in visible if e.id == assigned_id), None)
                if target is not None and unit.can_attack(target):
                    return target
                return None
            visible_units = [target for target in visible
                             if target.unit_type != "base"]
            emergency = self._emergency_attack_target(unit, visible_units)
            if (emergency is not None
                    and eng.current_target_id == emergency.id
                    and emergency.id in visible_ids):
                return emergency
            return None

        # 兼容路径：RDMA 未启用或本步未执行分配时保持旧逻辑。
        if unit.status == STATUS_EVADE:
            nearest = self.strategy.nearest_enemy(unit, visible)
            if nearest and unit.attack_range > 0 and unit.distance_to(nearest) <= unit.attack_range * 0.55:
                return nearest
            return None
        # 先检查集火目标是否可攻击，不可则从可见敌人中选择
        focus = self.focus_targets.get(unit.team)
        if focus and focus in visible and unit.can_attack(focus):
            return focus
        for e in sorted(visible, key=unit.distance_to):
            if unit.can_attack(e):
                return e
        return None

    def _update_destroyed_stats(self) -> None:
        """统计新摧毁单位数量，并清理绕障状态。"""
        for unit in self.units:
            if unit.is_destroyed and unit.id not in self._destroyed_record:
                unit.status = STATUS_DESTROYED
                unit.target_id = None
                self._destroyed_record.add(unit.id)
                self.destroyed_count[unit.team] += 1
                self._record_destruction(unit)
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if base.is_destroyed:
                self._record_destruction(base)
        # 清理已摧毁单位的绕障状态，防止内存泄漏
        active_ids = {u.id for u in self.units if not u.is_destroyed}
        cleanup_destroyed(active_ids)

    def _record_destruction(self, unit: Unit, killer: Unit | None = None) -> None:
        """记录第一次摧毁时刻，攻击者即使同步结算中已阵亡也保留击杀归因。"""
        if unit.id in self._destruction_ids:
            return
        self._destruction_ids.add(unit.id)
        is_base = unit.id in ("red_base", "blue_base")
        destroyed = {
            "unit_id": unit.id, "name": unit.name, "team": unit.team,
            "unit_type": unit.unit_type, "step": self.time_step,
            "elapsed_seconds": round(self.elapsed_seconds, 9),
            "killer_id": killer.id if killer else None,
            "killer_name": killer.name if killer else None, "is_base": is_base,
        }
        self.destroyed_units.append(destroyed)
        message = (f"{unit.team.title()} base was destroyed" if is_base
                   else f"{unit.team.title()} {unit.name} was destroyed")
        self._add_log("Destroyed", message, record_category="destroyed", event="destroyed",
                      source_id=destroyed["killer_id"], target_id=unit.id, **destroyed)

    def _record_unit_tactical_changes(self, initial: bool = False) -> None:
        for unit in self.units:
            behavior = self.strategy.behavior_mgr.current_behavior(unit.id)
            phase = unit.engagement_state.phase.name
            target_id = unit.engagement_state.current_target_id or unit.target_id
            assigned_id = self._assigned_target_id(unit)
            state = (unit.status, phase, target_id, behavior, unit.target_id,
                     assigned_id)
            previous = self._unit_tactical_state.get(unit.id)
            if state == previous:
                continue
            self._unit_tactical_state[unit.id] = state
            self.record_event("tactical", f"{unit.team.title()} {unit.name} 战术状态："
                              f"{unit.status} / {unit.engagement_state.phase_name}",
                              event="unit_state", unit_id=unit.id, unit_name=unit.name,
                              team=unit.team, status=unit.status, engagement=phase,
                              engagement_label=unit.engagement_state.phase_name,
                              target_id=target_id, behavior=behavior,
                              previous_status=previous[0] if previous else None,
                              previous_engagement=previous[1] if previous else None,
                              previous_target_id=previous[2] if previous else None,
                              behavior_label=BEHAVIOR_LABELS.get(behavior, "巡逻"),
                              command_target_id=unit.target_id,
                              assigned_target_id=assigned_id,
                              initial=initial)

    def _record_team_tactical_changes(self, initial: bool = False) -> None:
        red_strength = team_strength(self.active_units(TEAM_RED))
        blue_strength = team_strength(self.active_units(TEAM_BLUE))
        for team in (TEAM_RED, TEAM_BLUE):
            situation = situation_label(red_strength, blue_strength, team)
            tactics = tactics_label(situation)
            state = (situation, tactics)
            previous = self._team_tactical_state.get(team)
            if state == previous:
                continue
            self._team_tactical_state[team] = state
            focus = self.focus_targets.get(team)
            self.record_event("tactical", f"{team.title()} 态势：{situation}；战术：{tactics}",
                              event="team_state", team=team, situation=situation, tactics=tactics,
                              previous_situation=previous[0] if previous else None,
                              target_id=focus.id if focus and not focus.is_destroyed else None,
                              red_strength=red_strength, blue_strength=blue_strength,
                              initial=initial)

    def _attack_base_phase(self) -> None:
        """各单位攻击射程内的敌方基地（通过标准攻击队列）。
        基地为 BaseUnit（Unit 子类），通过 can_attack() 检查后走标准 queue_attack()。"""
        red_base = self.battlefield.base_obj(TEAM_RED)
        blue_base = self.battlefield.base_obj(TEAM_BLUE)
        for unit in self.active_units():
            if not unit.engagement_state.can_attack:
                continue
            if unit.ammo <= 0 or unit.attack_power <= 0:
                continue
            target_base = blue_base if unit.team == TEAM_RED else red_base
            if target_base.is_destroyed:
                continue
            # RDMA 本步已生效时，基地统一由 _attack_phase 按分配目标
            # 授权，不能再走旁路；RDMA 关闭或兼容调用时保持旧基地通道。
            if self._assignment_mode_active(unit.team):
                continue
            if not unit.can_attack(target_base):
                continue
            intent = self.combat.queue_attack(
                unit, target_base, self.battlefield,
                is_evading=(unit.status == STATUS_EVADE))
            if intent:
                unit.engagement_state.on_attack_queued()

    def _replenish_phase(self) -> None:
        """基地给周围友军补给弹药和血量。弹药每2帧补给1发。"""
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if base.is_destroyed:
                continue
            for unit in self.active_units(team):
                dist = ((unit.x - base.x) ** 2 + (unit.y - base.y) ** 2) ** 0.5
                if dist <= BASE_REPAIR_RADIUS:
                    unit.hp = min(unit.max_hp, unit.hp + BASE_REPAIR_PER_STEP)
                    last_step = self._last_ammo_resupply.get(unit.id, -99)
                    if self.time_step - last_step >= 2:
                        ammo_max = get_unit_stats(unit.unit_type)["ammo"]
                        unit.ammo = min(unit.ammo + 1, ammo_max)
                        self._last_ammo_resupply[unit.id] = self.time_step

    def _judge_winner(self) -> None:
        """先判定消灭/基地胜负；仍未决且达到上限时按剩余战力裁定。

        超时不再无条件判平局：先比较双方剩余战力，再比较敌方基地剩余
        血量比例，最后比较存活数；三项完全持平才判平局。这样长期僵持的
        对局也会给出明确的胜负，而不是每局都以 ``draw`` 收场。
        """
        red_alive = self.remaining_count(TEAM_RED)
        blue_alive = self.remaining_count(TEAM_BLUE)
        red_base_dead = self.battlefield.base_obj(TEAM_RED).is_destroyed
        blue_base_dead = self.battlefield.base_obj(TEAM_BLUE).is_destroyed

        if (red_alive == 0 or red_base_dead) and (blue_alive == 0 or blue_base_dead):
            self.winner = "draw"
            self.finish_reason = "base_destroyed" if red_base_dead or blue_base_dead else "elimination"
        elif red_alive == 0 or red_base_dead:
            self.winner = TEAM_BLUE
            self.finish_reason = "base_destroyed" if red_base_dead else "elimination"
        elif blue_alive == 0 or blue_base_dead:
            self.winner = TEAM_RED
            self.finish_reason = "base_destroyed" if blue_base_dead else "elimination"
        elif self.time_step >= self.max_steps:
            self.winner = self._step_limit_verdict() or "draw"
            self.finish_reason = "step_limit"

        if self.winner and not self._result_logged:
            if self.finish_reason != "step_limit":
                result_text = {
                    TEAM_RED: "Red wins",
                    TEAM_BLUE: "Blue wins",
                    "draw": "Draw",
                }[self.winner]
            elif self.winner == "draw":
                # 保持原有平局文案，供历史记录与测试兼容。
                result_text = f"达到时间步上限（{self.max_steps}），本局平局"
            else:
                side = "红方" if self.winner == TEAM_RED else "蓝方"
                result_text = (f"达到时间步上限（{self.max_steps}），"
                               f"按剩余战力判定{side}获胜")
            self._add_log("Result", result_text, record_category="result", event="finished",
                          winner=self.winner, finish_reason=self.finish_reason,
                          max_steps=self.max_steps,
                          red_remaining=red_alive, blue_remaining=blue_alive,
                          red_destroyed=self.destroyed_count[TEAM_RED],
                          blue_destroyed=self.destroyed_count[TEAM_BLUE],
                          red_base_hp=self.battlefield.base_obj(TEAM_RED).hp,
                          blue_base_hp=self.battlefield.base_obj(TEAM_BLUE).hp,
                          attacks=dict(self.attack_count), hits=dict(self.hit_count),
                          damage=dict(self.total_damage), kills=dict(self.kill_count))
            self._result_logged = True

    def _step_limit_verdict(self) -> str | None:
        """步数上限时的胜负裁定：剩余战力 → 敌方基地血量 → 存活数。

        返回获胜方队名；三项完全持平返回 ``None``（平局）。战力使用当前
        存活的实时快照，避免使用本步开始时缓存的旧值。
        """
        red_strength = team_strength(self.active_units(TEAM_RED))
        blue_strength = team_strength(self.active_units(TEAM_BLUE))
        red_base = self.battlefield.base_obj(TEAM_RED)
        blue_base = self.battlefield.base_obj(TEAM_BLUE)

        def base_ratio(base) -> float:
            return base.hp / max(1, base.max_hp)

        red_score = (red_strength, -base_ratio(blue_base),
                     self.remaining_count(TEAM_RED))
        blue_score = (blue_strength, -base_ratio(red_base),
                      self.remaining_count(TEAM_BLUE))
        if red_score > blue_score:
            return TEAM_RED
        if blue_score > red_score:
            return TEAM_BLUE
        return None

    def _cleanup_target_pools(self) -> None:
        """清理共享目标池中的无效目标。"""
        pools = [
            (team, targets, ())
            for team, targets in self.shared_targets.items()
        ] + [
            (team, targets, ("base",))
            for team, targets in self.strategic_targets.items()
        ]
        for team, targets, keep_stale_types in pools:
            for target_id, target, reason in targets.cleanup(
                    self.time_step, DETECTION_TIMEOUT_STEPS,
                    keep_stale_types=keep_stale_types):
                key = (team, target_id)
                delivered = key in self._sharing_delivered
                self._add_log(
                    "TargetPool",
                    f"{team.title()} target pool removed "
                    f"{target.team.title()} {target.name} ({reason})",
                    record_category="sharing", event="expired" if reason == "stale" else "removed",
                    team=team, target_id=target.id, target_name=target.name,
                    reason=reason, delivered=delivered,
                    source_id=self._sharing_sources.get(key),
                )
                self._sharing_delivered.discard(key)
                self._sharing_sources.pop(key, None)
                if target.unit_type == "base":
                    for own_bases in self._base_own_sightings.values():
                        own_bases.discard(target.id)
                    self._base_sightings = {
                        (observer_id, base_id)
                        for observer_id, base_id in self._base_sightings
                        if base_id != target.id
                    }
        # 结算造成的视野丢失也属于本步，避免结束局把丢失事件遗漏或延后。
        unit_map = {unit.id: unit for unit in self.units}
        for observer_id, target_ids in self._last_scout_sightings.items():
            observer = unit_map.get(observer_id)
            if observer is None:
                continue
            for target_id in sorted(tuple(target_ids)):
                target = unit_map.get(target_id)
                if observer.is_destroyed or target is None or target.is_destroyed:
                    self._record_scout_loss(observer, target, target_id,
                                            "observer_destroyed" if observer.is_destroyed
                                            else "target_destroyed")
                    target_ids.discard(target_id)
        bases = {self.battlefield.base_obj(team).id: self.battlefield.base_obj(team)
                 for team in (TEAM_RED, TEAM_BLUE)}
        for observer_id, base_id in sorted(tuple(self._base_sightings)):
            observer = unit_map.get(observer_id)
            base = bases.get(base_id)
            if observer and base and (observer.is_destroyed or base.is_destroyed):
                self._record_scout_loss(observer, base, base_id,
                                        "observer_destroyed" if observer.is_destroyed
                                        else "target_destroyed")
                self._base_sightings.discard((observer_id, base_id))
        for unit in self.units:
            if unit.is_destroyed:
                unit.target_id = None
                self._own_sightings.pop(unit.id, None)
                self._base_own_sightings.pop(unit.id, None)
        alive_ids = {unit.id for unit in self.active_units()}
        for own_ids in self._own_sightings.values():
            own_ids.intersection_update(alive_ids)

    def _capture_replay_frame(self) -> None:
        """采样当前步的单位与基地状态，供运行记录回放。

        单位顺序在首帧冻结；本局内不增删单位，因此帧号恒等于 time_step。
        """
        self.frame_buffer.capture(self.units,
                                  self.battlefield.base_obj(TEAM_RED),
                                  self.battlefield.base_obj(TEAM_BLUE))

    def _tick_attack_events(self) -> None:
        """更新攻击连线特效生命周期。"""
        for event in self.attack_events:
            event.life -= 1
        self.attack_events = [event for event in self.attack_events if event.life > 0]

    def focus_target_name(self, team: str) -> str:
        """返回面板显示用的集火目标名称。"""
        target = self.focus_targets.get(team)
        if target is None or target.is_destroyed:
            return "无"
        return target.name

    def assigned_target_id(self, unit_id: str) -> str | None:
        """返回单位的协同分配目标 ID（未启用/未分配时为 None）。"""
        for team in (TEAM_RED, TEAM_BLUE):
            target_id = self.assignments[team].assignments.get(unit_id)
            if target_id is not None:
                return target_id
        return None

    def assigned_target_name(self, unit_id: str) -> str:
        target_id = self.assigned_target_id(unit_id)
        if target_id is None:
            return "无"
        for unit in self.units:
            if unit.id == target_id:
                return unit.name
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if base.id == target_id:
                return base.name
        return target_id

    def _primary_assignment_name(self, team: str) -> str:
        result = self.assignments.get(team)
        target_id = result.primary_target_id if result else None
        if not target_id:
            return "无"
        for unit in self.units:
            if unit.id == target_id:
                return unit.name
        for base_team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(base_team)
            if base.id == target_id:
                return base.name
        return target_id

    def _add_log(self, category: str, message: str, *,
                 record_category: str | None = None, **fields) -> None:
        """保留兼容日志标签；全部文本另存为带模拟时间的结构化历史。"""
        line = f"[{category}] {message}"
        print(line)
        self.combat_logs.append(line)
        self.combat_logs = self.combat_logs[-12:]
        categories = {"Scout": "scout", "TargetPool": "sharing", "Destroyed": "destroyed",
                      "Focus": "tactical", "Evade": "tactical", "Result": "result",
                      "Attack": "combat", "Assign": "coordination"}
        self.record_event(record_category or categories.get(category, "combat"), message,
                          log_category=category, **fields)

    def status_snapshot(self) -> dict:
        """为 UI 面板提供统计快照。"""
        red_sit = situation_label(self.red_strength, self.blue_strength, TEAM_RED)
        blue_sit = situation_label(self.red_strength, self.blue_strength, TEAM_BLUE)
        red_active = self.active_units(TEAM_RED)
        blue_active = self.active_units(TEAM_BLUE)
        red_behavior = "待命"
        blue_behavior = "待命"
        if red_active:
            red_behavior = BEHAVIOR_LABELS.get(
                self.strategy.behavior_mgr.current_behavior(red_active[0].id), "巡逻")
        if blue_active:
            blue_behavior = BEHAVIOR_LABELS.get(
                self.strategy.behavior_mgr.current_behavior(blue_active[0].id), "巡逻")

        return {
            "time_step": self.time_step,
            "max_steps": self.max_steps,
            "elapsed_seconds": self.elapsed_seconds,
            "step_duration_seconds": self.step_duration_seconds,
            "record_count": len(self.records),
            "finish_reason": self.finish_reason,
            "red_remaining": self.remaining_count(TEAM_RED),
            "blue_remaining": self.remaining_count(TEAM_BLUE),
            "red_destroyed": self.destroyed_count[TEAM_RED],
            "blue_destroyed": self.destroyed_count[TEAM_BLUE],
            "red_kills": self.kill_count[TEAM_RED],
            "blue_kills": self.kill_count[TEAM_BLUE],
            "red_attacks": self.attack_count[TEAM_RED],
            "blue_attacks": self.attack_count[TEAM_BLUE],
            "red_hits": self.hit_count[TEAM_RED],
            "blue_hits": self.hit_count[TEAM_BLUE],
            "red_damage": self.total_damage[TEAM_RED],
            "blue_damage": self.total_damage[TEAM_BLUE],
            "red_detected": len(self.red_detected_targets),
            "blue_detected": len(self.blue_detected_targets),
            "red_focus": self.focus_target_name(TEAM_RED),
            "blue_focus": self.focus_target_name(TEAM_BLUE),
            "cooperative_enabled": self.cooperative_enabled,
            "cooperative_mode": self.cooperative_mode,
            "red_wave": self.assignments[TEAM_RED].wave_id,
            "blue_wave": self.assignments[TEAM_BLUE].wave_id,
            "red_doctrine": self.assignments[TEAM_RED].doctrine,
            "blue_doctrine": self.assignments[TEAM_BLUE].doctrine,
            "red_fire_plans": sum(len(plans) for plans in
                                  self.fire_plans[TEAM_RED].values()),
            "blue_fire_plans": sum(len(plans) for plans in
                                   self.fire_plans[TEAM_BLUE].values()),
            "red_suppressed": len([u for u in red_active
                                   if u.suppressed_until > self.time_step]),
            "blue_suppressed": len([u for u in blue_active
                                    if u.suppressed_until > self.time_step]),
            "red_reattack_targets": len(self._htcs_reattack[TEAM_RED]),
            "blue_reattack_targets": len(self._htcs_reattack[TEAM_BLUE]),
            "red_assigned": len(self.assignments[TEAM_RED].assignments),
            "blue_assigned": len(self.assignments[TEAM_BLUE].assignments),
            "red_unassigned": len({
                unit.id for unit in red_active
                if unit.attack_power > 0 and unit.unit_type != "command_node"
            } - set(self.assignments[TEAM_RED].assignments)),
            "blue_unassigned": len({
                unit.id for unit in blue_active
                if unit.attack_power > 0 and unit.unit_type != "command_node"
            } - set(self.assignments[TEAM_BLUE].assignments)),
            "red_assignment_primary": self._primary_assignment_name(TEAM_RED),
            "blue_assignment_primary": self._primary_assignment_name(TEAM_BLUE),
            "red_assignment_primary_id": self.assignments[TEAM_RED].primary_target_id,
            "blue_assignment_primary_id": self.assignments[TEAM_BLUE].primary_target_id,
            "red_base_assigned": sum(
                1 for target_id in self.assignments[TEAM_RED].assignments.values()
                if target_id == self.battlefield.base_obj(TEAM_BLUE).id),
            "blue_base_assigned": sum(
                1 for target_id in self.assignments[TEAM_BLUE].assignments.values()
                if target_id == self.battlefield.base_obj(TEAM_RED).id),
            "red_evading": len([u for u in self.active_units(TEAM_RED) if u.status == STATUS_EVADE]),
            "blue_evading": len([u for u in self.active_units(TEAM_BLUE) if u.status == STATUS_EVADE]),
            "evading_units": ", ".join(u.name for u in self.active_units() if u.status == STATUS_EVADE),
            "red_strength": self.red_strength,
            "blue_strength": self.blue_strength,
            "red_situation": red_sit,
            "blue_situation": blue_sit,
            "red_tactics": tactics_label(red_sit),
            "blue_tactics": tactics_label(blue_sit),
            "red_behavior": red_behavior,
            "blue_behavior": blue_behavior,
            "red_base_hp": self.battlefield.base_obj(TEAM_RED).hp,
            "blue_base_hp": self.battlefield.base_obj(TEAM_BLUE).hp,
            "red_base_max": self.battlefield.base_obj(TEAM_RED).max_hp,
            "blue_base_max": self.battlefield.base_obj(TEAM_BLUE).max_hp,
            "winner": self.winner,
        }
