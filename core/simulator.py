"""仿真主控模块。"""

from __future__ import annotations

from config import (BASE_REPAIR_PER_STEP, BASE_REPAIR_RADIUS, COMM_DELAY_FACTOR,
                     DETECTION_TIMEOUT_STEPS, STATUS_DESTROYED, STATUS_EVADE,
                     TARGET_LOCK_TIME, TEAM_BLUE, TEAM_RED)
from core.battlefield import Battlefield
from core.behavior import BEHAVIOR_LABELS, STATUS_TO_BEHAVIOR
from core.combat import AttackEvent, CombatSystem
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
        # 按需求提供明确命名的阵营目标池，二者与 shared_targets 指向同一个字典。
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
        self._own_sightings: dict[str, set[str]] = {}  # unit_id -> immediate sightings
        self._destroyed_record: set[str] = set()
        self._kill_credit_record: set[str] = set()
        self._evading_units: set[str] = set()
        self._result_logged = False

    def step(self) -> None:
        """推进一个仿真时间步。

        标准流程：
        1. 清理已摧毁单位和无效目标；
        2. 执行侦察，更新共享目标池；
        3. 每个阵营选择集火目标；
        4. 每个单位进行状态决策；
        5. 单位移动或规避；
        6. 执行攻击结算；
        7. 更新统计数据；
        8. 判断胜负。
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
        self._reconnaissance_phase()
        self._select_focus_targets()
        self._movement_phase()
        self._attack_phase()
        self._attack_base_phase()
        self._replenish_phase()
        self._update_destroyed_stats()
        self._cleanup_target_pools()
        self._select_focus_targets()
        self._judge_winner()
        self._tick_attack_events()

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
        """侦察阶段：发现目标→自己立即可见，广播有延迟。"""
        for unit in self.active_units():
            enemies = self.enemy_units(unit.team)
            # 初始化自己的即时视野
            if unit.id not in self._own_sightings:
                self._own_sightings[unit.id] = set()
            for spotted in self.strategy.scan_enemies(unit, enemies):
                # 自己立即看到
                self._own_sightings[unit.id].add(spotted.id)
                # 广播给共享池（含通信延迟）
                delay = self._comm_delay(unit)
                avail_step = self.time_step + int(delay)
                targets = self.shared_targets[unit.team]
                was_new = targets.sight(spotted, self.time_step, avail_step)
                if was_new:
                    self._add_log("Scout",
                        f"{unit.team.title()} {unit.name} detected {spotted.team.title()} {spotted.name}")
                    self._add_log("TargetPool",
                        f"{unit.team.title()} target pool add {spotted.team.title()} {spotted.name} "
                        f"(delay={int(delay)} steps)")

    def _comm_delay(self, unit: Unit) -> float:
        """计算通信延迟（步）：distance × COMM_DELAY_FACTOR。"""
        from core.units import CommandNode
        cmd = next((u for u in self.units if isinstance(u, CommandNode)
                    and u.team == unit.team and not u.is_destroyed), None)
        if cmd is None:
            return 99  # 指挥节点被毁 → 几乎无法通信
        dist = ((unit.x - cmd.x) ** 2 + (unit.y - cmd.y) ** 2) ** 0.5
        return dist * COMM_DELAY_FACTOR

    def _select_focus_targets(self) -> None:
        """选择集火目标（合并立即视野 + 延迟共享池 + 目标锁定）。"""
        for team in (TEAM_RED, TEAM_BLUE):
            old_target = self.focus_targets.get(team)
            locked_id = self.focus_lock.get(team)
            # 合并：所有队员立即看到的 + 共享池延迟已到的
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
                self._add_log("Focus", f"{team.title()} focus target changed to {new_target.name}")
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
            # 自己看到的 + 共享池已延迟到达的
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
                self._add_log("Evade", f"{unit.team.title()} {unit.name} enters evade mode")
                self._evading_units.add(unit.id)
            elif not is_evading:
                self._evading_units.discard(unit.id)

    def _attack_phase(self) -> None:
        """攻击阶段：优先攻击阵营集火目标，规避状态下只允许近距离自卫。"""
        events: list[AttackEvent] = []
        for unit in self.active_units():
            target = self._attack_target_for(unit)
            if target is None or target.is_destroyed:
                continue
            was_evading = unit.status == STATUS_EVADE
            event = self.combat.attack(unit, target)
            if was_evading and event:
                unit.status = STATUS_EVADE
            if event:
                self.attack_count[unit.team] += 1
                self.total_damage[unit.team] += event.damage
                self._add_log(
                    "Attack",
                    (
                        f"{unit.team.title()} {unit.name} attacked {target.team.title()} {target.name}, "
                        f"damage={event.damage}, hp={target.hp}"
                    ),
                )
                if event.target_destroyed and target.id not in self._kill_credit_record:
                    self.kill_count[unit.team] += 1
                    self._kill_credit_record.add(target.id)
                events.append(event)
        self.attack_events.extend(events)

    def _attack_target_for(self, unit: Unit) -> Unit | None:
        """根据单位状态确定攻击目标。"""
        if unit.status == STATUS_EVADE:
            nearest = self.strategy.nearest_enemy(unit, self.enemy_units(unit.team))
            if nearest and unit.attack_range > 0 and unit.distance_to(nearest) <= unit.attack_range * 0.55:
                return nearest
            return None
        return self.focus_targets.get(unit.team)

    def _update_destroyed_stats(self) -> None:
        """统计新摧毁单位数量。"""
        for unit in self.units:
            if unit.is_destroyed and unit.id not in self._destroyed_record:
                unit.status = STATUS_DESTROYED
                unit.target_id = None
                self._destroyed_record.add(unit.id)
                self.destroyed_count[unit.team] += 1
                self._add_log("Destroyed", f"{unit.team.title()} {unit.name} was destroyed")

    def _attack_base_phase(self) -> None:
        """各单位优先攻击射程内的敌方基地。"""
        red_base = self.battlefield.base_obj(TEAM_RED)
        blue_base = self.battlefield.base_obj(TEAM_BLUE)
        for unit in self.active_units():
            if unit.ammo <= 0 or unit.attack_power <= 0:
                continue
            target_base = blue_base if unit.team == TEAM_RED else red_base
            if target_base.is_destroyed:
                continue
            dist = ((unit.x - target_base.x) ** 2 + (unit.y - target_base.y) ** 2) ** 0.5
            if dist > unit.attack_range:
                continue
            # 检查攻击域
            if not unit.can_attack_ground:
                continue
            unit.ammo -= 1
            dmg = target_base.take_damage(unit.attack_power)
            self.attack_count[unit.team] += 1
            self.total_damage[unit.team] += dmg
            self.attack_events.append(AttackEvent(
                attacker_id=unit.id, target_id=f"{target_base.team}_base",
                start=(unit.x, unit.y), end=(target_base.x, target_base.y),
                damage=dmg, target_hp=target_base.hp,
                target_destroyed=target_base.is_destroyed,
            ))
            self._add_log("Attack",
                f"{unit.team.title()} {unit.name} attacked {target_base.team.title()} base, damage={dmg}")
            if target_base.is_destroyed:
                self._add_log("Destroyed", f"{target_base.team.title()} base was destroyed")

    def _replenish_phase(self) -> None:
        """基地给周围友军补给弹药和血量。"""
        for team in (TEAM_RED, TEAM_BLUE):
            base = self.battlefield.base_obj(team)
            if base.is_destroyed:
                continue
            for unit in self.active_units(team):
                dist = ((unit.x - base.x) ** 2 + (unit.y - base.y) ** 2) ** 0.5
                if dist <= BASE_REPAIR_RADIUS:
                    healed = unit.hp < unit.max_hp
                    rearmed = unit.ammo < 10
                    unit.hp = min(unit.max_hp, unit.hp + BASE_REPAIR_PER_STEP)
                    unit.ammo = min(unit.ammo + 1, 10)
                    if healed or rearmed:
                        if unit.hp % 32 < BASE_REPAIR_PER_STEP:
                            pass  # 补给中（静默）

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
            self._add_log("Result", result_text)
            self._result_logged = True

    def _cleanup_target_pools(self) -> None:
        """清理共享目标池中的无效目标。"""
        for team, targets in self.shared_targets.items():
            for _, target, reason in targets.cleanup(self.time_step, DETECTION_TIMEOUT_STEPS):
                self._add_log(
                    "TargetPool",
                    f"{team.title()} target pool removed {target.team.title()} {target.name} ({reason})",
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
        """为 UI 面板提供统计快照（含第八阶段态势/行为字段）。"""
        red_sit = situation_label(self.red_strength, self.blue_strength, TEAM_RED)
        blue_sit = situation_label(self.red_strength, self.blue_strength, TEAM_BLUE)
        # 获取一个代表性单位的行为
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
