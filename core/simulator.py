"""仿真主控模块。

第十阶段集成：
- 每帧更新交战状态机
- 攻击改为队列模式，统一结算
- 反应延迟消除先手优势
"""

from __future__ import annotations

import math
from numbers import Real

from config import (BASE_REPAIR_PER_STEP, BASE_REPAIR_RADIUS, COMM_DELAY_FACTOR,
                     DETECTION_TIMEOUT_STEPS, MAX_CONFIGURABLE_STEPS,
                     MAX_SIMULATION_STEPS, MAX_STEP_DURATION_SECONDS,
                     MIN_STEP_DURATION_SECONDS, SIMULATION_INTERVAL_MS,
                     STATUS_DESTROYED, STATUS_EVADE, TARGET_LOCK_TIME, TEAM_BLUE, TEAM_RED)
from core.battlefield import Battlefield
from core.behavior import BEHAVIOR_LABELS
from core.combat import AttackEvent, CombatSystem
from core.engagement import EngagementPhase
from core.pathfinding import cleanup_destroyed
from core.strategy import StrategyEngine
from core.target_pool import TargetPool
from core.threat import priority_targets, situation_label, tactics_label, team_strength
from core.unit_config_loader import get_unit_stats
from core.units import Unit


class Simulator:
    """按时间步推进侦察、集火、规避、攻击和胜负判断。"""

    def __init__(self, battlefield: Battlefield, units: list[Unit],
                 max_steps: int = MAX_SIMULATION_STEPS,
                 step_duration_seconds: float = SIMULATION_INTERVAL_MS / 1000):
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
            raise ValueError("最大运行步数必须为 1 至 1000000 的正整数")
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
        self._update_engagement_states()
        self._record_unit_tactical_changes()
        self._select_focus_targets()
        self._record_team_tactical_changes()
        self._movement_phase()
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

    # ═══════════════════════════════════════════════════════════
    #  交战状态更新
    # ═══════════════════════════════════════════════════════════

    def _update_engagement_states(self) -> None:
        """用本步有效视野推进状态；新发现目标从下一步累计反应期。"""
        for unit in self.active_units():
            eng = unit.engagement_state
            visible = self._visible_targets_for(unit)
            visible_ids = {target.id for target in visible}
            enemy_base = self.battlefield.base_obj(
                TEAM_BLUE if unit.team == TEAM_RED else TEAM_RED)
            if eng.phase in (EngagementPhase.REACTING, EngagementPhase.ATTACK) and eng.current_target_id:
                tid = eng.current_target_id
                # 基地是固定战略目标，发现后保持有效，直到被摧毁。
                base_known = tid == enemy_base.id and not enemy_base.is_destroyed
                if not base_known and tid not in visible_ids:
                    eng.reset_to_search()
            eng.tick()
            if eng.phase == EngagementPhase.SEARCH:
                if not enemy_base.is_destroyed and unit.distance_to(enemy_base) <= unit.detect_range:
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
                    eng.on_target_spotted(enemy_base.id)
                elif visible:
                    focus = self.focus_targets.get(unit.team)
                    target = focus if focus and focus.id in visible_ids else min(visible, key=unit.distance_to)
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
            attacker = unit_map.get(event.attacker_id)
            team = attacker.team if attacker else "unknown"
            if team in self.attack_count:
                self.attack_count[team] += 1
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
                    is_critical=event.is_critical)
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
        for team, targets in self.shared_targets.items():
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
                              last_seen_step=sighting.last_seen_step)

    def _visible_targets_for(self, unit: Unit) -> list[Unit]:
        """该单位当前探测到的目标与已交付共享信息的并集。"""
        own_ids = self._own_sightings.get(unit.id, set())
        shared_ids = {target.id for target in
                      self.shared_targets[unit.team].values_available(self.time_step)}
        return [target for target in self.enemy_units(unit.team)
                if target.id in own_ids or target.id in shared_ids]

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
        """移动阶段：集火推进、战术规避或巡逻。"""
        for unit in self.active_units():
            target = self.focus_targets.get(unit.team)
            visible_for_me = self._visible_targets_for(unit)
            if target and target.id not in {enemy.id for enemy in visible_for_me}:
                target = None
            was_evading = unit.id in self._evading_units
            is_evading = self.strategy.move_unit(
                unit=unit,
                battlefield=self.battlefield,
                target=target,
                visible_enemies=visible_for_me,
                all_enemies=visible_for_me,
            )

            if is_evading and not was_evading:
                self._add_log("Evade",
                    f"{unit.team.title()} {unit.name} enters evade mode",
                    record_category="tactical", event="evade_started",
                    unit_id=unit.id, team=unit.team,
                    target_id=target.id if target else None)
                self._evading_units.add(unit.id)
            elif not is_evading:
                self._evading_units.discard(unit.id)

    def _attack_phase(self) -> None:
        """攻击阶段：优先攻击集火目标，需通过交战状态检查。"""
        for unit in self.active_units():
            if not unit.engagement_state.can_attack:
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

    def _attack_target_for(self, unit: Unit) -> Unit | None:
        """根据单位状态确定攻击目标，确保目标可被该单位攻击。"""
        visible = self._visible_targets_for(unit)
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
            state = (unit.status, phase, target_id, behavior, unit.target_id)
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
        """先判定消灭/基地胜负；仍未决且达到演示上限时结束为平局。"""
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
            self.winner = "draw"
            self.finish_reason = "step_limit"

        if self.winner and not self._result_logged:
            result_text = (f"达到时间步上限（{self.max_steps}），本局平局"
                           if self.finish_reason == "step_limit" else {
                               TEAM_RED: "Red wins",
                               TEAM_BLUE: "Blue wins",
                               "draw": "Draw",
                           }[self.winner])
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

    def _cleanup_target_pools(self) -> None:
        """清理共享目标池中的无效目标。"""
        for team, targets in self.shared_targets.items():
            for target_id, target, reason in targets.cleanup(self.time_step, DETECTION_TIMEOUT_STEPS):
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
        alive_ids = {unit.id for unit in self.active_units()}
        for own_ids in self._own_sightings.values():
            own_ids.intersection_update(alive_ids)

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

    def _add_log(self, category: str, message: str, *,
                 record_category: str | None = None, **fields) -> None:
        """保留兼容日志标签；全部文本另存为带模拟时间的结构化历史。"""
        line = f"[{category}] {message}"
        print(line)
        self.combat_logs.append(line)
        self.combat_logs = self.combat_logs[-12:]
        categories = {"Scout": "scout", "TargetPool": "sharing", "Destroyed": "destroyed",
                      "Focus": "tactical", "Evade": "tactical", "Result": "result",
                      "Attack": "combat"}
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
