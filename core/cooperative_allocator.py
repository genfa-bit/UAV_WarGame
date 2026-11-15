"""协同动态边际拍卖（Role-aware Dynamic Marginal Auction, RDMA）。

本模块只做“单位 → 目标”的确定性分配，不移动、不开火。分配结果由
Simulator 用来约束移动和攻击授权；目标失效或重新分配时由调用方同步
EngagementState。

关键设计：
- RoleFit 由 unit_type × target_type 配置驱动，can_engage() 只做硬约束。
- 目标效果函数 F_j(D)=min(1, D/(q_j*H_j))；Demand 与出价都使用
  “新增单位带来的效果增量”，而不是只数目标数量或绝对分数。
- 期望伤害复用动态命中率、冷却/反应窗口和暴击期望；同步结算下用
  过杀惩罚限制同一目标的重复堆积。
- 基地作为战略目标进入同一分配器，但有独立目标价值、打击包上下限和
  承诺窗口。
- 每个单位只使用“自身可见 ∪ 已送达共享池”的目标集合，未收到通信的
  单位不会获得队友私有侦察信息。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from config import (COOPERATIVE_ASSIGNMENT_DEFAULTS, CRIT_CHANCE,
                    CRIT_DAMAGE_MULTIPLIER, DETECTION_TIMEOUT_STEPS,
                    MIN_ASSIGNMENT_DEMAND, STATUS_EVADE,
                    THREAT_VALUE_BY_TYPE)
from core.combat import calculate_hit_probability
from core.engagement import EngagementPhase
from core.target_pool import TargetSighting
from core.unit_config_loader import get_unit_stats
from core.units import Unit


@dataclass
class AssignmentResult:
    """某一时刻某一阵营的完整分配结果。"""

    assignments: dict[str, str] = field(default_factory=dict)
    target_members: dict[str, list[str]] = field(default_factory=dict)
    primary_target_id: str | None = None
    updated_step: int = 0
    assignment_since: dict[str, int] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    demand: dict[str, int] = field(default_factory=dict)

    def target_for(self, unit_id: str) -> str | None:
        return self.assignments.get(unit_id)


class CooperativeAllocator:
    """按阵营执行一次 RDMA 分配。"""

    def __init__(self, config: dict | None = None):
        self.config = config or COOPERATIVE_ASSIGNMENT_DEFAULTS
        self._dirty = True
        self._invalid_units: set[str] = set()
        self._invalid_targets: set[str] = set()

    # ── 脏标记：状态变化时提前重算 ──────────────────────────────
    def mark_dirty(self) -> None:
        self._dirty = True

    def invalidate_unit(self, unit_id: str) -> None:
        self._dirty = True
        self._invalid_units.add(unit_id)

    def invalidate_target(self, target_id: str) -> None:
        self._dirty = True
        self._invalid_targets.add(target_id)

    @property
    def dirty(self) -> bool:
        return self._dirty

    @property
    def invalid_units(self) -> set[str]:
        return set(self._invalid_units)

    @property
    def invalid_targets(self) -> set[str]:
        return set(self._invalid_targets)

    def consume_dirty(self) -> None:
        self._dirty = False
        self._invalid_units.clear()
        self._invalid_targets.clear()

    # ── 主入口 ──────────────────────────────────────────────────
    def allocate(
        self,
        units: Iterable[Unit],
        sightings: Iterable[TargetSighting] | None,
        step: int,
        battlefield=None,
        previous: AssignmentResult | None = None,
        visible_ids_by_unit: dict[str, set[str]] | None = None,
        context: dict | None = None,
    ) -> AssignmentResult:
        """执行一次分配。

        visible_ids_by_unit 必须是“每个单位自己的可见目标 ID 集合”
        （自身观测 ∪ 已送达共享信息）。为兼容独立测试，传入 None 时
        退化为使用全部已送达目标；Simulator 始终显式传入。
        context 可提供 ``enemy_combat_units``，用于基地 late-game 价值。
        """
        cfg = self.config
        unit_list = sorted(list(units), key=lambda u: u.id)
        records = list(sightings or [])
        previous = previous or AssignmentResult()
        context = context or {}

        # 目标基本信息。基地是静态战略目标，一经确认就保留到摧毁；
        # 普通目标仍按 TargetPool 的超时口径过滤。
        target_by_id: dict[str, Unit] = {}
        available_ids: set[str] = set()
        for record in records:
            target = record.target
            if target.is_destroyed:
                continue
            if (target.unit_type != "base"
                    and step - record.last_seen_step > DETECTION_TIMEOUT_STEPS):
                continue
            target_by_id[target.id] = target
            if record.available_step <= step:
                available_ids.add(target.id)

        if not target_by_id:
            self.consume_dirty()
            return AssignmentResult(updated_step=step)

        visible_sets: dict[str, set[str]] = {}
        for unit in unit_list:
            if visible_ids_by_unit is None:
                visible_sets[unit.id] = set(available_ids)
            else:
                visible_sets[unit.id] = set(visible_ids_by_unit.get(unit.id, set()))

        target_priority = self._target_priorities(target_by_id)
        target_values = self._target_values(target_by_id, target_priority, context)
        readiness = {unit.id: self._readiness(unit) for unit in unit_list}

        # pair (uid, tid) -> 基础出价与窗口期望伤害
        bids: dict[tuple[str, str], float] = {}
        damage: dict[tuple[str, str], float] = {}
        for unit in unit_list:
            if unit.is_destroyed or unit.ammo <= 0 or unit.attack_power <= 0:
                continue
            if unit.status == STATUS_EVADE:
                continue
            for target_id, target in target_by_id.items():
                if target_id not in visible_sets[unit.id]:
                    continue
                if not unit.can_engage(target):
                    continue
                distance_cost = self._distance_cost(unit, target, battlefield)
                role_fit = self._role_fit(unit.unit_type, target.unit_type)
                freshness = (1.0 if target.unit_type == "base" else
                             self._freshness(records, target_id, step,
                                             unit.id, visible_sets[unit.id]))
                bid = self._bid(unit, target, target_priority[target_id],
                                role_fit, readiness[unit.id], freshness,
                                distance_cost)
                expected = self._expected_damage(unit, target, battlefield)
                bids[(unit.id, target_id)] = bid
                damage[(unit.id, target_id)] = expected

        if not bids:
            self.consume_dirty()
            return AssignmentResult(updated_step=step)

        # 换目标惩罚计入出价：旧目标已不可见/不可交战时不惩罚。
        switch_penalty = float(cfg["switch_penalty"])
        for (unit_id, target_id) in list(bids):
            old_target = previous.assignments.get(unit_id)
            if (old_target is not None and old_target != target_id
                    and (unit_id, old_target) in bids):
                bids[(unit_id, target_id)] -= switch_penalty

        demand = self._demand(target_by_id, damage, unit_list)
        unit_by_id = {unit.id: unit for unit in unit_list}
        assignments, since, reasons = self._select_assignments(
            bids, damage, demand, target_priority, target_values,
            target_by_id, unit_by_id, previous, step)

        target_members: dict[str, list[str]] = {}
        for unit_id, target_id in assignments.items():
            target_members.setdefault(target_id, []).append(unit_id)
        for members in target_members.values():
            members.sort()

        primary = None
        if target_members:
            primary = sorted(
                target_members,
                key=lambda tid: (-len(target_members[tid]),
                                 -target_priority[tid], tid),
            )[0]

        self.consume_dirty()
        return AssignmentResult(
            assignments=assignments,
            target_members=target_members,
            primary_target_id=primary,
            updated_step=step,
            assignment_since=since,
            reasons=reasons,
            demand=demand,
        )

    # ── 评分 ────────────────────────────────────────────────────
    def _target_priorities(self, targets: dict[str, Unit]) -> dict[str, float]:
        raw = {}
        for target_id, target in targets.items():
            raw[target_id] = float(
                THREAT_VALUE_BY_TYPE.get(target.unit_type,
                                         target.threat_value or 1))
        low, high = min(raw.values()), max(raw.values())
        weights = self.config["target_priority_weights"]
        result = {}
        for target_id, target in targets.items():
            type_norm = 1.0 if high <= low else (raw[target_id] - low) / (high - low)
            low_hp = 1.0 - max(0.0, min(1.0, target.hp_ratio))
            value = (weights["type_threat"] * type_norm
                     + weights["low_hp"] * low_hp)
            if target.unit_type == "base":
                value += float(weights.get("base_bonus", 0.0))
            result[target_id] = min(1.0, value)
        return result

    def _target_values(self, targets: dict[str, Unit],
                       priorities: dict[str, float],
                       context: dict) -> dict[str, float]:
        values = dict(priorities)
        base = float(self.config.get("base_target_value", 0.9))
        bonus = 0.0
        threshold = int(self.config.get("late_game_unit_threshold", 2))
        enemy_units = context.get("enemy_combat_units")
        if enemy_units is not None and int(enemy_units) <= threshold:
            bonus = float(self.config.get("late_game_bonus", 0.0))
        for target_id, target in targets.items():
            if target.unit_type == "base":
                values[target_id] = max(priorities[target_id], base) + bonus
        return values

    def _role_fit(self, attacker_type: str, target_type: str) -> float:
        row = self.config["role_fit"].get(attacker_type, {})
        return float(row.get(target_type, 0.4))

    def _readiness(self, unit: Unit) -> float:
        weights = self.config["unit_readiness_weights"]
        try:
            max_ammo = int(get_unit_stats(unit.unit_type).get("ammo", 0))
        except KeyError:
            max_ammo = 0
        max_ammo = max(1, max_ammo, unit.ammo)
        health = max(0.0, min(1.0, unit.hp_ratio))
        ammo = max(0.0, min(1.0, unit.ammo / max_ammo))
        return weights["health"] * health + weights["ammo"] * ammo

    def _distance_cost(self, unit: Unit, target: Unit, battlefield) -> float:
        if battlefield is not None:
            diagonal = math.hypot(max(1, battlefield.width),
                                  max(1, battlefield.height))
        else:
            diagonal = 1000.0
        return min(1.0, unit.distance_to(target) / max(1.0, diagonal))

    def _freshness(self, records: Iterable[TargetSighting], target_id: str,
                   step: int, unit_id: str,
                   visible_ids: set[str]) -> float:
        # 未送达的信息不参与该单位评分。
        if target_id not in visible_ids:
            return 0.0
        last_seen = None
        for record in records:
            if record.target.id == target_id:
                last_seen = record.last_seen_step
                break
        if last_seen is None:
            return 0.0
        age = max(0, step - last_seen)
        return max(0.0, 1.0 - age / max(1, DETECTION_TIMEOUT_STEPS))

    def _bid(self, unit: Unit, target: Unit, priority: float,
             role_fit: float, readiness: float, freshness: float,
             distance_cost: float) -> float:
        weights = self.config["bid_weights"]
        base = (weights["target_priority"] * priority
                + weights["role_fit"] * role_fit
                + weights["readiness"] * readiness
                + weights["freshness"] * freshness
                - weights["distance_cost"] * distance_cost)
        return base

    # ── Demand：期望伤害、效果阈值与同步超杀覆盖 ───────────────
    def _desired_effect(self, target: Unit) -> float:
        values = self.config.get("desired_effect_by_type", {})
        return float(values.get(target.unit_type, 1.0))

    def _effect_threshold(self, target: Unit) -> float:
        return max(1.0, target.hp * self._desired_effect(target))

    def _effect(self, target: Unit, damage: float) -> float:
        """目标效果 F_j(D)=min(1, D/(q_j*H_j))。"""
        return max(0.0, min(1.0, damage / self._effect_threshold(target)))

    def _effect_gain(self, target: Unit, current: float,
                     addition: float) -> float:
        return (self._effect(target, current + addition)
                - self._effect(target, current))

    def _expected_damage(self, unit: Unit, target: Unit, battlefield) -> float:
        hit_prob = calculate_hit_probability(
            unit, target, battlefield, is_evading=(unit.status == STATUS_EVADE))
        if hit_prob <= 0:
            return 0.0
        crit_factor = 1.0 + CRIT_CHANCE * (CRIT_DAMAGE_MULTIPLIER - 1.0)
        shots = self._shots_in_horizon(unit)
        if shots <= 0:
            return 0.0
        return hit_prob * unit.attack_power * crit_factor * shots

    def _shots_in_horizon(self, unit: Unit) -> int:
        horizon = int(self.config["demand_horizon_steps"])
        eng = unit.engagement_state
        reaction = max(0, int(eng.reaction_delay))
        cooldown = max(0, int(eng.attack_cooldown))
        cycle = max(1, reaction + cooldown + 1)

        if eng.phase == EngagementPhase.ATTACK:
            ready_in = 0
        elif eng.phase == EngagementPhase.REACTING:
            ready_in = max(0, reaction - int(eng.reaction_progress))
        elif eng.phase == EngagementPhase.COOLDOWN:
            ready_in = (max(0, cooldown - int(eng.cooldown_progress))
                        + reaction)
        else:
            ready_in = reaction

        if ready_in >= horizon:
            return 0
        return 1 + (horizon - 1 - ready_in) // cycle

    def _target_capacity(self, target: Unit) -> int:
        cap = int(self.config["max_assignments_per_target"])
        if target.unit_type == "base":
            cap = min(cap, int(self.config.get("base_max_assignments", cap)))
        return max(1, cap)

    def _demand(self, targets: dict[str, Unit],
                damage: dict[tuple[str, str], float],
                units: list[Unit]) -> dict[str, int]:
        result: dict[str, int] = {}
        for target_id, target in targets.items():
            pair_values = [
                damage[(unit.id, target_id)] for unit in units
                if (unit.id, target_id) in damage
            ]
            capacity = self._target_capacity(target)
            if not pair_values:
                result[target_id] = 0
                continue
            values = sorted((value for value in pair_values if value > 0),
                            reverse=True)
            if not values:
                # 反应/冷却期较长时本窗口期望伤害可能为 0，但目标仍需
                # 保留最低需求，避免“无人接单”与无意义的过度分配。
                minimum = (int(self.config.get("base_min_assignments", 1))
                           if target.unit_type == "base"
                           else MIN_ASSIGNMENT_DEMAND)
                result[target_id] = min(
                    max(1, minimum), capacity, len(pair_values))
                continue
            threshold = self._effect_threshold(target)
            covered = 0.0
            k = 0
            for value in values:
                covered += value
                k += 1
                if covered >= threshold:
                    break
            minimum = (int(self.config.get("base_min_assignments", 1))
                       if target.unit_type == "base"
                       else MIN_ASSIGNMENT_DEMAND)
            k = max(k, minimum)
            k = min(k, capacity, len(values))
            result[target_id] = max(0, k)
        return result

    # ── 选择：保留 + 迟滞换目标 + 边际贪心 + 1-opt ─────────────
    def _select_assignments(
        self,
        bids: dict[tuple[str, str], float],
        damage: dict[tuple[str, str], float],
        demand: dict[str, int],
        target_priority: dict[str, float],
        target_values: dict[str, float],
        targets: dict[str, Unit],
        unit_by_id: dict[str, Unit],
        previous: AssignmentResult,
        step: int,
    ) -> tuple[dict[str, str], dict[str, int], dict[str, str]]:
        cfg = self.config
        min_bid = float(cfg["min_assignment_bid"])
        margin = float(cfg["reassign_margin"])
        overload = float(cfg["overload_penalty"])
        overkill_weight = float(cfg.get("effect_overkill_penalty", 0.0))
        ammo_weight = float(cfg.get("ammo_cost_weight", 0.0))
        effect_weight = (float(cfg.get("marginal_utility_weight", 1.0))
                         * float(cfg["bid_weights"].get("target_priority", 0.0)))
        commitment = int(cfg.get("base_commitment_steps", 0))

        assignments: dict[str, str] = {}
        since: dict[str, int] = {}
        reasons: dict[str, str] = {}
        counts: dict[str, int] = {tid: 0 for tid in demand}
        accumulated: dict[str, float] = {tid: 0.0 for tid in demand}

        def committed(unit_id: str, target_id: str) -> bool:
            target = targets.get(target_id)
            return (target is not None and target.unit_type == "base"
                    and commitment > 0
                    and step - previous.assignment_since.get(unit_id, step)
                    < commitment)

        def add(unit_id: str, target_id: str, stamp: int, reason: str) -> None:
            assignments[unit_id] = target_id
            since[unit_id] = stamp
            reasons[unit_id] = reason
            counts[target_id] = counts.get(target_id, 0) + 1
            accumulated[target_id] = (accumulated.get(target_id, 0.0)
                                      + damage.get((unit_id, target_id), 0.0))

        def remove(unit_id: str) -> None:
            target_id = assignments.pop(unit_id)
            since.pop(unit_id, None)
            reasons.pop(unit_id, None)
            counts[target_id] -= 1
            accumulated[target_id] = max(
                0.0, accumulated.get(target_id, 0.0)
                - damage.get((unit_id, target_id), 0.0))

        # 1) 保留旧分配（需求容量内；基地承诺窗口内放宽最低出价）。
        old_by_target: dict[str, list[str]] = {}
        for unit_id, target_id in previous.assignments.items():
            if (unit_id, target_id) not in bids:
                continue
            if (bids[(unit_id, target_id)] >= min_bid
                    or committed(unit_id, target_id)):
                old_by_target.setdefault(target_id, []).append(unit_id)
        for target_id in sorted(old_by_target):
            capacity = min(demand.get(target_id, 0), self._target_capacity(targets[target_id]))
            candidates = sorted(
                old_by_target[target_id],
                key=lambda uid: (-bids[(uid, target_id)],
                                 previous.assignment_since.get(uid, step),
                                 uid),
            )
            for unit_id in candidates[:capacity]:
                add(unit_id, target_id,
                    previous.assignment_since.get(unit_id, step), "retained")

        # 2) 迟滞换目标：按“新目标边际效果 - 旧目标边际损失”比较。
        upgrades = []
        for unit_id, old_target in assignments.items():
            if committed(unit_id, old_target):
                continue
            for (uid, new_target), bid in bids.items():
                if uid != unit_id or new_target == old_target:
                    continue
                if counts.get(new_target, 0) >= demand.get(new_target, 0):
                    continue
                old_damage = damage.get((unit_id, old_target), 0.0)
                old_loss = effect_weight * target_values.get(old_target, 0.0) * (
                    self._effect(targets[old_target], accumulated[old_target])
                    - self._effect(targets[old_target],
                                   max(0.0, accumulated[old_target] - old_damage)))
                new_target_obj = targets[new_target]
                new_gain = effect_weight * target_values.get(new_target, 0.0) * (
                    self._effect_gain(new_target_obj,
                                      accumulated.get(new_target, 0.0),
                                      damage.get((unit_id, new_target), 0.0)))
                improvement = (bid + new_gain) - (
                    bids.get((unit_id, old_target), 0.0) + old_loss)
                if improvement > margin:
                    upgrades.append((improvement,
                                     target_values.get(new_target, 0.0),
                                     unit_id, new_target))
        upgrades.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
        for _, _, unit_id, new_target in upgrades:
            old_target = assignments.get(unit_id)
            if old_target is None or old_target == new_target:
                continue
            if committed(unit_id, old_target):
                continue
            if counts.get(new_target, 0) >= demand.get(new_target, 0):
                continue
            remove(unit_id)
            add(unit_id, new_target, step, "switch")

        # 3) 未分配单位按边际收益贪心补充。
        assigned = set(assignments)
        while True:
            best = None
            for (unit_id, target_id), bid in bids.items():
                if unit_id in assigned or bid < min_bid:
                    continue
                if counts.get(target_id, 0) >= demand.get(target_id, 0):
                    continue
                target = targets[target_id]
                addition = damage.get((unit_id, target_id), 0.0)
                current = accumulated.get(target_id, 0.0)
                effect_gain = effect_weight * target_values.get(target_id, 0.0) * (
                    self._effect_gain(target, current, addition))
                threshold = self._effect_threshold(target)
                overkill = max(0.0, current + addition - threshold) / threshold
                overload_ratio = (counts.get(target_id, 0)
                                  / max(1, demand.get(target_id, 0)))
                unit = unit_by_id.get(unit_id)
                ammo_cost = (ammo_weight / max(1, unit.ammo)) if unit else 0.0
                marginal = (bid + effect_gain
                            - overload * overload_ratio
                            - overkill_weight * overkill
                            - ammo_cost)
                # 效果已饱和时不再为同一目标追加单位；全零窗口仍保留
                # 最低需求，保证有人在下一窗口接单。
                if current > 0 and addition > 0 and effect_gain <= 1e-9:
                    continue
                key = (-marginal, -target_priority.get(target_id, 0.0),
                       unit_id, target_id)
                if best is None or key < best[0]:
                    best = (key, unit_id, target_id)
            if best is None:
                break
            _, unit_id, target_id = best
            add(unit_id, target_id, step, "new")
            assigned.add(unit_id)

        # 4) 单轮 1-opt：释放并重新填满被过杀保护释放出的容量。
        for unit_id in sorted(assignments):
            old_target = assignments[unit_id]
            if committed(unit_id, old_target):
                continue
            old_damage = damage.get((unit_id, old_target), 0.0)
            old_loss = effect_weight * target_values.get(old_target, 0.0) * (
                self._effect(targets[old_target], accumulated[old_target])
                - self._effect(targets[old_target],
                               max(0.0, accumulated[old_target] - old_damage)))
            best_swap = None
            for (uid, new_target), bid in bids.items():
                if uid != unit_id or new_target == old_target:
                    continue
                if counts.get(new_target, 0) >= demand.get(new_target, 0):
                    continue
                new_gain = effect_weight * target_values.get(new_target, 0.0) * (
                    self._effect_gain(targets[new_target],
                                      accumulated.get(new_target, 0.0),
                                      damage.get((unit_id, new_target), 0.0)))
                improvement = (bid + new_gain) - (
                    bids.get((unit_id, old_target), 0.0) + old_loss)
                key = (-improvement, -target_values.get(new_target, 0.0),
                       new_target)
                if improvement > margin and (best_swap is None or key < best_swap[0]):
                    best_swap = (key, new_target)
            if best_swap is not None:
                remove(unit_id)
                add(unit_id, best_swap[1], step, "swap")

        # 5) 清理低于最低出价的保留项，避免幽灵分配。
        for unit_id in sorted(list(assignments), reverse=True):
            target_id = assignments[unit_id]
            if (bids.get((unit_id, target_id), 0.0) < min_bid
                    and not committed(unit_id, target_id)):
                remove(unit_id)

        # 6) 过杀保护：累计期望伤害超过阈值比例时，释放边际贡献最低的
        # 非基地承诺成员。同步结算本身不取消已排队攻击，这里只约束下一波。
        for target_id in sorted(targets):
            target = targets[target_id]
            threshold = self._effect_threshold(target)
            ratio = float(cfg.get("overkill_release_ratio", 1.2))
            minimum = (int(cfg.get("base_min_assignments", 1))
                       if target.unit_type == "base" else 1)
            while (accumulated.get(target_id, 0.0) > ratio * threshold
                   and counts.get(target_id, 0) > minimum):
                candidates = [uid for uid, tid in assignments.items()
                              if tid == target_id
                              and not committed(uid, target_id)]
                if not candidates:
                    break
                victim = min(
                    candidates,
                    key=lambda uid: (
                        self._effect_gain(
                            target,
                            accumulated.get(target_id, 0.0)
                            - damage.get((uid, target_id), 0.0),
                            damage.get((uid, target_id), 0.0)),
                        bids.get((uid, target_id), 0.0), uid))
                remove(victim)

        return assignments, since, reasons
