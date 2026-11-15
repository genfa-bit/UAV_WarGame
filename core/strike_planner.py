"""分层时相协同打击（Hierarchical Time-Phased Cooperative Strike, HTCS）。

HTCS 在 RDMA v2 的“单位 → 目标”分配之上增加三层结构：

1. **滚动波次（rolling waves）**：每 ``wave_length_steps`` 步重规划一次，
   当前波次只承诺一个打击时刻（TOT），完成不了的伤害留给下一波次。
2. **任务束（task bundle，CBBA 思路）**：每个单位可在一个波次内承担多个
   按优先级排序的任务；任务按“压制敌防空（SEAD）→ 普通目标 → 基地”
   的顺序执行，形成先导压制、再主攻的时序。
3. **时间协调（TOT/火力门）**：同一任务的各单位以最晚到达者的 ETA 作为
   共同 TOT，先到者待机、后到者到达即打；火力门在 ``core.time_coordination``。

与 RDMA v2 的关系：复用 ``CooperativeAllocator.score_pairs`` 的出价与
期望伤害，仅启用三处已知修正（绝对优先级归一化、弹药截断、效果权重
解耦），并新增伤害账本、BDA/再攻击、SEAD 压制与态势自适应战法。
``mode`` 缺省仍为 ``rdma_v2``，因此既有行为保持不变。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from config import COOPERATIVE_ASSIGNMENT_DEFAULTS, CRIT_CHANCE, CRIT_DAMAGE_MULTIPLIER
from core.cooperative_allocator import AssignmentResult, CooperativeAllocator
from core.combat import calculate_hit_probability
from core.target_pool import TargetSighting
from core.time_coordination import estimate_eta, plan_tot
from core.units import Unit

_DOCTRINES = ("balanced", "attrition", "decapitation", "base_pressure")


def choose_doctrine(own_strength: float, enemy_strength: float,
                    targets, config: dict) -> str:
    """选择态势自适应战法。

    ``adaptive`` 下：优势时优先斩首（可见指挥节点）或压基地；劣势时转入
    消耗战，避免把有限弹药砸在基地上；均势保持平衡。配置为固定战法时
    直接返回该战法。
    """
    mode = str(config.get("doctrine", "adaptive"))
    if mode in _DOCTRINES:
        return mode
    ratio = float(own_strength) / max(1.0, float(enemy_strength))
    if ratio >= float(config.get("doctrine_advantage_ratio", 1.25)):
        if any(target.unit_type == "command_node" for target in targets):
            return "decapitation"
        return "base_pressure"
    if ratio <= float(config.get("doctrine_disadvantage_ratio", 0.80)):
        return "attrition"
    return "balanced"


def doctrine_priority_bonus(target: Unit, doctrine: str) -> float:
    """战法对目标价值的加成。"""
    if doctrine == "decapitation":
        if target.unit_type == "command_node":
            return 0.35
        if target.unit_type == "missile_vehicle":
            return 0.10
    elif doctrine == "base_pressure":
        if target.unit_type == "base":
            return 0.30
    elif doctrine == "attrition":
        bonus = 0.20 * (1.0 - max(0.0, min(1.0, target.hp_ratio)))
        if target.unit_type == "base":
            bonus -= 0.25
        return bonus
    return 0.0


def doctrine_ammo_reserve(doctrine: str, config: dict) -> float:
    """战法对应的弹药预留比例（机会射击/任务分配的最低余量）。"""
    if doctrine == "attrition":
        return max(float(config.get("ammo_reserve_ratio", 0.20)), 0.35)
    if doctrine == "base_pressure":
        return min(float(config.get("ammo_reserve_ratio", 0.20)), 0.10)
    return float(config.get("ammo_reserve_ratio", 0.20))


@dataclass
class StrikeTask:
    """一个打击任务：打谁、什么时刻、由谁打多少发。"""

    task_id: str
    target_id: str
    target: Unit
    wave: int
    precedence: int
    priority: float
    role: str                     # sead | strike | base
    reason: str                   # sead | strike | base | reattack
    required_damage: float
    tot_step: int
    window_start: int
    late_until: int
    members: list[str] = field(default_factory=list)
    shots: dict[str, int] = field(default_factory=dict)
    planned_damage: float = 0.0
    state: str = "planned"        # planned | ready | understrength | done | failed
    doctrine: str = "balanced"
    # 时间折扣后的执行优先级与最佳 ETA（时间维信息，供任务束串行排序）。
    effective_priority: float = 0.0
    eta_best: int = 0
    order: int = 0
    # 任务创建时目标已结算伤害的基线：BDA 用它求“本波次实际兑现”。
    applied_at_plan: float = 0.0

    @property
    def assigned(self) -> list[str]:
        return list(self.members)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "target_id": self.target_id,
            "wave": self.wave,
            "precedence": self.precedence,
            "priority": round(self.priority, 4),
            "effective_priority": round(self.effective_priority, 4),
            "eta_best": self.eta_best,
            "order": self.order,
            "role": self.role,
            "reason": self.reason,
            "required_damage": round(self.required_damage, 2),
            "planned_damage": round(self.planned_damage, 2),
            "members": list(self.members),
            "shots": dict(self.shots),
            "tot_step": self.tot_step,
            "window_start": self.window_start,
            "late_until": self.late_until,
            "state": self.state,
            "doctrine": self.doctrine,
        }


class StrikePlanner:
    """按阵营生成 HTCS 波次计划。"""

    def __init__(self, config: dict | None = None):
        self.config = config or COOPERATIVE_ASSIGNMENT_DEFAULTS
        self.htcs = dict(self.config.get("htcs", {}))
        self.allocator = CooperativeAllocator(self.config)

    # ── 主入口 ──────────────────────────────────────────────────
    def plan(
        self,
        units,
        sightings: list[TargetSighting] | None,
        step: int,
        battlefield=None,
        previous: AssignmentResult | None = None,
        visible_ids_by_unit: dict[str, set[str]] | None = None,
        context: dict | None = None,
        ledger=None,
    ) -> AssignmentResult:
        """生成当前波次的任务、任务束与打击时刻。"""
        previous = previous or AssignmentResult()
        context = context or {}
        cfg = self.htcs
        wave_length = int(cfg.get("wave_length_steps", 6))
        wave = step // max(1, wave_length)

        (bids, _damage, target_priority, target_values, target_by_id,
         unit_by_id, _visible, unit_list) = self.allocator.score_pairs(
            units, sightings, step, battlefield, visible_ids_by_unit, context,
            htcs=True)
        if not target_by_id or not bids:
            return AssignmentResult(updated_step=step, wave_id=wave,
                                    doctrine="balanced")

        visible_targets = [target for target_id, target in target_by_id.items()
                           if any((unit.id, target_id) in bids
                                  for unit in unit_list)]

        # ── 时间维：ETA 折扣与可行性 ─────────────────────────────
        # HTCS 与 RDMA v2 的分野在于时间。RDMA 的 bid 不含机动代价，会把
        # 已经在射程内的单位派去追几百像素外的散兵。这里按
        # discount = wave / (wave + ETA) 对“单位-目标”对的效用打折，并规定
        # ETA 超过 planning_horizon_waves 个波次的目标不进入本波次任务束。
        etas: dict[tuple[str, str], int] = {}
        for pair in bids:
            unit = unit_by_id.get(pair[0])
            target = target_by_id.get(pair[1])
            if unit is not None and target is not None:
                etas[pair] = estimate_eta(unit, target, battlefield)
        horizon = wave_length * max(1, int(cfg.get("planning_horizon_waves", 3)))

        def time_discount(eta: int) -> float:
            return wave_length / (wave_length + max(0, int(eta)))
        doctrine = choose_doctrine(
            float(context.get("own_strength", 0.0)),
            float(context.get("enemy_strength", 0.0)),
            visible_targets, cfg)

        enemy_units = list(context.get("enemy_units") or [])
        reattack_targets = set(context.get("reattack_targets") or set())
        reserve_ratio = doctrine_ammo_reserve(doctrine, cfg)
        min_bid = float(self.config.get("min_assignment_bid", 0.05))

        priorities: dict[str, float] = {}
        for target_id, target in target_by_id.items():
            bonus = doctrine_priority_bonus(target, doctrine)
            applied = ledger.applied(target_id) if ledger is not None else 0.0
            if applied > 0.0 or target_id in reattack_targets:
                bonus += float(cfg.get("reattack_bonus", 0.0)) * max(
                    0.0, min(1.0, applied / max(1.0, target.max_hp)))
            priorities[target_id] = max(0.0, target_priority[target_id] + bonus)

        # 本波次各目标可望投入的期望伤害上限：任务需求取“剩余需求”与
        # “本波次火力上限”的较小值。这样任务状态从“整个目标要打光”变成
        # “本波次承诺的火力是否兑现”，BDA 才能区分“任务失败”与“下个
        # 波次继续打”。
        wave_shots_estimate = self._wave_shot_capacity(unit_list, wave_length)
        capacity_hint: dict[str, float] = {}
        for pair, eta in etas.items():
            if eta > horizon or bids.get(pair, 0.0) < min_bid:
                continue
            unit = unit_by_id.get(pair[0])
            target = target_by_id.get(pair[1])
            if unit is None or target is None:
                continue
            # 与任务束分配口径一致：先扣掉战法规定的弹药预留，再按波次
            # 射击能力截断。否则任务需求会按“满弹量”估算，而实际分配只能
            # 用预留后的弹药，任务永远被标成 understrength，BDA 也就永远
            # 无法判定“执行失败”。
            reserve = math.ceil(reserve_ratio * self.allocator.max_ammo(unit))
            reserve = min(reserve, max(0, int(unit.ammo) - 1))
            usable = max(0, int(unit.ammo) - reserve)
            shots = min(wave_shots_estimate.get(unit.id, 1), usable)
            if shots <= 0:
                continue
            capacity_hint[target.id] = (
                capacity_hint.get(target.id, 0.0)
                + shots * self._shot_damage(unit, target, battlefield))

        # ── 1. 形成任务候选：SEAD 先导、普通打击、基地主攻 ─────
        task_specs = self._task_specs(
            target_by_id, priorities, target_values, bids, enemy_units,
            doctrine, step, wave, previous, ledger, cfg, etas, time_discount,
            horizon, capacity_hint)
        task_specs = task_specs[:max(1, int(cfg.get("max_tasks_per_wave", 6)))]
        for index, spec in enumerate(task_specs):
            spec.order = index   # 已按“SEAD 先导 + 时间折扣优先级”排好执行顺序

        # ── 2. 任务束构建：按优先级贪心分配单位 ─────────────────
        task_by_id: dict[str, StrikeTask] = {}
        unit_tasks: dict[str, list[str]] = {}
        virtual_ammo = {unit.id: int(unit.ammo) for unit in unit_list}
        bundle_size = max(1, int(cfg.get("bundle_size", 2)))
        wave_shots = self._wave_shot_capacity(unit_list, wave_length)
        # 同一单位的任务束按 precedence 串行执行：前一个任务（如 SEAD）占用的
        # 射击周期之后才轮到下一个任务。否则“先压制后主攻”的单位会拿着更晚
        # 的 SEAD TOT 待在队首，把更早的主攻窗口白白等过期。
        # 初值取单位真实的下一次可开火时刻：反应中/冷却中的单位不能把
        # “本波次 1 发”当成马上就能打出去，否则任务计划无法兑现，BDA 会
        # 把每一波次都判成失败。
        unit_ready = {unit.id: self._ready_step(unit, step)
                      for unit in unit_list}

        for task in task_specs:
            target = task.target
            threshold = self.allocator.effect_threshold(target)
            capacity = self._task_capacity(target)
            planned = 0.0
            candidates = []
            for unit in unit_list:
                pair = (unit.id, target.id)
                if pair not in bids:
                    continue
                if bids[pair] < min_bid:
                    continue
                if len(unit_tasks.get(unit.id, [])) >= bundle_size:
                    continue
                eta = etas.get(pair, horizon + 1)
                if eta > horizon:
                    # 本波次内到不了：不占用任务束，留给后续波次重规划。
                    continue
                reserve = math.ceil(
                    reserve_ratio * self.allocator.max_ammo(unit))
                # 预留弹药只用来挡“后续波次”，不能把所有弹药都锁死：
                # 至少保留 1 发可执行本波次任务，否则最后几发永远打不出去。
                reserve = min(reserve, max(0, virtual_ammo.get(unit.id, 0) - 1))
                available = virtual_ammo.get(unit.id, 0) - reserve
                shots = min(wave_shots.get(unit.id, 1), available)
                if shots <= 0:
                    continue
                shot_damage = self._shot_damage(unit, target, battlefield)
                if shot_damage <= 0:
                    continue
                effect_gain = self.allocator.marginal_effect(
                    target, planned, shots * shot_damage)
                score = ((bids[pair]
                          + float(self.config.get("marginal_utility_weight", 1.0))
                          * target_values.get(target.id, 0.0) * effect_gain)
                         * time_discount(eta))
                candidates.append((score, shot_damage, shots, unit))

            candidates.sort(key=lambda item: (-item[0], -item[1], item[3].id))
            for score, shot_damage, shots, unit in candidates:
                if len(task.members) >= capacity:
                    break
                if planned >= task.required_damage:
                    break
                contribution = shots * shot_damage
                task.members.append(unit.id)
                task.shots[unit.id] = shots
                planned += contribution
                virtual_ammo[unit.id] -= shots
                unit_tasks.setdefault(unit.id, []).append(task.task_id)

            task.planned_damage = planned
            member_etas = [etas.get((uid, target.id),
                                    estimate_eta(unit_by_id[uid], target,
                                                 battlefield))
                           for uid in task.members]
            tot = plan_tot(step, member_etas, wave_length)
            if task.members:
                # 不得早于任一成员完成前序任务的时刻。
                tot = max(tot, max(unit_ready[uid] for uid in task.members))
            task.tot_step = tot
            tolerance = int(cfg.get("tot_tolerance_steps", 1))
            late = int(cfg.get("tot_late_steps", 3))
            task.window_start = max(step, tot - tolerance)
            task.late_until = tot + late
            for uid in task.members:
                unit_ready[uid] = tot + max(
                    1, int(task.shots.get(uid, 1))
                ) * self._shot_cycle(unit_by_id[uid])
            task.state = ("ready" if planned >= 0.9 * task.required_damage
                          else "understrength" if task.members
                          else "unassigned")
            task_by_id[task.task_id] = task

        # ── 3. 组装 AssignmentResult ────────────────────────────
        assignments: dict[str, str] = {}
        bundles: dict[str, list[str]] = {}
        attack_steps: dict[str, int] = {}
        reasons: dict[str, str] = {}
        assignment_since: dict[str, int] = {}
        for unit_id, task_ids in unit_tasks.items():
            ordered = sorted(
                (task_by_id[task_id] for task_id in task_ids),
                key=lambda task: task.order)
            if not ordered:
                continue
            bundles[unit_id] = [task.task_id for task in ordered]
            assignments[unit_id] = ordered[0].target_id
            attack_steps[unit_id] = ordered[0].tot_step
            reasons[unit_id] = f"htcs:{ordered[0].role}"
            if previous.assignments.get(unit_id) == ordered[0].target_id:
                assignment_since[unit_id] = previous.assignment_since.get(
                    unit_id, step)
            else:
                assignment_since[unit_id] = step

        target_members: dict[str, list[str]] = {}
        demand: dict[str, int] = {}
        ledger_plan: dict[str, float] = {}
        for task in task_by_id.values():
            if task.members:
                target_members.setdefault(task.target_id, []).extend(task.members)
            demand[task.target_id] = max(
                demand.get(task.target_id, 0), len(task.members))
            ledger_plan[task.target_id] = (
                ledger_plan.get(task.target_id, 0.0) + task.planned_damage)
        for members in target_members.values():
            members.sort()

        primary = None
        active_tasks = [task for task in task_by_id.values() if task.members]
        if active_tasks:
            primary_task = min(active_tasks, key=lambda task: (
                task.precedence, -task.priority, -len(task.members),
                task.task_id))
            primary = primary_task.target_id

        return AssignmentResult(
            assignments=assignments,
            target_members=target_members,
            primary_target_id=primary,
            updated_step=step,
            assignment_since=assignment_since,
            reasons=reasons,
            demand=demand,
            bundles=bundles,
            attack_steps=attack_steps,
            wave_id=wave,
            doctrine=doctrine,
            tasks=task_by_id,
            ledger_plan=ledger_plan,
        )

    # ── 任务候选 ────────────────────────────────────────────────
    def _task_specs(
        self,
        targets: dict[str, Unit],
        priorities: dict[str, float],
        values: dict[str, float],
        bids: dict[tuple[str, str], float],
        enemy_units: list[Unit],
        doctrine: str,
        step: int,
        wave: int,
        previous: AssignmentResult,
        ledger,
        cfg: dict,
        etas: dict[tuple[str, str], int] | None = None,
        time_discount=None,
        horizon: int = 0,
        capacity_hint: dict[str, float] | None = None,
    ) -> list[StrikeTask]:
        """生成按执行顺序排列的任务候选（含 SEAD 先导任务）。"""
        known = set(targets)
        tasked: set[str] = set()
        specs: list[StrikeTask] = []
        etas = etas or {}
        capacity_hint = capacity_hint or {}

        def eta_best(target_id: str) -> int:
            values = [eta for (unit_id, tid), eta in etas.items()
                      if tid == target_id]
            return min(values) if values else max(1, horizon or 1)

        def reachable(target_id: str) -> bool:
            return any(tid == target_id and eta <= max(0, horizon)
                       for (_unit_id, tid), eta in etas.items())

        def need_for(target: Unit, role: str) -> float:
            threshold = self.allocator.effect_threshold(target)
            if role == "sead":
                threshold *= float(cfg.get("sead_effect_ratio", 0.6))
            reserved = ledger.reserved(target.id) if ledger is not None else 0.0
            need = max(0.0, threshold - reserved)
            wave_cap = capacity_hint.get(target.id, 0.0)
            if wave_cap > 0.0:
                # 单个波次只承诺“本波次打得出”的那部分伤害。
                need = min(need, wave_cap)
            return need

        def make_task(target: Unit, precedence: int, role: str,
                      reason: str) -> StrikeTask:
            task_id = f"{target.id}:{role}:{wave}"
            raw_priority = priorities.get(target.id, 0.0)
            best_eta = eta_best(target.id)
            discount = (time_discount(best_eta) if time_discount is not None
                        else 1.0)
            return StrikeTask(
                task_id=task_id,
                target_id=target.id,
                target=target,
                wave=wave,
                precedence=precedence,
                priority=raw_priority,
                effective_priority=raw_priority * discount,
                eta_best=best_eta,
                role=role,
                reason=reason,
                required_damage=need_for(target, role),
                tot_step=step,
                window_start=step,
                late_until=step,
                doctrine=doctrine,
                applied_at_plan=(ledger.applied(target.id)
                                 if ledger is not None else 0.0),
            )

        # SEAD：为基地/指挥节点等高价值目标先压制其掩护兵力。
        if cfg.get("sead_enabled", True):
            sead_candidates = sorted(
                (target for target in targets.values()
                 if target.unit_type in ("base", "command_node")
                 and target.id not in tasked),
                key=lambda target: (-priorities.get(target.id, 0.0),
                                    target.id))
            radius = float(cfg.get("sead_defense_radius", 220.0))
            for protected in sead_candidates:
                defenders = self._defenders_of(protected, enemy_units, radius)
                defender = next(
                    (unit for unit in defenders
                     if unit.id in known and unit.id != protected.id
                     and unit.id not in tasked and reachable(unit.id)
                     and any(pair[1] == unit.id for pair in bids)),
                    None)
                if defender is None:
                    continue
                need = need_for(defender, "sead")
                if need <= 0.0:
                    continue
                reason = ("reattack" if (ledger is not None
                                        and ledger.applied(defender.id) > 0)
                          else "sead")
                specs.append(make_task(defender, 0, "sead", reason))
                tasked.add(defender.id)

        # 普通打击与基地主攻：按“时间折扣后的效用”排序，而不是按
        # strike/base 的固定档次。否则远处的散兵会排在射程内的高价值
        # 基地之前，把部队从已经到位的目标上拉走。
        ordered = sorted(
            (target for target in targets.values()
             if target.id not in tasked),
            key=lambda target: (-priorities.get(target.id, 0.0), target.id))
        for target in ordered:
            need = need_for(target, "strike")
            if need <= 0.0:
                continue   # 账本已覆盖：本波次不再追加伤害
            role = "base" if target.unit_type == "base" else "strike"
            precedence = 2 if role == "base" else 1
            applied = ledger.applied(target.id) if ledger is not None else 0.0
            reason = "reattack" if applied > 0.0 else role
            specs.append(make_task(target, precedence, role, reason))
            tasked.add(target.id)

        # 执行顺序：SEAD（precedence=0）永远先导；其余按时间折扣效用排。
        specs.sort(key=lambda task: (
            0 if task.precedence == 0 else 1,
            -task.effective_priority,
            task.precedence,
            task.task_id))
        return specs

    @staticmethod
    def _defenders_of(protected: Unit, enemies: list[Unit],
                      radius: float) -> list[Unit]:
        """保护目标的敌方掩护兵力：非基地、具攻击力且在防御半径内。"""
        defenders = [
            unit for unit in enemies
            if not unit.is_destroyed and unit.id != protected.id
            and unit.unit_type != "base" and unit.attack_power > 0
            and unit.distance_to(protected) <= radius
        ]
        return sorted(defenders, key=lambda unit: (-unit.threat_score, unit.id))

    # ── 容量与火力 ──────────────────────────────────────────────
    def _task_capacity(self, target: Unit) -> int:
        cap = int(self.config.get("max_assignments_per_target", 3))
        if target.unit_type == "base":
            cap = min(cap, int(self.config.get("base_max_assignments", cap)))
        return max(1, cap)

    @staticmethod
    def _shot_damage(unit: Unit, target: Unit, battlefield) -> float:
        """单发期望伤害（含暴击期望），用于任务束的覆盖估算。"""
        hit_prob = calculate_hit_probability(unit, target, battlefield)
        crit_factor = 1.0 + CRIT_CHANCE * (CRIT_DAMAGE_MULTIPLIER - 1.0)
        return max(0.0, hit_prob * unit.attack_power * crit_factor)

    @staticmethod
    def _ready_step(unit: Unit, step: int) -> int:
        """单位最早可以开火的步数（含剩余反应/冷却）。"""
        eng = unit.engagement_state
        phase = eng.phase.name
        if phase == "COOLDOWN":
            remaining = max(0, int(eng.attack_cooldown)
                            - int(eng.cooldown_progress))
            return (step + remaining + max(0, int(eng.reaction_delay)) + 1)
        if phase == "REACTING":
            remaining = max(0, int(eng.reaction_delay)
                            - int(eng.reaction_progress))
            return step + remaining + 1
        return step

    @staticmethod
    def _shot_cycle(unit: Unit) -> int:
        """单位两次射击之间的最短间隔（反应 + 冷却 + 1）。"""
        eng = unit.engagement_state
        return max(1, max(0, int(eng.reaction_delay))
                   + max(0, int(eng.attack_cooldown)) + 1)

    def _wave_shot_capacity(self, units: list[Unit],
                            wave_length: int) -> dict[str, int]:
        """一个波次内每个单位大致能打出的发数。"""
        result: dict[str, int] = {}
        for unit in units:
            shots = max(1, int(wave_length) // self._shot_cycle(unit))
            result[unit.id] = shots
        return result
