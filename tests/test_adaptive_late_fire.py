"""自适应迟到策略（late_fire_policy="adaptive"）测试。

覆盖三条核心路径：

- 不可行计划挂起：不设停火保持、不触发再攻击；
- 可赶到计划有界再定时：整任务平移并同步 BDA 窗口；
- 火力纪律/已覆盖分类：纪律挡住时顺延，账本已覆盖时静默消耗。

沿用 ``test_htcs_integration`` 的固定命中/可见性构造方式，断言只依赖
确定性逻辑。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from config import STATUS_EVADE
from core.battlefield import Battlefield
from core.damage_ledger import DamageLedger
from core.engagement import EngagementPhase
from core.simulator import Simulator
from core.time_coordination import FirePlan, FireWindow
from core.unit_config_loader import get_cooperative_assignment_config
from core.units import GroundVehicle, StrikeDrone


def _config(**htcs_overrides):
    config = deepcopy(get_cooperative_assignment_config())
    config["mode"] = "htcs"
    config["htcs"]["late_fire_policy"] = "adaptive"
    config["htcs"].update(htcs_overrides)
    return config


def _drone(uid="r1", x=300.0, y=300.0):
    return StrikeDrone(id=uid, name=uid, team="red", x=x, y=y, speed=0,
                       ammo=7, reaction_delay=0, attack_cooldown=0)


def _target(uid="b1", x=400.0, hp=500):
    return GroundVehicle(id=uid, name=uid, team="blue", x=x, y=300.0,
                         speed=0, hp=hp, max_hp=hp, reaction_delay=5,
                         attack_cooldown=5)


def _sim(units, **htcs_overrides):
    return Simulator(Battlefield(800, 600), units,
                     cooperative_config=_config(**htcs_overrides))


def _events(simulator, name):
    return [row for row in simulator.records if row.get("event") == name]


def _expire_head(simulator, unit_id="r1"):
    """把队首计划改成早已过期，返回（计划, 所属任务）。"""
    plans = simulator.fire_plans["red"][unit_id]
    plans[0] = replace(
        plans[0], window=FireWindow(tot=0, tolerance=0, late=0))
    task = simulator.assignments["red"].tasks[plans[0].task_id]
    return plans[0], task


def _head(simulator, unit_id="r1"):
    unit = simulator._entity(unit_id)
    target = simulator._entity("b1")
    return simulator._htcs_head_plan(unit, {target.id})


# ── 不可行：挂起，不设保持、不转再攻击 ──────────────────────────
def test_infeasible_expired_plan_is_deferred_without_hold():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_horizon_steps=5)
    simulator.step()
    plan, task = _expire_head(simulator)
    target.x = 600.0          # 射程外且速度 0，ETA 达到视野上限
    red.speed = 0.0
    red.engagement_state.phase = EngagementPhase.ATTACK  # 无剩余反应/冷却

    assert _head(simulator) is None
    assert task.state == "deferred"
    assert task.deferred is True
    assert ("r1", "b1") not in simulator._htcs_target_hold
    assert not simulator.fire_plans["red"]["r1"]
    deferred = _events(simulator, "fire_window_deferred")
    assert deferred and deferred[0]["reason"] == "infeasible"
    assert not _events(simulator, "fire_window_missed")

    simulator._bda_phase()
    assert not _events(simulator, "reattack_required")


# ── 可赶到：有界再定时 ──────────────────────────────────────────
def test_deliverable_expired_plan_is_retimed_once():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=1,
                     late_fire_retime_horizon_steps=60)
    simulator.step()
    plan, task = _expire_head(simulator)
    old_task_tot = task.tot_step
    old_task_late = task.late_until
    target.x = 600.0
    red.speed = 5.0
    red.engagement_state.phase = EngagementPhase.ATTACK  # 无剩余反应/冷却

    head = _head(simulator)
    assert head is not None
    assert head.task_id == plan.task_id
    assert head.tot > plan.tot
    assert task.retimes == 1
    delta = head.tot - plan.tot
    assert task.tot_step == old_task_tot + delta
    assert task.late_until == old_task_late + delta
    assert ("r1", "b1") not in simulator._htcs_target_hold
    retimed = _events(simulator, "fire_window_retimed")
    assert retimed and retimed[0]["reason"] == "deliverable"
    assert retimed[0]["old_tot"] == plan.tot
    assert retimed[0]["new_tot"] == head.tot


def test_retime_budget_is_bounded():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=0,
                     late_fire_retime_horizon_steps=60)
    simulator.step()
    plan, task = _expire_head(simulator)
    target.x = 600.0
    red.speed = 5.0
    red.engagement_state.phase = EngagementPhase.ATTACK  # 无剩余反应/冷却

    # 再定时预算为 0：过期计划按迟到拦截，后续未过期计划仍在队首。
    _head(simulator)
    assert task.retimes == 0
    missed = _events(simulator, "fire_window_missed")
    assert missed and missed[0]["reason"] == "deliverable"
    assert simulator._htcs_target_hold[("r1", "b1")] > simulator.time_step


# ── 纪律/覆盖分类 ──────────────────────────────────────────────
def test_discipline_expired_plan_is_retimed_by_hold_window():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=1,
                     late_fire_hold_steps=6)
    simulator.step()
    plan, task = _expire_head(simulator)
    # 预约到“还差 10 点血”：剩余需求 > 0.5（未覆盖），但加上本发会过杀。
    simulator.damage_ledger.reserve("r2", "b1", target.hp - 10)

    head = _head(simulator)
    assert head is not None
    assert task.retimes == 1
    assert head.tot == simulator.time_step + 6
    assert ("r1", "b1") not in simulator._htcs_target_hold
    retimed = _events(simulator, "fire_window_retimed")
    assert retimed and retimed[0]["reason"] == "discipline"


def test_reacting_unit_plan_is_retimed_by_remaining_reaction():
    # 已进入射程但仍在反应期：不是“没赶到”，应按剩余反应时间顺延，
    # 而不是判迟到并停火。
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=1)
    simulator.step()
    _expire_head(simulator)
    eng = red.engagement_state
    eng.phase = EngagementPhase.REACTING
    eng.reaction_delay = 10
    eng.reaction_progress = 3
    eng.current_target_id = "b1"

    head = _head(simulator)
    assert head is not None
    assert head.tot == simulator.time_step + 8   # 剩余反应 7 + 1 步推进
    retimed = _events(simulator, "fire_window_retimed")
    assert retimed and retimed[0]["reason"] == "temporary"
    assert ("r1", "b1") not in simulator._htcs_target_hold


def test_discipline_without_retime_budget_still_misses():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=0)
    simulator.step()
    _expire_head(simulator)
    simulator.damage_ledger.reserve("r2", "b1", target.hp - 10)

    _head(simulator)
    missed = _events(simulator, "fire_window_missed")
    assert missed and missed[0]["reason"] == "discipline"
    assert simulator._htcs_target_hold[("r1", "b1")] > simulator.time_step


def test_covered_expired_plan_is_consumed_without_hold():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.step()
    plan, task = _expire_head(simulator)
    # 预约发生在当前步，BDA 的过期残留清理不应把它当作历史遗留释放。
    simulator.damage_ledger.reserve("r2", "b1", 1000, simulator.time_step)

    assert _head(simulator) is None
    assert not simulator.fire_plans["red"]["r1"]
    assert ("r1", "b1") not in simulator._htcs_target_hold
    assert task.state != "deferred"
    assert not _events(simulator, "fire_window_missed")

    task.late_until = -1          # 窗口已过，BDA 应直接判定“已覆盖”
    simulator._bda_phase()
    assert task.state == "done"


# ── 已到位但没执行：仍是迟到 ────────────────────────────────────
def test_reached_but_unexecuted_plan_is_still_late():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.step()
    plan, _task = _expire_head(simulator)
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.engagement_state.current_target_id = "b1"

    _head(simulator)
    missed = _events(simulator, "fire_window_missed")
    assert missed and missed[0]["reason"] == "late"
    assert missed[0]["reached"] is True
    assert simulator._htcs_target_hold[("r1", "b1")] > simulator.time_step
    assert all(item.tot != plan.tot for item in
               simulator.fire_plans["red"]["r1"])


# ── 每计划动态迟到宽限 ──────────────────────────────────────────
def test_plan_late_window_expands_with_eta_upper_bound():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_late_max_steps=12,
                     plan_persistence=False)
    simulator.step()
    task = next(iter(simulator.assignments["red"].tasks.values()))
    task.eta_by_unit["r1"] = 10
    task.eta_upper_by_unit["r1"] = 18
    simulator._install_fire_plans("red", simulator.assignments["red"])

    plans = simulator.fire_plans["red"]["r1"]
    assert plans
    assert all(plan.window.late == 11 for plan in plans)


def test_plan_late_window_is_capped():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_late_max_steps=5,
                     plan_persistence=False)
    simulator.step()
    task = next(iter(simulator.assignments["red"].tasks.values()))
    task.eta_by_unit["r1"] = 1
    task.eta_upper_by_unit["r1"] = 40
    simulator._install_fire_plans("red", simulator.assignments["red"])

    plans = simulator.fire_plans["red"]["r1"]
    assert plans
    assert all(plan.window.late == 5 for plan in plans)


# ── 任务级延期预算：所有再定时/顺延共用 ────────────────────────
def _force_temporary(simulator):
    """让队首计划因规避而暂时打不出去。"""
    red = simulator._entity("r1")
    red.status = STATUS_EVADE
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.engagement_state.current_target_id = "b1"


def test_temporary_retimes_share_one_task_delay_budget():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=5,
                     late_fire_task_delay_max_steps=6,
                     late_fire_hold_steps=3,
                     late_fire_retime_horizon_steps=60)
    simulator.step()
    plan, task = _expire_head(simulator)
    _force_temporary(simulator)

    head = _head(simulator)
    assert head is not None
    budget = simulator._htcs_task_budgets["red"][plan.task_id]
    first = budget.deferred_steps
    assert 0 < first <= 6

    simulator.time_step = head.tot + head.window.late + 1
    head = _head(simulator)
    assert head is not None
    second = budget.deferred_steps
    assert first < second <= 6

    simulator.time_step = head.tot + head.window.late + 1
    assert _head(simulator) is None
    # 时间预算先耗尽：即使次数上限仍有余额，也不能再延期。
    assert budget.retimes < 5
    assert budget.deferred_steps == 6
    assert budget.remaining_steps == 0
    assert task.deferred is True
    assert task.deferred_steps == 6
    deferred = _events(simulator, "fire_window_deferred")
    assert deferred and deferred[0]["reason"] == "temporary"


def test_retime_count_limit_is_independent_of_time_budget():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=1,
                     late_fire_task_delay_max_steps=60,
                     late_fire_hold_steps=3)
    simulator.step()
    plan, task = _expire_head(simulator)
    _force_temporary(simulator)

    head = _head(simulator)
    assert head is not None
    budget = simulator._htcs_task_budgets["red"][plan.task_id]
    assert budget.retimes == 1
    assert budget.remaining_steps > 0

    simulator.time_step = head.tot + head.window.late + 1
    assert _head(simulator) is None
    # 次数先耗尽：时间预算仍充足也不能再延期。
    assert budget.retimes == 1
    assert budget.remaining_steps > 0
    assert task.deferred is True


def test_zero_task_delay_budget_cannot_retime():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=5,
                     late_fire_task_delay_max_steps=0,
                     late_fire_hold_steps=3)
    simulator.step()
    plan, task = _expire_head(simulator)
    _force_temporary(simulator)

    assert _head(simulator) is None
    budget = simulator._htcs_task_budgets["red"][plan.task_id]
    assert budget.retimes == 0
    assert budget.deferred_steps == 0
    assert task.deferred is True


def test_replan_does_not_reset_task_delay_budget():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=5,
                     late_fire_task_delay_max_steps=60,
                     late_fire_hold_steps=3)
    simulator.step()
    plan, task = _expire_head(simulator)
    _force_temporary(simulator)

    assert _head(simulator) is not None
    budget = simulator._htcs_task_budgets["red"][plan.task_id]
    saved = (budget.retimes, budget.deferred_steps, budget.original_tot)
    assert saved[0] == 1 and saved[1] > 0

    simulator._install_fire_plans("red", simulator.assignments["red"])
    same = simulator._htcs_task_budgets["red"][plan.task_id]
    assert same is budget
    assert (same.retimes, same.deferred_steps,
            same.original_tot) == saved

    # 第二次再定时继续扣同一本账，而不是重新获得完整额度。
    simulator.time_step = 30
    assert _head(simulator) is not None
    assert budget.retimes == 2
    assert budget.deferred_steps > saved[1]
    assert budget.original_tot == saved[2]


# ── 平移范围：所有计划同步，且不侵占后续任务 ────────────────────
def test_retime_syncs_retired_task_and_every_plan():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=2)
    simulator.step()
    plan, task = _expire_head(simulator)
    task_id = plan.task_id
    result = simulator.assignments["red"]
    result.tasks.pop(task_id)
    simulator._htcs_retired["red"].append(task)
    old_tot, old_start, old_late = (
        task.tot_step, task.window_start, task.late_until)
    before = {item.tot for item in simulator.fire_plans["red"]["r1"]
              if item.task_id == task_id}
    target.x = 600.0
    red.speed = 5.0
    red.engagement_state.phase = EngagementPhase.ATTACK

    head = _head(simulator)
    assert head is not None
    delta = head.tot - plan.tot
    assert delta > 0
    assert task in simulator._htcs_retired["red"]
    assert task.tot_step == old_tot + delta
    assert task.window_start == old_start + delta
    assert task.late_until == old_late + delta
    after = {item.tot for item in simulator.fire_plans["red"]["r1"]
             if item.task_id == task_id}
    assert after == {tot + delta for tot in before}
    assert result.attack_steps["r1"] == head.tot


def test_shift_is_capped_by_later_task_window():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=5,
                     late_fire_task_delay_max_steps=60)
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    plan = plans[0]
    last = [item for item in plans if item.task_id == plan.task_id][-1]
    next_tot = int(last.late_until) + 11
    plans.append(FirePlan(
        task_id="b1:sead:99", target_id="b1", wave=99, role="sead",
        window=FireWindow(tot=next_tot, tolerance=0, late=0)))
    budget = simulator._htcs_budget("red", plan)

    applied = simulator._htcs_shift_task(
        red, plan, 50, reason="temporary", eta_nominal=0, eta_upper=0)
    # 与后续任务之间只剩 10 步空隙，不能按 50 步平移。
    assert applied == min(50, budget.remaining_steps, 10)
    assert budget.deferred_steps == applied
    assert plans[-1].task_id == "b1:sead:99"
    assert plans[-1].tot == next_tot


def test_shift_refused_when_later_task_starts_immediately():
    red, target = _drone(), _target()
    simulator = _sim([red, target], late_fire_retime_max=5,
                     late_fire_task_delay_max_steps=60)
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    plan = plans[0]
    last = [item for item in plans if item.task_id == plan.task_id][-1]
    next_tot = int(last.late_until) + 1
    plans.append(FirePlan(
        task_id="b1:sead:99", target_id="b1", wave=99, role="sead",
        window=FireWindow(tot=next_tot, tolerance=0, late=0)))
    budget = simulator._htcs_budget("red", plan)

    assert simulator._htcs_shift_task(
        red, plan, 10, reason="temporary",
        eta_nominal=0, eta_upper=0) == 0
    assert budget.retimes == 0
    assert budget.deferred_steps == 0
    assert not _events(simulator, "fire_window_retimed")


# ── reached 只表示历史到达，不能替代当前条件复检 ────────────────
def test_historical_reached_does_not_authorize_fire_out_of_range():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    plans[0] = replace(plans[0], window=FireWindow(
        tot=simulator.time_step, tolerance=1, late=3))
    plan = plans[0]
    plan.reached = True          # 曾经进入过射程
    target.x = 600.0             # 目标已离开射程
    red.speed = 0.0
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.engagement_state.current_target_id = "b1"
    ammo = red.ammo
    simulator.combat.clear_intents()

    simulator._htcs_attack_unit(red)
    assert plan.reached is True
    assert not [intent for intent in simulator.combat._intents
                if intent.attacker_id == red.id]
    assert red.ammo == ammo
    assert simulator.fire_plans["red"]["r1"][0] is plan


def test_out_of_range_expired_plan_is_infeasible_not_late():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.step()
    plan, task = _expire_head(simulator)
    plan.reached = True          # 历史到达过，但当前已不在射程
    target.x = 600.0
    red.speed = 0.0
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.engagement_state.current_target_id = "b1"

    assert _head(simulator) is None
    assert task.deferred is True
    deferred = _events(simulator, "fire_window_deferred")
    assert deferred and deferred[0]["reason"] == "infeasible"
    assert deferred[0]["ever_in_range"] is True
    assert deferred[0]["in_range_now"] is False
    assert not _events(simulator, "fire_window_missed")


# ── 取消/挂起释放未执行任务的预约 ──────────────────────────────
def test_release_task_only_removes_matching_unsettled_reservations():
    ledger = DamageLedger()
    ledger.reserve("r1", "b1", 40, step=1, task_id="t1")
    ledger.reserve("r1", "b1", 30, step=1, task_id="t2")
    ledger.reserve("r1", "b1", 20, step=2, task_id="t1")

    assert ledger.release_task("t1", before_step=2) == 40
    assert ledger.reserved("b1") == 50
    assert ledger.release_task("t1", before_step=2) == 0

    # 结算最近一发 t1 预约，剩余 t2 不受影响；applied 只累计实际伤害。
    assert ledger.settle("r1", "b1", 5) == 20
    assert ledger.reserved("b1") == 30
    assert ledger.reserved_by("r1", "b1") == 30
    assert ledger.applied("b1") == 5


def test_cancel_task_releases_only_that_tasks_old_reservations():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.step()
    plan = simulator.fire_plans["red"]["r1"][0]
    simulator.damage_ledger.reserve(
        "r1", "b1", 25, step=simulator.time_step - 1,
        task_id=plan.task_id)
    simulator.damage_ledger.reserve(
        "r9", "b1", 15, step=simulator.time_step,
        task_id="other:strike:0")

    assert simulator.damage_ledger.reserved("b1") == 40
    simulator._htcs_cancel_task_plans(red, plan)
    assert simulator.damage_ledger.reserved("b1") == 15
    # 重复取消不会再次释放，也不会影响其他任务的本步预约。
    simulator._htcs_cancel_task_plans(red, plan)
    assert simulator.damage_ledger.reserved("b1") == 15
    assert not [item for item in simulator.fire_plans["red"]["r1"]
                if item.task_id == plan.task_id]
