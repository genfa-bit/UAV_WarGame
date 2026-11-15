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
from math import atan2, cos, hypot, sin
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
from core.entity import stable_unit_angle
from core.pathfinding import move_to
from core.units import Unit, UnitDomain

_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, -1),
               (-1, 0), (-1, 1), (0, 1), (1, 1)]

# 接近目标时停在射程的 85% 处：既进入攻击范围，又不会走到目标坐标上。
APPROACH_STANDOFF_RATIO = 0.85
# 无分配目标时向敌方基地推进，停在射程 90% 的外围。
BASE_PUSH_STANDOFF_RATIO = 0.90
# 基地补给站位半径（小于 BASE_REPAIR_RADIUS=80，仍可被补给）。
RESUPPLY_SLOT_RADIUS = 36.0
_MIN_STANDOFF = 24.0


def _ring_point(unit: Unit, center_x: float, center_y: float,
                radius: float) -> tuple[float, float]:
    """目标外围的环绕站位点：留在单位当前所在的方位上。

    站位角取“目标指向单位”的当前方位，而不是单位 ID 的固定角。这样在
    点对称的战场上双方走位完全镜像，不会因为单位编号不同而让某一方
    总是占到位（这正是此前蓝方胜率偏高的根因）。只有单位与目标完全
    重合、方位无法定义时，才用 ID 稳定角兜底并把两者分开。
    """
    dx, dy = unit.x - center_x, unit.y - center_y
    if dx * dx + dy * dy < 1e-12:
        angle = stable_unit_angle(unit.id)
    else:
        angle = atan2(dy, dx)
    return center_x + cos(angle) * radius, center_y + sin(angle) * radius


