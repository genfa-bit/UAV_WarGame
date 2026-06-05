"""AI策略模块（第八阶段：行为管理器 + 角色智能 + 卡死检测 + 目标锁定）。

第八阶段优化：
- Evade退出不再要求弹药>0，弹药耗尽后返回巡逻/侦察
- 规避最长25帧后强制退出
- 卡死恢复：采样敌方方向有效位置而非完全随机
- 巡逻方向：8方向优先队列替代纯随机
- 导弹车后退时优先横向避障
- 在基地附近连续卡死自动重新向敌方推进
"""

from __future__ import annotations

import random
from math import hypot
from typing import Iterable

from config import (
    STATUS_ATTACK,
    STATUS_EVADE,
    STATUS_MOVE,
    STATUS_SCOUT,
    STUCK_MOVE_DELTA,
    STUCK_THRESHOLD,
    TARGET_LOCK_TIME,
)
from core.battlefield import Battlefield
from core.behavior import Behavior, BehaviorManager
from core.pathfinding import move_to
from core.units import Unit, UnitDomain

_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, -1),
               (-1, 0), (-1, 1), (0, 1), (1, 1)]


class StrategyEngine:
    """侦察、集火、移动、规避 + 行为管理器 + 角色智能 + 卡死检测。"""

    def __init__(self) -> None:
        self._patrol_vectors: dict[str, tuple[float, float]] = {}
        self.behavior_mgr = BehaviorManager()

    # ═══════════════════════════════════════════════════════════
    #  侦察
    # ═══════════════════════════════════════════════════════════

    def scan_enemies(self, unit: Unit, enemies: Iterable[Unit]) -> list[Unit]:
        if unit.is_destroyed:
            return []
        spotted = [e for e in enemies
                   if not e.is_destroyed and unit.distance_to(e) <= unit.detect_range]
        if spotted and unit.status != STATUS_EVADE:
            unit.status = STATUS_SCOUT
        return spotted

    # ═══════════════════════════════════════════════════════════
    #  集火目标（高威胁优先 + 目标锁定）
    # ═══════════════════════════════════════════════════════════

    def choose_focus_target(self, shared_targets: Iterable[Unit],
                            friendly_units: Iterable[Unit],
                            locked_target_id: str | None = None) -> Unit | None:
        from core.threat import threat_score
        candidates = [t for t in shared_targets if not t.is_destroyed]
        if not candidates:
            return None
        if locked_target_id:
            locked = next((t for t in candidates if t.id == locked_target_id), None)
            if locked:
                return locked
        friendlies = [u for u in friendly_units if not u.is_destroyed]
        ref = friendlies[0] if friendlies else None
        return max(candidates, key=lambda t: threat_score(t, ref))

    def nearest_enemy(self, unit: Unit, enemies: Iterable[Unit]) -> Unit | None:
        candidates = [e for e in enemies if not e.is_destroyed]
        return min(candidates, key=unit.distance_to) if candidates else None

    # ═══════════════════════════════════════════════════════════
    #  规避判断（退出不再要求弹药>0，由 evade_exceeded 兜底）
    # ═══════════════════════════════════════════════════════════

    def should_evade(self, unit: Unit, nearest_enemy: Unit | None) -> bool:
        if unit.is_destroyed or unit.speed <= 0:
            return False
        # 冷却期内禁止规避
        if self.behavior_mgr.on_evade_cooldown(unit.id):
            return False

        danger_dist = max(50.0, nearest_enemy.attack_range * 0.5) if nearest_enemy else 50.0
        enemy_dist = unit.distance_to(nearest_enemy) if nearest_enemy else None

        if unit.status == STATUS_EVADE:
            enemy_clear = enemy_dist is None or enemy_dist > danger_dist * 1.2
            return not (unit.hp_ratio >= 0.35 and enemy_clear)

        hp_low = unit.hp_ratio < 0.3
        ammo_empty = unit.ammo == 0 and enemy_dist is not None and enemy_dist < danger_dist * 1.5
        enemy_close = enemy_dist is not None and enemy_dist < danger_dist
        high_threat = (
            nearest_enemy is not None and enemy_dist is not None
            and nearest_enemy.threat_value >= unit.threat_value + 3
            and enemy_dist <= max(nearest_enemy.attack_range, danger_dist)
        )
        return hp_low or ammo_empty or enemy_close or high_threat

    # ═══════════════════════════════════════════════════════════
    #  主移动决策
    # ═══════════════════════════════════════════════════════════

    def move_unit(
        self,
        unit: Unit,
        battlefield: Battlefield,
        target: Unit | None,
        visible_enemies: Iterable[Unit],
        all_enemies: Iterable[Unit],
    ) -> bool:
        if unit.is_destroyed:
            return False

        visible = [e for e in visible_enemies if not e.is_destroyed]
        enemies = [e for e in all_enemies if not e.is_destroyed]
        nearest_vis = self.nearest_enemy(unit, visible)
        nearest_any = self.nearest_enemy(unit, enemies)

        need_evade = self.should_evade(unit, nearest_any)
        force_exit = self.behavior_mgr.evade_exceeded(unit.id)

        # 规避超时退出后进入冷却期，防止立即重新规避
        if force_exit:
            self.behavior_mgr.start_evade_cooldown(unit.id)

        candidates: list[tuple[Behavior, callable]] = []

        # 基地防御（敌方在250px内→全员防御，无论血量弹药）
        base_x, base_y = battlefield.base_for_team(unit.team)
        enemies_near_base = [e for e in enemies
                             if ((e.x - base_x) ** 2 + (e.y - base_y) ** 2) ** 0.5 < 250]
        if enemies_near_base and (unit.can_attack(enemies_near_base[0]) or unit.ammo > 0):
            defender = enemies_near_base[0] if unit.can_attack(enemies_near_base[0]) else \
                       min(enemies_near_base, key=lambda e: unit.distance_to(e))
            candidates.append((Behavior.ATTACK,
                               lambda: self._move_with_role(unit, defender, battlefield,
                                                            visible, enemies)))

        # 增援：队友正在交火，我状态OK → 去帮忙
        reinforce_pt = self._check_reinforce(unit, visible, enemies, battlefield)
        if reinforce_pt and not enemies_near_base:
            rx, ry = reinforce_pt
            candidates.append((Behavior.ATTACK,
                               lambda: self._do_move_to_point(unit, rx, ry, battlefield)))

        # 弹药/血量不足 → 回基地补给
        need_resupply = (unit.ammo == 0 or unit.hp_ratio < 0.4)
        if need_resupply:
            candidates.append((Behavior.SCOUT,
                               lambda: self._do_resupply(unit, battlefield)))

        # 补给充足 → 向敌方/前线推进
        if not need_resupply:
            if enemies:
                # 向已知最近敌人推进
                nearest = min(enemies, key=unit.distance_to)
                candidates.append((Behavior.SCOUT,
                                   lambda: self._do_move_to_point(
                                       unit, nearest.x, nearest.y, battlefield)))
            elif not visible:
                candidates.append((Behavior.PATROL,
                                   lambda: self._do_push_enemy_base(unit, battlefield)))
            else:
                candidates.append((Behavior.PATROL,
                                   lambda: self._do_patrol(unit, battlefield)))
        else:
            candidates.append((Behavior.PATROL,
                               lambda: self._do_patrol(unit, battlefield)))

        # Scout
        if not need_resupply or enemies_near_base:
            if nearest_vis and unit.status != STATUS_EVADE:
                candidates.append((Behavior.SCOUT,
                                   lambda: self._do_scout(unit, nearest_vis)))
            elif target and not target.is_destroyed:
                candidates.append((Behavior.SCOUT,
                                   lambda: setattr(unit, 'status', STATUS_SCOUT)))

        # Evade
        if need_evade:
            def ev(u, nv, bf):
                u.status = STATUS_EVADE
                if nv:
                    self._move_away_smart(u, nv, bf)
                else:
                    bx, by = bf.base_for_team(u.team)
                    move_to(u, bx, by, bf)
            candidates.append((Behavior.EVADE,
                               lambda: ev(unit, nearest_vis, battlefield)))

        # Attack（集火目标 或 面前最近的可攻击敌人）
        attack_target = None
        if target and not target.is_destroyed and unit.can_attack(target):
            attack_target = target
        else:
            for e in sorted(visible, key=unit.distance_to):
                if unit.can_attack(e):
                    attack_target = e
                    break
        if attack_target:
            at = attack_target  # capture for lambda
            candidates.append((Behavior.ATTACK,
                               lambda: self._move_with_role(unit, at, battlefield,
                                                            visible, enemies)))

        executed = self.behavior_mgr.resolve(unit.id, candidates, force_exit)

        # 卡死检测 + 恢复
        if self.behavior_mgr.update_stuck(unit.id, unit.x, unit.y,
                                          STUCK_THRESHOLD, STUCK_MOVE_DELTA):
            self._handle_stuck(unit, battlefield, enemies)

        return executed == Behavior.EVADE

    # ═══════════════════════════════════════════════════════════
    #  基础行为
    # ═══════════════════════════════════════════════════════════

    def _do_patrol(self, unit: Unit, battlefield: Battlefield) -> None:
        unit.target_id = None
        unit.status = STATUS_MOVE
        unit.patrol(battlefield, self._get_patrol_vector(unit, battlefield))

    def _do_resupply(self, unit: Unit, battlefield: Battlefield) -> None:
        """弹药/血量不足 → 自动绕障返回己方基地。"""
        unit.status = STATUS_MOVE
        bx, by = battlefield.base_for_team(unit.team)
        move_to(unit, bx, by, battlefield)

    def _do_push_enemy_base(self, unit: Unit, battlefield: Battlefield) -> None:
        """无可见敌人 → 自动绕障向敌方基地推进。"""
        unit.status = STATUS_MOVE
        enemy_team = "blue" if unit.team == "red" else "red"
        bx, by = battlefield.base_for_team(enemy_team)
        move_to(unit, bx, by, battlefield)

    def _do_move_to_point(self, unit: Unit, tx: float, ty: float,
                          battlefield: Battlefield) -> None:
        """向指定坐标移动。"""
        unit.status = STATUS_MOVE
        move_to(unit, tx, ty, battlefield)

    def _check_reinforce(self, unit: Unit, visible: list[Unit],
                         enemies: list[Unit],
                         battlefield: Battlefield) -> tuple[float, float] | None:
        """检查是否需要增援队友：我有战力且队友在附近交火。"""
        if unit.hp_ratio < 0.5 or unit.ammo < 3:
            return None
        for enemy in enemies:
            # 有敌人在交火范围内
            dist_me = unit.distance_to(enemy)
            if dist_me < 350 and dist_me > 80:
                # 去增援
                return (enemy.x, enemy.y)
        return None

    def _do_scout(self, unit: Unit, nearest_vis: Unit) -> None:
        unit.status = STATUS_SCOUT

    # ═══════════════════════════════════════════════════════════
    #  智能远离（导弹车优先横向避障）
    # ═══════════════════════════════════════════════════════════

    def _move_away_smart(self, unit: Unit, enemy: Unit, battlefield: Battlefield) -> None:
        """远离敌人；地面单位优先横向移动，全堵死则不移动（避免贴墙振荡）。"""
        if unit.unit_type in ("missile_vehicle", "ground_vehicle"):
            dx, dy = unit.x - enemy.x, unit.y - enemy.y
            dist = hypot(dx, dy) or 1.0
            bx, by = dx / dist, dy / dist
            lx, ly = -by, bx  # 横向
            candidates = [
                (unit.x + bx * unit.speed, unit.y + by * unit.speed),
                (unit.x + bx * unit.speed + lx * unit.speed * 0.7,
                 unit.y + by * unit.speed + ly * unit.speed * 0.7),
                (unit.x + bx * unit.speed - lx * unit.speed * 0.7,
                 unit.y + by * unit.speed - ly * unit.speed * 0.7),
            ]
            for cx, cy in candidates:
                cx, cy = battlefield.clamp_position(cx, cy)
                if battlefield.can_move_to(cx, cy, unit.domain):
                    unit.move_towards(cx, cy, battlefield)
                    return
            # 全部堵死，不移动（避免 move_away_from 导致贴墙振荡）
            return
        unit.move_away_from(enemy, battlefield)

    # ═══════════════════════════════════════════════════════════
    #  兵种角色行为
    # ═══════════════════════════════════════════════════════════

    def _move_with_role(self, unit: Unit, target: Unit, battlefield: Battlefield,
                        visible: list[Unit], enemies: list[Unit]) -> None:
        ut = unit.unit_type
        if ut == "scout_drone":
            self._scout_behavior(unit, target, battlefield, visible)
        elif ut == "strike_drone":
            self._strike_behavior(unit, target, battlefield, visible)
        elif ut == "ground_vehicle":
            self._ground_behavior(unit, target, battlefield)
        elif ut == "missile_vehicle":
            self._missile_behavior(unit, target, battlefield)
        else:
            self._default_behavior(unit, target, battlefield)

    def _scout_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield,
                        visible: list[Unit]) -> None:
        from core.threat import threat_score
        dist = unit.distance_to(target)
        if visible:
            worst = max(visible, key=lambda e: threat_score(e, unit))
            if unit.distance_to(worst) < worst.attack_range * 0.7:
                unit.status = STATUS_EVADE
                self._move_away_smart(unit, worst, battlefield)
                return
        if dist <= unit.attack_range:
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_SCOUT
            if dist > unit.detect_range * 0.7:
                move_to(unit, target.x, target.y, battlefield)

    def _strike_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield,
                         visible: list[Unit]) -> None:
        from core.threat import threat_score
        dist = unit.distance_to(target)
        if visible:
            worst = max(visible, key=lambda e: threat_score(e, unit))
            if threat_score(worst, unit) > 80 and unit.distance_to(worst) < worst.attack_range:
                unit.status = STATUS_EVADE
                self._move_away_smart(unit, worst, battlefield)
                return
        if dist <= unit.attack_range:
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            move_to(unit, target.x, target.y, battlefield)

    def _ground_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield) -> None:
        dist = unit.distance_to(target)
        if dist <= unit.attack_range * 0.8 and unit.can_attack(target):
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            move_to(unit, target.x, target.y, battlefield)

    def _missile_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield) -> None:
        dist = unit.distance_to(target)
        preferred_min = unit.attack_range * 0.5
        if dist < preferred_min:
            unit.status = STATUS_EVADE
            self._move_away_smart(unit, target, battlefield)
        elif dist <= unit.attack_range:
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            move_to(unit, target.x, target.y, battlefield)

    def _default_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield) -> None:
        dist = unit.distance_to(target)
        if dist <= unit.attack_range:
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            move_to(unit, target.x, target.y, battlefield)

    # ═══════════════════════════════════════════════════════════
    #  卡死处理（采样敌方方向的有效位置）
    # ═══════════════════════════════════════════════════════════

    def _handle_stuck(self, unit: Unit, battlefield: Battlefield,
                      enemies: list[Unit]) -> None:
        self.behavior_mgr.clear_stuck(unit.id)
        # 尝试在敌方方向采样有效位置
        if enemies:
            center_x = sum(e.x for e in enemies) / len(enemies)
            center_y = sum(e.y for e in enemies) / len(enemies)
        else:
            center_x = battlefield.width if unit.team == "red" else 0
            center_y = unit.y
        for _ in range(8):
            offset_x = random.uniform(30, 90) * (1 if unit.team == "red" else -1)
            offset_y = random.uniform(-50, 50)
            tx = unit.x + offset_x
            ty = unit.y + offset_y
            tx, ty = battlefield.clamp_position(tx, ty)
            if battlefield.can_move_to(tx, ty, unit.domain):
                move_to(unit, tx, ty, battlefield)
                return
        # 全失败则原地等待
        unit.status = STATUS_MOVE

    # ═══════════════════════════════════════════════════════════
    #  巡逻方向（8方向优先队列，先试前方再两侧最后后方）
    # ═══════════════════════════════════════════════════════════

    def _get_patrol_vector(self, unit: Unit, battlefield: Battlefield) -> tuple[float, float]:
        vector = self._patrol_vectors.get(unit.id)
        if vector is None:
            forward = 1 if unit.team == "red" else -1
            vector = (forward, random.uniform(-0.4, 0.4))
            self._patrol_vectors[unit.id] = vector

        nx = unit.x + vector[0] * unit.speed
        ny = unit.y + vector[1] * unit.speed
        nx, ny = battlefield.clamp_position(nx, ny)
        if battlefield.can_move_to(nx, ny, unit.domain):
            self._patrol_hits = getattr(self, '_patrol_hits', {})
            self._patrol_hits[unit.id] = 0
            return vector

        # 撞了，按优先级试8方向
        forward = 1 if unit.team == "red" else -1
        prioritized = [
            (forward, 0), (forward, -0.5), (forward, 0.5),
            (0, -1), (0, 1), (-forward * 0.3, -0.5), (-forward * 0.3, 0.5),
            (-forward, 0),
        ]
        for dx, dy in prioritized:
            tx = unit.x + dx * unit.speed * 2
            ty = unit.y + dy * unit.speed * 2
            tx, ty = battlefield.clamp_position(tx, ty)
            if battlefield.can_move_to(tx, ty, unit.domain):
                self._patrol_vectors[unit.id] = (dx, dy)
                return (dx, dy)

        # 全部失败 → 彻底重置方向
        fwd = 1 if unit.team == "red" else -1
        new_vec = (random.uniform(-1, 1), random.uniform(-1, 1))
        if hypot(*new_vec) == 0:
            new_vec = (fwd, 0)
        self._patrol_vectors[unit.id] = new_vec
        return new_vec
