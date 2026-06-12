"""仿真主控模块。

第十阶段集成：
- 每帧更新交战状态机
- 攻击改为队列模式，统一结算
- 反应延迟消除先手优势
"""

from __future__ import annotations

from config import (BASE_REPAIR_PER_STEP, BASE_REPAIR_RADIUS, COMM_DELAY_FACTOR,
                     DETECTION_TIMEOUT_STEPS, STATUS_DESTROYED, STATUS_EVADE,
                     TARGET_LOCK_TIME, TEAM_BLUE, TEAM_RED)
from core.battlefield import Battlefield
from core.behavior import BEHAVIOR_LABELS, STATUS_TO_BEHAVIOR
from core.combat import AttackEvent, CombatSystem
from core.engagement import EngagementPhase
from core.strategy import StrategyEngine
from core.target_pool import TargetPool
from core.threat import priority_targets, situation_label, tactics_label, team_strength
from core.units import Unit


class Simulator:
    """按时间步推进侦察、集火、规避、攻击和胜负判断。"""

    def __init__(self, battlefield: Battlefield, units: list[Unit]):
        self.battlefield = battlefield
        self.units = units
        self.time_step = 0
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
        self.total_damage = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.winner: str | None = None
        self.attack_events: list[AttackEvent] = []
        self.combat_logs: list[str] = []

        self.show_wrecks = True
        self._own_sightings: dict[str, set[str]] = {}
        self._destroyed_record: set[str] = set()
        self._kill_credit_record: set[str] = set()
        self._evading_units: set[str] = set()
        self._result_logged = False

    def step(self) -> None:
        """推进一个仿真时间步。

        流程：
        1. 清理已摧毁单位和无效目标；
        2. 更新战力/优先级；
        3. 更新交战状态机；
        4. 侦察（更新共享目标池 + 交战状态）；
        5. 选择集火目标；
        6. 移动/规避；
        7. 攻击（加入意图队列）；
        8. 攻击基地（加入意图队列）；
        9. 统一结算所有攻击意图；
        10. 补给、统计、胜负。
        """
        if self.winner:
            self._tick_attack_events()
            return

        self.time_step += 1
        self._update_strength()
        self._update_priority_targets()
        self.strategy.behavior_mgr.tick_target_locks()
        self.strategy.behavior_mgr.tick_cooldowns()
        self._cleanup_target_pools()
        self._update_engagement_states()
        self._reconnaissance_phase()
        self._select_focus_targets()
        self._movement_phase()
        self._attack_phase()
        self._attack_base_phase()
        self._resolve_attacks()
        self._replenish_phase()
        self._update_destroyed_stats()
        self._cleanup_target_pools()
        self._select_focus_targets()
        self._judge_winner()
        self._tick_attack_events()

    # ═══════════════════════════════════════════════════════════
    #  交战状态更新
    # ═══════════════════════════════════════════════════════════

    def _update_engagement_states(self) -> None:
        """更新所有单位的交战状态机。"""
        for unit in self.active_units():
            eng = unit.engagement_state
            # 检查反应期目标是否仍然可见
            if eng.phase == EngagementPhase.REACTING and eng.current_target_id:
                own_ids = self._own_sightings.get(unit.id, set())
                pool = {e.id for e in
                        self.shared_targets[unit.team].values_available(self.time_step)}
                visible_ids = own_ids | pool
                if eng.current_target_id not in visible_ids:
                    eng.on_target_lost()
            eng.tick()

    # ═══════════════════════════════════════════════════════════
    #  攻击结算
    # ═══════════════════════════════════════════════════════════

    def _resolve_attacks(self) -> None:
        """批量结算所有攻击意图，统计伤害和击杀。"""
        events = self.combat.resolve_all_attacks()
        unit_map = {u.id: u for u in self.units}
        for event in events:
            attacker = unit_map.get(event.attacker_id)
            team = attacker.team if attacker else "unknown"
            if event.is_miss:
                self._add_log("Attack",
                    f"{team.title()} {attacker.name if attacker else event.attacker_id} "
                    f"missed")
                continue
            self.attack_count[team] += 1
            self.total_damage[team] += event.damage
            target = unit_map.get(event.target_id)
            if attacker and target:
                self._add_log("Attack",
                    f"{team.title()} {attacker.name} attacked "
                    f"{target.team.title()} {target.name}, "
                    f"damage={event.damage}, hp={target.hp}"
                    + (" (暴击)" if event.is_critical else ""))
                if event.target_destroyed and target.id not in self._kill_credit_record:
                    self.kill_count[team] += 1
                    self._kill_credit_record.add(target.id)
            elif attacker and event.target_id.endswith("_base"):
                base_team = event.target_id.replace("_base", "")
                self._add_log("Attack",
                    f"{team.title()} {attacker.name} attacked {base_team.title()} base, "
                    f"damage={event.damage}")
                base = self.battlefield.base_obj(base_team)
                if base.is_destroyed:
                    self._add_log("Destroyed",
                        f"{base_team.title()} base was destroyed")
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
        """侦察阶段：发现目标→自己立即可见，广播有延迟，更新交战状态。"""
        for unit in self.active_units():
            enemies = self.enemy_units(unit.team)
            if unit.id not in self._own_sightings:
                self._own_sightings[unit.id] = set()
            for spotted in self.strategy.scan_enemies(unit, enemies):
                self._own_sightings[unit.id].add(spotted.id)
                delay = self._comm_delay(unit)
                avail_step = self.time_step + int(delay)
                targets = self.shared_targets[unit.team]
                was_new = targets.sight(spotted, self.time_step, avail_step)
                if was_new:
                    self._add_log("Scout",
                        f"{unit.team.title()} {unit.name} detected "
                        f"{spotted.team.title()} {spotted.name}")
                    self._add_log("TargetPool",
                        f"{unit.team.title()} target pool add "
                        f"{spotted.team.title()} {spotted.name} "
                        f"(delay={int(delay)} steps)")
                # 通知交战状态机：发现目标
                unit.engagement_state.on_target_spotted(spotted.id)

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
            old_id = old_target.id if old_target and not old_target.is_destroyed else None
            new_id = new_target.id if new_target and not new_target.is_destroyed else None
            if old_id != new_id and new_target:
                self.focus_lock[team] = new_target.id
                self.strategy.behavior_mgr.lock_target(team, new_target.id, TARGET_LOCK_TIME)
                self._add_log("Focus",
                    f"{team.title()} focus target changed to {new_target.name}")
            elif old_id != new_id:
                self.focus_lock[team] = None

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
            own_ids = self._own_sightings.get(unit.id, set())
            all_enemies = self.enemy_units(unit.team)
            shared = [e for e in self.shared_targets[unit.team].values_available(self.time_step)
                      if e.id in {x.id for x in all_enemies}]
            own = [e for e in all_enemies if e.id in own_ids]
            seen = {e.id: e for e in shared}
            for e in own:
                seen[e.id] = e
            visible_for_me = list(seen.values())
            was_evading = unit.id in self._evading_units
            is_evading = self.strategy.move_unit(
                unit=unit,
                battlefield=self.battlefield,
                target=target,
                visible_enemies=visible_for_me,
                all_enemies=self.enemy_units(unit.team),
            )

            if is_evading and not was_evading:
                self._add_log("Evade",
                    f"{unit.team.title()} {unit.name} enters evade mode")
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
        if unit.status == STATUS_EVADE:
            nearest = self.strategy.nearest_enemy(unit, self.enemy_units(unit.team))
            if nearest and unit.attack_range > 0 and unit.distance_to(nearest) <= unit.attack_range * 0.55:
                return nearest
            return None
        # 先检查集火目标是否可攻击，不可则从可见敌人中选择
        focus = self.focus_targets.get(unit.team)
        if focus and not focus.is_destroyed and unit.can_attack(focus):
            return focus
        all_enemies = self.enemy_units(unit.team)
        own_ids = self._own_sightings.get(unit.id, set())
        visible = [e for e in all_enemies if e.id in own_ids]
        for e in sorted(visible, key=unit.distance_to):
            if unit.can_attack(e):
                return e
        return None

    def _update_destroyed_stats(self) -> None:
        """统计新摧毁单位数量。"""
        for unit in self.units:
            if unit.is_destroyed and unit.id not in self._destroyed_record:
                unit.status = STATUS_DESTROYED
                unit.target_id = None
                self._destroyed_record.add(unit.id)
                self.destroyed_count[unit.team] += 1
                self._add_log("Destroyed",
                    f"{unit.team.title()} {unit.name} was destroyed")

    def _attack_base_phase(self) -> None:
        """各单位攻击射程内的敌方基地（通过意图队列），需通过交战状态检查。"""
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
            dist = ((unit.x - target_base.x) ** 2 + (unit.y - target_base.y) ** 2) ** 0.5
            if dist > unit.attack_range:
                continue
            if not unit.can_attack_ground:
                continue
            intent = self.combat.queue_attack_base(unit, target_base)
            if intent:
                unit.engagement_state.on_attack_queued()

    def _replenish_phase(self) -> None:
        """基地给周围友军补给弹药和血量。"""
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if base.is_destroyed:
                continue
            for unit in self.active_units(team):
                dist = ((unit.x - base.x) ** 2 + (unit.y - base.y) ** 2) ** 0.5
                if dist <= BASE_REPAIR_RADIUS:
                    unit.hp = min(unit.max_hp, unit.hp + BASE_REPAIR_PER_STEP)
                    unit.ammo = min(unit.ammo + 1, 10)

    def _judge_winner(self) -> None:
        """判断胜负：某方全部单位被摧毁或基地被摧毁。"""
        red_alive = self.remaining_count(TEAM_RED)
        blue_alive = self.remaining_count(TEAM_BLUE)
        red_base_dead = self.battlefield.base_obj(TEAM_RED).is_destroyed
        blue_base_dead = self.battlefield.base_obj(TEAM_BLUE).is_destroyed

        if (red_alive == 0 or red_base_dead) and (blue_alive == 0 or blue_base_dead):
            self.winner = "draw"
        elif red_alive == 0 or red_base_dead:
            self.winner = TEAM_BLUE
        elif blue_alive == 0 or blue_base_dead:
            self.winner = TEAM_RED

        if self.winner and not self._result_logged:
            result_text = {
                TEAM_RED: "Red wins",
                TEAM_BLUE: "Blue wins",
                "draw": "Draw",
            }[self.winner]
            self._add_log("Result", result_text)
            self._result_logged = True

    def _cleanup_target_pools(self) -> None:
        """清理共享目标池中的无效目标。"""
        for team, targets in self.shared_targets.items():
            for _, target, reason in targets.cleanup(self.time_step, DETECTION_TIMEOUT_STEPS):
                self._add_log(
                    "TargetPool",
                    f"{team.title()} target pool removed "
                    f"{target.team.title()} {target.name} ({reason})",
                )
        for unit in self.units:
            if unit.is_destroyed:
                unit.target_id = None

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

    def _add_log(self, category: str, message: str) -> None:
        """记录最近若干条战斗日志，同时输出到控制台。"""
        line = f"[{category}] {message}"
        print(line)
        self.combat_logs.append(line)
        self.combat_logs = self.combat_logs[-12:]

    def status_snapshot(self) -> dict[str, int | str | None]:
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
            "red_remaining": self.remaining_count(TEAM_RED),
            "blue_remaining": self.remaining_count(TEAM_BLUE),
            "red_destroyed": self.destroyed_count[TEAM_RED],
            "blue_destroyed": self.destroyed_count[TEAM_BLUE],
            "red_kills": self.kill_count[TEAM_RED],
            "blue_kills": self.kill_count[TEAM_BLUE],
            "red_attacks": self.attack_count[TEAM_RED],
            "blue_attacks": self.attack_count[TEAM_BLUE],
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
