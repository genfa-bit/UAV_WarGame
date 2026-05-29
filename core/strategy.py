"""简单 AI 策略模块。

本模块只实现课程仿真需要的抽象规则，不涉及真实军事参数。
"""

from __future__ import annotations

import random
from math import hypot
from typing import Iterable

from config import STATUS_ATTACK, STATUS_EVADE, STATUS_MOVE, STATUS_SCOUT
from core.battlefield import Battlefield
from core.units import Unit, UnitDomain


class StrategyEngine:
    """负责侦察、集火目标选择、移动和规避策略。"""

    def __init__(self) -> None:
        self._patrol_vectors: dict[str, tuple[float, float]] = {}

    def scan_enemies(self, unit: Unit, enemies: Iterable[Unit]) -> list[Unit]:
        """返回单位探测范围内的敌方单位。

        被摧毁单位不会被发现；发现目标时单位状态暂记为 Scout。
        """
        if unit.is_destroyed:
            return []
        spotted = [
            enemy
            for enemy in enemies
            if not enemy.is_destroyed and unit.distance_to(enemy) <= unit.detect_range
        ]
        if spotted and unit.status != STATUS_EVADE:
            unit.status = STATUS_SCOUT
        return spotted

    def choose_focus_target(self, shared_targets: Iterable[Unit], friendly_units: Iterable[Unit]) -> Unit | None:
        """为阵营选择集火目标。

        规则：优先未摧毁目标；生命值最低优先；生命相同则选择距离己方平均位置更近的目标。
        """
        candidates = [target for target in shared_targets if not target.is_destroyed]
        if not candidates:
            return None

        friendlies = [unit for unit in friendly_units if not unit.is_destroyed]
        if friendlies:
            avg_x = sum(unit.x for unit in friendlies) / len(friendlies)
            avg_y = sum(unit.y for unit in friendlies) / len(friendlies)
        else:
            avg_x, avg_y = 0.0, 0.0

        def priority(target: Unit) -> tuple[float, float, float]:
            distance_to_group = hypot(target.x - avg_x, target.y - avg_y)
            return target.hp, -target.threat_value, distance_to_group

        return min(candidates, key=priority)

    def choose_shared_target(self, unit: Unit, shared_targets: Iterable[Unit]) -> Unit | None:
        """兼容第一阶段接口：为单个单位从共享目标中选择目标。"""
        target = self.choose_focus_target(shared_targets, [unit])
        unit.target_id = target.id if target else None
        return target

    def nearest_enemy(self, unit: Unit, enemies: Iterable[Unit]) -> Unit | None:
        """查找最近的未摧毁敌方单位。"""
        candidates = [enemy for enemy in enemies if not enemy.is_destroyed]
        if not candidates:
            return None
        return min(candidates, key=unit.distance_to)

    def should_evade(self, unit: Unit, nearest_enemy: Unit | None) -> bool:
        """判断单位是否需要进入规避状态。

        固定指挥节点速度为 0，不执行规避移动；移动单位在低血量、弹药耗尽或敌人过近时规避。
        """
        if unit.is_destroyed or unit.speed <= 0:
            return False

        danger_distance = max(50.0, nearest_enemy.attack_range * 0.5) if nearest_enemy else 50.0
        enemy_distance = unit.distance_to(nearest_enemy) if nearest_enemy else None

        if unit.status == STATUS_EVADE:
            enemy_clear = enemy_distance is None or enemy_distance > danger_distance * 1.2
            return not (unit.hp_ratio >= 0.35 and unit.ammo > 0 and enemy_clear)

        enemy_too_close = enemy_distance is not None and enemy_distance < danger_distance
        high_fire_threat = (
            nearest_enemy is not None
            and enemy_distance is not None
            and nearest_enemy.threat_value >= unit.threat_value + 3
            and enemy_distance <= max(nearest_enemy.attack_range, danger_distance)
        )
        return unit.hp_ratio < 0.3 or unit.ammo == 0 or enemy_too_close or high_fire_threat

    def move_unit(
        self,
        unit: Unit,
        battlefield: Battlefield,
        target: Unit | None,
        visible_enemies: Iterable[Unit],
        all_enemies: Iterable[Unit],
    ) -> bool:
        """根据当前状态驱动单位移动。

        返回值表示本次移动后单位是否处于 Evade 状态，便于 Simulator 输出规避日志。
        """
        if unit.is_destroyed:
            return False

        visible = [enemy for enemy in visible_enemies if not enemy.is_destroyed]
        enemies = [enemy for enemy in all_enemies if not enemy.is_destroyed]
        nearest_visible = self.nearest_enemy(unit, visible)
        nearest_any = self.nearest_enemy(unit, enemies)

        if self.should_evade(unit, nearest_any):
            unit.status = STATUS_EVADE
            if nearest_visible:
                # 已知敌人时，沿远离最近可见敌人的方向撤离。
                unit.move_away_from(nearest_visible, battlefield)
            else:
                # 没有可见敌人时，向己方基地撤退，便于演示“战术回撤”。
                base_x, base_y = battlefield.base_for_team(unit.team)
                unit.move_towards(base_x, base_y, battlefield)
            return True

        if target and not target.is_destroyed:
            unit.target_id = target.id
            self._move_with_unit_role(unit, target, battlefield)
            return unit.status == STATUS_EVADE

        unit.target_id = None
        unit.status = STATUS_SCOUT if unit.unit_type == "scout_drone" else STATUS_MOVE
        unit.patrol(battlefield, self._get_patrol_vector(unit, battlefield))
        return False

    def _move_with_unit_role(self, unit: Unit, target: Unit, battlefield: Battlefield) -> None:
        """Apply role differences while preserving the shared focus-target rule."""

        distance = unit.distance_to(target)
        if unit.unit_type == "scout_drone":
            if distance <= unit.attack_range:
                unit.status = STATUS_ATTACK
            else:
                unit.status = STATUS_SCOUT
                if distance > unit.detect_range * 0.75:
                    unit.move_towards(target.x, target.y, battlefield)
            return

        if unit.unit_type == "missile_vehicle":
            preferred_min_distance = unit.attack_range * 0.55
            if distance < preferred_min_distance:
                unit.status = STATUS_EVADE
                unit.move_away_from(target, battlefield)
            elif distance <= unit.attack_range:
                unit.status = STATUS_ATTACK
            else:
                unit.status = STATUS_MOVE
                unit.move_towards(target.x, target.y, battlefield)
            return

        if unit.unit_type == "ground_vehicle" and target.domain == UnitDomain.AIR and distance > unit.attack_range:
            unit.status = STATUS_MOVE
            unit.move_towards(target.x, target.y, battlefield)
            return

        if distance <= unit.attack_range:
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            unit.move_towards(target.x, target.y, battlefield)

    def _get_patrol_vector(self, unit: Unit, battlefield: Battlefield) -> tuple[float, float]:
        """生成并缓存巡逻方向，碰到边界或障碍物时重新选择。"""
        vector = self._patrol_vectors.get(unit.id)
        if vector is None:
            forward = 1 if unit.team == "red" else -1
            vector = (forward, random.uniform(-0.6, 0.6))
            self._patrol_vectors[unit.id] = vector

        next_x = unit.x + vector[0] * unit.speed
        next_y = unit.y + vector[1] * unit.speed
        next_x, next_y = battlefield.clamp_position(next_x, next_y)
        if not battlefield.can_move_to(next_x, next_y, unit.domain):
            angle_vector = (random.uniform(-1, 1), random.uniform(-1, 1))
            if hypot(*angle_vector) == 0:
                angle_vector = (1, 0)
            self._patrol_vectors[unit.id] = angle_vector
        return self._patrol_vectors[unit.id]
