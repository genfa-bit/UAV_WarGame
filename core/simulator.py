"""仿真主控模块。"""

from __future__ import annotations

from config import DETECTION_TIMEOUT_STEPS, STATUS_DESTROYED, STATUS_EVADE, TEAM_BLUE, TEAM_RED
from core.battlefield import Battlefield
from core.combat import AttackEvent, CombatSystem
from core.strategy import StrategyEngine
from core.target_pool import TargetPool
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
        self.destroyed_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.kill_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.attack_count = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.total_damage = {TEAM_RED: 0, TEAM_BLUE: 0}
        self.winner: str | None = None
        self.attack_events: list[AttackEvent] = []
        self.combat_logs: list[str] = []

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
        self._cleanup_target_pools()
        self._reconnaissance_phase()
        self._select_focus_targets()
        self._movement_phase()
        self._attack_phase()
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
        """侦察阶段：发现目标并写入本方共享目标池。"""
        for unit in self.active_units():
            enemies = self.enemy_units(unit.team)
            for spotted in self.strategy.scan_enemies(unit, enemies):
                targets = self.shared_targets[unit.team]
                is_new = targets.sight(spotted, self.time_step)
                if is_new:
                    self._add_log(
                        "Scout",
                        f"{unit.team.title()} {unit.name} detected {spotted.team.title()} {spotted.name}",
                    )
                    self._add_log(
                        "TargetPool",
                        f"{unit.team.title()} target pool added {spotted.team.title()} {spotted.name}",
                    )

    def _select_focus_targets(self) -> None:
        """为红蓝双方分别选择当前集火目标。"""
        for team in (TEAM_RED, TEAM_BLUE):
            old_target = self.focus_targets.get(team)
            new_target = self.strategy.choose_focus_target(
                self.shared_targets[team].values(),
                self.active_units(team),
            )
            self.focus_targets[team] = new_target
            old_id = old_target.id if old_target and not old_target.is_destroyed else None
            new_id = new_target.id if new_target and not new_target.is_destroyed else None
            if old_id != new_id:
                target_name = new_target.name if new_target else "None"
                self._add_log("Focus", f"{team.title()} focus target changed to {target_name}")

    def _movement_phase(self) -> None:
        """移动阶段：集火推进、战术规避或巡逻。"""
        for unit in self.active_units():
            target = self.focus_targets.get(unit.team)
            was_evading = unit.id in self._evading_units
            is_evading = self.strategy.move_unit(
                unit=unit,
                battlefield=self.battlefield,
                target=target,
                visible_enemies=self.shared_targets[unit.team].values(),
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

    def _judge_winner(self) -> None:
        """判断胜负：某方全部单位被摧毁时另一方获胜。"""
        red_alive = self.remaining_count(TEAM_RED)
        blue_alive = self.remaining_count(TEAM_BLUE)
        if red_alive == 0 and blue_alive == 0:
            self.winner = "draw"
        elif red_alive == 0:
            self.winner = TEAM_BLUE
        elif blue_alive == 0:
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
        """为 UI 面板提供当前统计快照。"""
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
            "red_evading": len([unit for unit in self.active_units(TEAM_RED) if unit.status == STATUS_EVADE]),
            "blue_evading": len([unit for unit in self.active_units(TEAM_BLUE) if unit.status == STATUS_EVADE]),
            "evading_units": ", ".join(unit.name for unit in self.active_units() if unit.status == STATUS_EVADE),
            "winner": self.winner,
        }
