"""协同动态边际拍卖（Role-aware Dynamic Marginal Auction, RDMA）。

本模块只做“单位 → 目标”的确定性分配，不移动、不开火。分配结果由
Simulator 用来约束移动和攻击授权；目标失效或重新分配时由调用方同步
EngagementState。

关键设计：
- RoleFit 由 unit_type × target_type 配置驱动，can_engage() 只做硬约束。
- Demand 用“单位-目标对期望伤害”估算，考虑动态命中率、冷却/反应时间、
  同步结算下的超杀覆盖，而不是简单按目标数量分配。
- 部分分配优先：先保留旧分配，再以边际收益做贪心补充；换目标需要超过
  reassign_margin 的收益。
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
    ) -> AssignmentResult:
        """执行一次分配。

        visible_ids_by_unit 必须是“每个单位自己的可见目标 ID 集合”
        （自身观测 ∪ 已送达共享信息）。为兼容独立测试，传入 None 时
        退化为使用全部已送达目标；Simulator 始终显式传入。
        """
        cfg = self.config
        unit_list = sorted(list(units), key=lambda u: u.id)
        records = list(sightings or [])
        previous = previous or AssignmentResult()

        # 目标基本信息。只保留存活、非基地且未超时的目标；基地不参与
        # RDMA v1。超时判定与 TargetPool.cleanup() 保持同一口径。
        target_by_id: dict[str, Unit] = {}
        available_ids: set[str] = set()
        for record in records:
            target = record.target
            if target.is_destroyed or target.unit_type == "base":
                continue
            if step - record.last_seen_step > DETECTION_TIMEOUT_STEPS:
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
        readiness = {unit.id: self._readiness(unit) for unit in unit_list}

        # pair (uid, tid) -> (bid, demand_contribution)
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
                freshness = self._freshness(
                    records, target_id, step, unit.id, visible_sets[unit.id])
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
        assignments, since, reasons = self._select_assignments(
            bids, demand, target_priority, previous, step)

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
            result[target_id] = (weights["type_threat"] * type_norm
                                 + weights["low_hp"] * low_hp)
        return result

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

    # ── Demand：期望伤害与同步超杀覆盖 ─────────────────────────
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

    def _demand(self, targets: dict[str, Unit],
                damage: dict[tuple[str, str], float],
                units: list[Unit]) -> dict[str, int]:
        cfg = self.config
        max_assign = int(cfg["max_assignments_per_target"])
        result: dict[str, int] = {}
        for target_id, target in targets.items():
            pair_values = [
                damage[(unit.id, target_id)] for unit in units
                if (unit.id, target_id) in damage
            ]
            if not pair_values:
                result[target_id] = 0
                continue
            values = sorted((value for value in pair_values if value > 0),
                            reverse=True)
            if not values:
                # 反应/冷却期较长时本窗口期望伤害可能为 0，但目标仍需
                # 保留最低需求（而不是把所有可行单位都压上去），避免
                # “无人接单”与无意义的过度分配。
                result[target_id] = min(
                    max(1, MIN_ASSIGNMENT_DEMAND), max_assign, len(pair_values))
                continue
            covered = 0.0
            k = 0
            for value in values:
                covered += value
                k += 1
                if covered >= target.hp:
                    break
            k = max(k, MIN_ASSIGNMENT_DEMAND)
            k = min(k, max_assign, len(values))
            result[target_id] = max(0, k)
        return result

    # ── 选择：保留 + 迟滞换目标 + 边际贪心 ─────────────────────
    def _select_assignments(
        self,
        bids: dict[tuple[str, str], float],
        demand: dict[str, int],
        target_priority: dict[str, float],
        previous: AssignmentResult,
        step: int,
    ) -> tuple[dict[str, str], dict[str, int], dict[str, str]]:
        cfg = self.config
        min_bid = float(cfg["min_assignment_bid"])
        max_assign = int(cfg["max_assignments_per_target"])
        margin = float(cfg["reassign_margin"])
        overload = float(cfg["overload_penalty"])

        assignments: dict[str, str] = {}
        since: dict[str, int] = {}
        reasons: dict[str, str] = {}
        counts: dict[str, int] = {tid: 0 for tid in demand}

        # 1) 保留旧分配（需求容量内）。
        old_by_target: dict[str, list[str]] = {}
        for unit_id, target_id in previous.assignments.items():
            if (unit_id, target_id) in bids and bids[(unit_id, target_id)] >= min_bid:
                old_by_target.setdefault(target_id, []).append(unit_id)
        for target_id in sorted(old_by_target):
            capacity = min(demand.get(target_id, 0), max_assign)
            candidates = sorted(
                old_by_target[target_id],
                key=lambda uid: (-bids[(uid, target_id)],
                                 previous.assignment_since.get(uid, step),
                                 uid),
            )
            for unit_id in candidates[:capacity]:
                assignments[unit_id] = target_id
                since[unit_id] = previous.assignment_since.get(unit_id, step)
                reasons[unit_id] = "retained"
                counts[target_id] += 1

        # 2) 迟滞换目标：只有收益超过 reassign_margin 才换。
        upgrades = []
        for unit_id, old_target in assignments.items():
            for (uid, new_target), bid in bids.items():
                if uid != unit_id or new_target == old_target:
                    continue
                if counts.get(new_target, 0) >= demand.get(new_target, 0):
                    continue
                old_bid = bids.get((unit_id, old_target), 0.0)
                improvement = bid - old_bid
                if improvement > margin:
                    upgrades.append((improvement, target_priority.get(new_target, 0.0),
                                     unit_id, new_target))
        upgrades.sort(key=lambda item: (-item[0], -item[1], item[2], item[3]))
        switched: set[str] = set()
        for improvement, _, unit_id, new_target in upgrades:
            if unit_id in switched:
                continue
            old_target = assignments.get(unit_id)
            if old_target is None or old_target == new_target:
                continue
            if counts.get(new_target, 0) >= demand.get(new_target, 0):
                continue
            counts[old_target] -= 1
            counts[new_target] += 1
            assignments[unit_id] = new_target
            since[unit_id] = step
            reasons[unit_id] = "switch"
            switched.add(unit_id)

        # 3) 未分配单位按边际收益贪心补充。
        assigned = set(assignments)
        while True:
            best = None
            for (unit_id, target_id), bid in bids.items():
                if unit_id in assigned or bid < min_bid:
                    continue
                if counts.get(target_id, 0) >= demand.get(target_id, 0):
                    continue
                penalty = overload * (counts.get(target_id, 0)
                                      / max(1, demand.get(target_id, 0)))
                marginal = bid - penalty
                key = (-marginal, -target_priority.get(target_id, 0.0),
                       unit_id, target_id)
                if best is None or key < best[0]:
                    best = (key, unit_id, target_id)
            if best is None:
                break
            _, unit_id, target_id = best
            assignments[unit_id] = target_id
            since[unit_id] = step
            reasons[unit_id] = "new"
            counts[target_id] += 1
            assigned.add(unit_id)

        # 4) 清理低于最低出价的保留项（例如旧目标被削弱/距离过远）。
        for unit_id, target_id in list(assignments.items()):
            if bids.get((unit_id, target_id), 0.0) < min_bid:
                counts[target_id] -= 1
                del assignments[unit_id]
                del since[unit_id]
                del reasons[unit_id]

        return assignments, since, reasons