def _approach_point(unit: Unit, target_x: float, target_y: float,
                    standoff: float) -> tuple[float, float] | None:
    """返回目标外围的接近点；已在站位圈内时返回 None（保持站位）。

    远距离沿当前方位直进，进入 2.5 倍站位半径内改走本单位方位的环绕
    站位点，从而把多个单位分散在目标周围的射程外沿，而不是叠在目标
    坐标上。同一方位上的多个单位由移动后的分离阶段兜底推开。
    """
    dx, dy = unit.x - target_x, unit.y - target_y
    distance = hypot(dx, dy)
    if distance <= standoff:
        return None
    if distance < 1e-6:
        angle = stable_unit_angle(unit.id)
    elif distance > standoff * 2.5:
        angle = atan2(dy, dx)
    else:
        return _ring_point(unit, target_x, target_y, standoff)
    return target_x + cos(angle) * standoff, target_y + sin(angle) * standoff


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
    #  第十阶段：按兵种差异化 HP 阈值和规避概率
    # ═══════════════════════════════════════════════════════════

    # 仅作战兵种可规避；指挥节点 / 基地 speed=0 在 should_evade 入口直接返回 False
    _EVADE_HP_THRESHOLD = {
        "ground_vehicle": 0.20,   # 重型坦克，只在极低血量时规避
        "missile_vehicle": 0.40,  # 远程单位，保持距离优先
        "scout_drone": 0.35,      # 脆弱侦察，适度规避
        "strike_drone": 0.30,     # 攻击无人机
    }
    _EVADE_CHANCE = {
        "ground_vehicle": 0.50,   # 坦克不轻易撤退
        "missile_vehicle": 0.85,  # 远程保持距离
        "scout_drone": 0.70,
        "strike_drone": 0.80,
    }

    def should_evade(self, unit: Unit, nearest_enemy: Unit | None) -> bool:
        if unit.is_destroyed or unit.speed <= 0:
            return False
        # 冷却期内禁止规避
        if self.behavior_mgr.on_evade_cooldown(unit.id):
            return False

        hp_threshold = self._EVADE_HP_THRESHOLD.get(unit.unit_type, 0.30)
        evade_chance = self._EVADE_CHANCE.get(unit.unit_type, 1.0)

        danger_dist = max(50.0, nearest_enemy.attack_range * 0.5) if nearest_enemy else 50.0
        enemy_dist = unit.distance_to(nearest_enemy) if nearest_enemy else None

        if unit.status == STATUS_EVADE:
            enemy_clear = enemy_dist is None or enemy_dist > danger_dist * 1.2
            return not (unit.hp_ratio >= hp_threshold + 0.05 and enemy_clear)

        hp_low = unit.hp_ratio < hp_threshold
        ammo_empty = unit.ammo == 0 and enemy_dist is not None and enemy_dist < danger_dist * 1.5
        enemy_close = enemy_dist is not None and enemy_dist < danger_dist
        high_threat = (
            nearest_enemy is not None and enemy_dist is not None
            and nearest_enemy.threat_value >= unit.threat_value + 3
            and enemy_dist <= max(nearest_enemy.attack_range, danger_dist)
        )
        should = hp_low or ammo_empty or enemy_close or high_threat

        # 弹药耗尽/低血量/高威胁必规避；仅 enemy_close 按兵种概率判定
        if should and enemy_close and not hp_low and not ammo_empty and not high_threat:
            if unit.unit_type in self._EVADE_CHANCE:
                if random.random() > evade_chance:
                    return False

        return should

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
        *,
        target_mode: str | None = None,
        emergency_target: Unit | None = None,
    ) -> bool:
        """执行移动决策。

        target_mode:
        - None：旧行为，保持 focus/最近敌人回退；
        - "assigned"：只围绕协同分配目标行动，不切换到其他敌人；
        - "unassigned"：RDMA 下未分配单位，禁止普通攻击候选，仅允许
          emergency_target 触发的基地防御/自卫移动。
        """
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

        # 基地防御（敌方在250px内→全员防御，无论血量弹药）。
        # 协同分配单位不参与通用基地防御，避免把火力从分配目标引开。
        base_x, base_y = battlefield.base_for_team(unit.team)
        enemies_near_base = [e for e in enemies
                             if ((e.x - base_x) ** 2 + (e.y - base_y) ** 2) ** 0.5 < 250]
        defender = emergency_target if emergency_target is not None else (
            enemies_near_base[0] if enemies_near_base and unit.can_attack(enemies_near_base[0])
            else (min(enemies_near_base, key=lambda e: unit.distance_to(e))
                  if enemies_near_base else None))
        assigned_defender_ok = (target_mode == "assigned" and target is not None
                                and defender is not None
                                and defender.id == target.id)
        if ((target_mode != "assigned" or assigned_defender_ok)
                and enemies_near_base and defender is not None
                and (emergency_target is not None or unit.can_attack(defender)
                     or unit.ammo > 0)):
            candidates.append((Behavior.ATTACK,
                               lambda: self._move_with_role(unit, defender, battlefield,
                                                            visible, enemies)))

        # 增援：队友正在交火，我状态OK → 去帮忙。
        # RDMA 已分配单位只服从分配目标，避免被路过的敌人拉走。
        reinforce_target = self._check_reinforce(unit, visible, enemies, battlefield)
        if (reinforce_target is not None and not enemies_near_base
                and target_mode is None):
            rt = reinforce_target
            candidates.append((Behavior.ATTACK,
                               lambda: self._do_advance_to_enemy(unit, rt, battlefield)))

        # 弹药/血量不足 → 回基地补给
        need_resupply = (unit.ammo == 0 or unit.hp_ratio < 0.4)
        if need_resupply:
            candidates.append((Behavior.SCOUT,
                               lambda: self._do_resupply(unit, battlefield)))

        # 补给充足 → 按分配目标或前线推进。
        # 所有“向目标移动”都用外围站位点，绝不把目标的精确坐标当目的地：
        # 否则多个单位会走到同一个像素上，随后距离为 0、永久重叠不动。
        if not need_resupply:
            if target_mode == "assigned" and target is not None:
                candidates.append((Behavior.SCOUT,
                                   lambda: self._do_approach_target(
                                       unit, target, battlefield)))
            elif target_mode == "unassigned":
                # 未分配单位不追逐可见敌人，只撤向外围待机/补给。
                candidates.append((Behavior.PATROL,
                                   lambda: self._do_push_enemy_base(unit, battlefield)))
            elif enemies:
                nearest = min(enemies, key=unit.distance_to)
                candidates.append((Behavior.SCOUT,
                                   lambda: self._do_advance_to_enemy(
                                       unit, nearest, battlefield)))
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
                    # 无可见威胁时撤向己方基地外围站位点，不挤在基地坐标上。
                    bx, by = bf.base_for_team(u.team)
                    point = _approach_point(u, bx, by, RESUPPLY_SLOT_RADIUS)
                    if point is not None:
                        move_to(u, point[0], point[1], bf)
            candidates.append((Behavior.EVADE,
                               lambda: ev(unit, nearest_vis, battlefield)))

        # Attack（集火目标 或 面前最近的可攻击敌人）
        # 第十阶段：只有交战状态机允许攻击时才能加入 ATTACK 候选。
        # RDMA 下 assigned 只认分配目标，unassigned 不生成普通攻击候选。
        attack_target = None
        if target_mode == "unassigned":
            attack_target = None
        elif target_mode == "assigned":
            if target and not target.is_destroyed and unit.can_attack(target):
                attack_target = target
        elif target and not target.is_destroyed and unit.can_attack(target):
            attack_target = target
        else:
            for e in sorted(visible, key=unit.distance_to):
                if unit.can_attack(e):
                    attack_target = e
                    break
        if attack_target:
            at = attack_target  # capture for lambda
            if unit.engagement_state.can_attack:
                candidates.append((Behavior.ATTACK,
                                   lambda: self._move_with_role(unit, at, battlefield,
                                                                visible, enemies)))
            else:
                # 反应中/冷却中 → 已在射程内保持站位，否则接近到射程外沿。
                # 不能把目标坐标当目的地，否则会走到目标身上并互相锁死。
                candidates.append((Behavior.SCOUT,
                                   lambda: self._do_hold_or_approach(
                                       unit, at, battlefield)))

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
        """弹药/血量不足 → 自动绕障返回己方基地。

        停在基地外围的固定环绕点上（每个单位角度不同），而不是基地坐标本身，
        否则同阵营单位会在补给时全部叠进同一个像素。
        """
        unit.status = STATUS_MOVE
        bx, by = battlefield.base_for_team(unit.team)
        point = _approach_point(unit, bx, by, RESUPPLY_SLOT_RADIUS)
        if point is not None:
            move_to(unit, point[0], point[1], battlefield)

    def _do_push_enemy_base(self, unit: Unit, battlefield: Battlefield) -> None:
        """无可见敌人 → 自动绕障向敌方基地推进，停在射程外围。

        停在射程的 90% 处：既在攻击范围内，又不会挤进基地坐标；
        多支部队按各自固定角度分散在基地周围的环上。
        """
        unit.status = STATUS_MOVE
        enemy_team = "blue" if unit.team == "red" else "red"
        bx, by = battlefield.base_for_team(enemy_team)
        standoff = self._standoff_for(unit, BASE_PUSH_STANDOFF_RATIO)
        point = _approach_point(unit, bx, by, standoff)
        if point is not None:
            move_to(unit, point[0], point[1], battlefield)

    def _do_approach_target(self, unit: Unit, target: Unit,
                            battlefield: Battlefield) -> None:
        """接近分配目标，停在射程的 85% 处。

        目标坐标只用于计算外围站位点，绝不作为目的地：多个单位若都以目标
        坐标为终点会走到同一像素，距离归零后双方都不再移动。
        """
        standoff = self._standoff_for(unit, APPROACH_STANDOFF_RATIO)
        point = _approach_point(unit, target.x, target.y, standoff)
        if point is None:
            unit.status = STATUS_ATTACK
            return
        unit.status = STATUS_MOVE
        move_to(unit, point[0], point[1], battlefield)

    def _do_advance_to_enemy(self, unit: Unit, enemy: Unit,
                             battlefield: Battlefield) -> None:
        """向普通敌人推进，同样停在射程外围的固定站位点。"""
        self._do_approach_target(unit, enemy, battlefield)

    def _do_hold_or_approach(self, unit: Unit, target: Unit,
                             battlefield: Battlefield) -> None:
        """已在射程内则原地保持，否则接近到射程外沿（不等同于贴近目标）。"""
        if unit.distance_to(target) <= unit.attack_range:
            unit.status = STATUS_ATTACK
            return
        self._do_approach_target(unit, target, battlefield)

    @staticmethod
    def _standoff_for(unit: Unit, ratio: float) -> float:
        """按单位射程计算站位距离，避免近距离兵种把站位点压到目标身上。"""
        return max(_MIN_STANDOFF, unit.attack_range * ratio)

    def _step_toward_standoff(self, unit: Unit, target: Unit,
                              battlefield: Battlefield) -> None:
        """兵种行为共用的接近步：只走到目标外围站位点。"""
        standoff = self._standoff_for(unit, APPROACH_STANDOFF_RATIO)
        point = _approach_point(unit, target.x, target.y, standoff)
        if point is not None:
            move_to(unit, point[0], point[1], battlefield)

    def _check_reinforce(self, unit: Unit, visible: list[Unit],
                         enemies: list[Unit],
                         battlefield: Battlefield) -> Unit | None:
        """检查是否需要增援队友：我有战力且队友在附近交火。"""
        if unit.hp_ratio < 0.5 or unit.ammo < 3:
            return None
        for enemy in enemies:
            # 有敌人在交火范围内
            dist_me = unit.distance_to(enemy)
            if dist_me < 350 and dist_me > 80:
                # 去增援
                return enemy
        return None

    def _do_scout(self, unit: Unit, nearest_vis: Unit) -> None:
        unit.status = STATUS_SCOUT

    # ═══════════════════════════════════════════════════════════
    #  智能远离（导弹车优先横向避障）
    # ═══════════════════════════════════════════════════════════

    def _move_away_smart(self, unit: Unit, enemy: Unit, battlefield: Battlefield) -> None:
        """远离敌人；地面单位使用 Bug2 绕障，空中单位直飞。"""
        if unit.unit_type in ("missile_vehicle", "ground_vehicle"):
            from core.pathfinding import move_to
            dx, dy = unit.x - enemy.x, unit.y - enemy.y
            dist = hypot(dx, dy) or 1.0
            bx, by = dx / dist, dy / dist
            # 计算远离敌人的撤退目标点，确保有足够距离绕障
            retreat_dist = 100.0
            retreat_x = unit.x + bx * retreat_dist
            retreat_y = unit.y + by * retreat_dist
            retreat_x, retreat_y = battlefield.clamp_position(retreat_x, retreat_y)
            # 使用 Bug2 绕障算法，避免贴墙振荡
            move_to(unit, retreat_x, retreat_y, battlefield)
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
                self._step_toward_standoff(unit, target, battlefield)

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
            self._step_toward_standoff(unit, target, battlefield)

    def _ground_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield) -> None:
        dist = unit.distance_to(target)
        if dist <= unit.attack_range * 0.8 and unit.can_attack(target):
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            self._step_toward_standoff(unit, target, battlefield)

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
            self._step_toward_standoff(unit, target, battlefield)

    def _default_behavior(self, unit: Unit, target: Unit, battlefield: Battlefield) -> None:
        dist = unit.distance_to(target)
        if dist <= unit.attack_range:
            unit.status = STATUS_ATTACK
        else:
            unit.status = STATUS_MOVE
            self._step_toward_standoff(unit, target, battlefield)

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
            if battlefield.can_move_to(tx, ty, unit):
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

        speed = unit.effective_speed(battlefield)
        nx = unit.x + vector[0] * speed
        ny = unit.y + vector[1] * speed
        nx, ny = battlefield.clamp_position(nx, ny)
        if battlefield.can_move_to(nx, ny, unit):
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
            tx = unit.x + dx * speed * 2
            ty = unit.y + dy * speed * 2
            tx, ty = battlefield.clamp_position(tx, ty)
            if battlefield.can_move_to(tx, ty, unit):
                self._patrol_vectors[unit.id] = (dx, dy)
                return (dx, dy)

        # 全部失败 → 彻底重置方向
        fwd = 1 if unit.team == "red" else -1
        new_vec = (random.uniform(-1, 1), random.uniform(-1, 1))
        if hypot(*new_vec) == 0:
            new_vec = (fwd, 0)
        self._patrol_vectors[unit.id] = new_vec
        return new_vec
