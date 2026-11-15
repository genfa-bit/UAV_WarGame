"""HTCS 打击规划器（StrikePlanner）单元测试。

覆盖：战法选择与加成、弹药预留、时间折扣与可行性、任务束、SEAD 先导、
TOT/火力窗口、单位就绪时间。全部使用确定性构造的单位，不跑 Simulator。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.cooperative_allocator import AssignmentResult
from core.engagement import EngagementPhase
from core.strike_planner import (StrikePlanner, StrikeTask, choose_doctrine,
                                 doctrine_ammo_reserve, doctrine_priority_bonus)
from core.target_pool import TargetSighting
from core.unit_config_loader import get_cooperative_assignment_config
from core.units import BaseUnit, CommandNode, StrikeDrone


def _config(**htcs_overrides):
    config = deepcopy(get_cooperative_assignment_config())
    config["mode"] = "htcs"
    config["htcs"].update(htcs_overrides)
    return config


def _planner(**htcs_overrides):
    return StrikePlanner(_config(**htcs_overrides))


def _drone(uid="r1", team="red", x=100.0, y=300.0, *, ammo=20, power=18,
           attack_range=135.0, speed=3.5, reaction_delay=0,
           attack_cooldown=0, hp=None):
    extra = {} if hp is None else {"hp": hp}
    return StrikeDrone(id=uid, name=uid, team=team, x=x, y=y, ammo=ammo,
                       attack_power=power, attack_range=attack_range,
                       speed=speed, reaction_delay=reaction_delay,
                       attack_cooldown=attack_cooldown, **extra)


def _base(uid="b1", x=450.0, y=300.0, hp=300):
    return BaseUnit(id=uid, name=uid, team="blue", x=x, y=y, hp=hp)


def _node(uid="c1", x=450.0, y=300.0):
    return CommandNode(id=uid, name=uid, team="blue", x=x, y=y)


def _sighting(target, step=0):
    return TargetSighting(target=target, last_seen_step=step, available_step=0)


def _balanced_context(**extra):
    context = {"own_strength": 10.0, "enemy_strength": 10.0}
    context.update(extra)
    return context


# ── 战法选择 ────────────────────────────────────────────────────
def test_adaptive_doctrine_decapitates_when_advantaged_and_node_visible():
    targets = [_node()]
    assert choose_doctrine(20, 10, targets, {"doctrine": "adaptive"}) == \
        "decapitation"


def test_adaptive_doctrine_pressures_base_without_command_node():
    assert choose_doctrine(20, 10, [_base()], {"doctrine": "adaptive"}) == \
        "base_pressure"


def test_adaptive_doctrine_attrits_when_disadvantaged():
    assert choose_doctrine(5, 20, [_base()], {"doctrine": "adaptive"}) == \
        "attrition"


def test_adaptive_doctrine_stays_balanced_at_parity():
    assert choose_doctrine(10, 10, [_base()], {"doctrine": "adaptive"}) == \
        "balanced"


def test_fixed_doctrine_overrides_situation():
    config = {"doctrine": "attrition"}
    assert choose_doctrine(100, 1, [], config) == "attrition"


def test_doctrine_thresholds_are_configurable():
    config = {"doctrine": "adaptive", "doctrine_advantage_ratio": 1.05,
              "doctrine_disadvantage_ratio": 0.95}
    assert choose_doctrine(11, 10, [_base()], config) == "base_pressure"


def test_enemy_strength_of_zero_does_not_divide_by_zero():
    assert choose_doctrine(10, 0, [_base()], {"doctrine": "adaptive"}) == \
        "base_pressure"


# ── 战法加成 ────────────────────────────────────────────────────
def test_decapitation_favours_command_node_then_missile():
    node = _node()
    drone = _drone("t2", team="blue", ammo=5, power=10)
    assert doctrine_priority_bonus(node, "decapitation") == pytest.approx(0.35)
    assert doctrine_priority_bonus(drone, "decapitation") == 0.0


def test_base_pressure_only_boosts_base():
    assert doctrine_priority_bonus(_base(), "base_pressure") == \
        pytest.approx(0.30)
    assert doctrine_priority_bonus(_drone("t2", team="blue"), "base_pressure") \
        == 0.0


def test_attrition_prefers_damaged_targets_and_penalises_base():
    damaged = _drone("t2", team="blue", ammo=5, power=10)
    damaged.hp = 20
    healthy = _drone("t3", team="blue", ammo=5, power=10)
    assert doctrine_priority_bonus(damaged, "attrition") > \
        doctrine_priority_bonus(healthy, "attrition")
    assert doctrine_priority_bonus(_base(), "attrition") < 0.0


def test_balanced_doctrine_has_no_bonus():
    assert doctrine_priority_bonus(_base(), "balanced") == 0.0


# ── 弹药预留 ────────────────────────────────────────────────────
def test_attrition_reserves_at_least_35_percent():
    assert doctrine_ammo_reserve("attrition", {}) == pytest.approx(0.35)


def test_base_pressure_keeps_reserve_low():
    assert doctrine_ammo_reserve("base_pressure", {"ammo_reserve_ratio": 0.2}) \
        == pytest.approx(0.10)


def test_balanced_uses_configured_reserve():
    assert doctrine_ammo_reserve("balanced", {"ammo_reserve_ratio": 0.25}) == \
        pytest.approx(0.25)


# ── 单位就绪与射击周期 ──────────────────────────────────────────
def test_ready_step_is_now_for_idle_unit():
    unit = _drone(reaction_delay=10, attack_cooldown=4)
    assert StrikePlanner._ready_step(unit, 50) == 50


def test_ready_step_counts_remaining_reaction():
    unit = _drone(reaction_delay=10, attack_cooldown=4)
    unit.engagement_state.phase = EngagementPhase.REACTING
    unit.engagement_state.reaction_progress = 3
    assert StrikePlanner._ready_step(unit, 50) == 50 + 7 + 1


def test_ready_step_counts_cooldown_then_reaction():
    unit = _drone(reaction_delay=10, attack_cooldown=4)
    unit.engagement_state.phase = EngagementPhase.COOLDOWN
    unit.engagement_state.cooldown_progress = 1
    assert StrikePlanner._ready_step(unit, 50) == 50 + 3 + 10 + 1


def test_shot_cycle_is_reaction_plus_cooldown_plus_one():
    assert StrikePlanner._shot_cycle(_drone(reaction_delay=10,
                                            attack_cooldown=4)) == 15


def test_shot_cycle_never_below_one():
    assert StrikePlanner._shot_cycle(_drone(reaction_delay=0,
                                            attack_cooldown=0)) == 1


def test_wave_shot_capacity_uses_cycle():
    planner = _planner(wave_length_steps=6)
    slow = _drone(reaction_delay=10, attack_cooldown=4)   # cycle 15 → 1 发
    fast = _drone("r2", reaction_delay=0, attack_cooldown=0)  # cycle 1 → 6 发
    capacity = planner._wave_shot_capacity([slow, fast], 6)
    assert capacity == {"r1": 1, "r2": 6}


def test_shot_damage_is_positive_and_scales_with_power():
    planner = _planner()
    target = _drone("t1", team="blue")
    weak = _drone("r1", power=10)
    strong = _drone("r2", power=30)
    assert planner._shot_damage(weak, target, None) > 0
    assert planner._shot_damage(strong, target, None) > \
        planner._shot_damage(weak, target, None)


# ── plan() 基本结构 ─────────────────────────────────────────────
def test_plan_returns_empty_result_without_targets():
    planner = _planner()
    result = planner.plan([_drone()], None, 0)
    assert result.tasks == {}
    assert result.bundles == {}
    assert result.updated_step == 0


def test_plan_creates_one_task_with_member_and_bundle():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert task.members == ["r1"]
    assert task.shots["r1"] >= 1
    assert result.assignments["r1"] == "t1"
    assert result.bundles["r1"] == ["t1:strike:0"]
    assert result.doctrine == "balanced"


def test_plan_task_has_tot_and_fire_window():
    planner = _planner(tot_tolerance_steps=1, tot_late_steps=3)
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 4, context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert task.window_start == max(4, task.tot_step - 1)
    assert task.late_until == task.tot_step + 3
    assert result.attack_steps["r1"] == task.tot_step


def test_plan_task_records_planned_damage_and_applied_baseline():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert task.planned_damage > 0
    assert task.applied_at_plan == 0.0
    assert result.ledger_plan["t1"] == pytest.approx(task.planned_damage)


def test_plan_marks_task_ready_when_damage_goal_is_met():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0, hp=1)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert task.state == "ready"
    assert task.planned_damage >= 0.9 * task.required_damage


def test_plan_marks_task_understrength_when_capacity_is_capped():
    planner = _planner()
    planner.config["max_assignments_per_target"] = 1
    units = [_drone("r1", x=100.0), _drone("r2", x=110.0),
             _drone("r3", x=120.0)]
    blue = _drone("t1", team="blue", x=250.0, hp=500)
    result = planner.plan(units, [_sighting(blue)], 0,
                          context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert len(task.members) == 1
    assert task.state == "understrength"


def test_plan_preserves_assignment_since_for_unchanged_target():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    previous = AssignmentResult(assignments={"r1": "t1"},
                                assignment_since={"r1": 3})
    result = planner.plan([red], [_sighting(blue, step=20)], 20,
                          previous=previous, context=_balanced_context())
    assert result.assignment_since["r1"] == 3


def test_plan_resets_assignment_since_for_new_target():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    previous = AssignmentResult(assignments={"r1": "other"},
                                assignment_since={"r1": 3})
    result = planner.plan([red], [_sighting(blue, step=20)], 20,
                          previous=previous, context=_balanced_context())
    assert result.assignment_since["r1"] == 20


# ── 时间折扣与可行性 ───────────────────────────────────────────
def test_near_target_orders_before_far_target():
    planner = _planner(wave_length_steps=6, planning_horizon_waves=3)
    red = _drone(x=100.0)
    near = _drone("tnear", team="blue", x=250.0)   # ETA ≈ 11
    far = _drone("tfar", team="blue", x=270.0)     # ETA ≈ 16
    result = planner.plan([red], [_sighting(near), _sighting(far)], 0,
                          context=_balanced_context())
    near_task = result.tasks["tnear:strike:0"]
    far_task = result.tasks["tfar:strike:0"]
    assert near_task.eta_best < far_task.eta_best
    assert near_task.effective_priority > far_task.effective_priority
    assert near_task.order < far_task.order
    assert result.bundles["r1"] == ["tnear:strike:0", "tfar:strike:0"]


def test_distant_but_reachable_target_is_still_tasked():
    planner = _planner(wave_length_steps=6, planning_horizon_waves=3)
    red = _drone(x=100.0)
    edge = _drone("tedge", team="blue", x=270.0)   # ETA ≈ 16 < 18
    result = planner.plan([red], [_sighting(edge)], 0,
                          context=_balanced_context())
    assert result.tasks["tedge:strike:0"].members == ["r1"]


def test_target_beyond_horizon_gets_no_members():
    planner = _planner(wave_length_steps=6, planning_horizon_waves=1)
    red = _drone(x=100.0)
    far = _drone("tfar", team="blue", x=300.0)     # ETA ≈ 24 > 6
    result = planner.plan([red], [_sighting(far)], 0,
                          context=_balanced_context())
    task = result.tasks["tfar:strike:0"]
    assert task.members == []
    assert task.state == "unassigned"
    assert result.bundles == {}


def test_time_discount_is_recorded_on_every_task():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert 0.0 < task.effective_priority < task.priority


# ── 任务束 ──────────────────────────────────────────────────────
def test_unit_can_hold_a_bundle_of_two_tasks():
    planner = _planner(bundle_size=2, wave_length_steps=6,
                       planning_horizon_waves=4)
    red = _drone(x=100.0)
    first = _drone("t1", team="blue", x=250.0)
    second = _drone("t2", team="blue", x=265.0)
    result = planner.plan([red], [_sighting(first), _sighting(second)], 0,
                          context=_balanced_context())
    assert len(result.bundles["r1"]) == 2
    assert result.assignments["r1"] == result.bundles["r1"][0].split(":")[0]


def test_bundle_size_one_limits_each_unit_to_a_single_task():
    planner = _planner(bundle_size=1)
    red = _drone(x=100.0)
    first = _drone("t1", team="blue", x=250.0)
    second = _drone("t2", team="blue", x=265.0)
    result = planner.plan([red], [_sighting(first), _sighting(second)], 0,
                          context=_balanced_context())
    assert len(result.bundles["r1"]) == 1


def test_second_task_in_bundle_starts_after_first_shooting_cycle():
    planner = _planner(bundle_size=2, planning_horizon_waves=4)
    red = _drone(x=100.0, reaction_delay=5, attack_cooldown=10)
    first = _drone("t1", team="blue", x=250.0)
    second = _drone("t2", team="blue", x=265.0)
    result = planner.plan([red], [_sighting(first), _sighting(second)], 0,
                          context=_balanced_context())
    tasks = [result.tasks[task_id] for task_id in result.bundles["r1"]]
    assert tasks[1].tot_step >= tasks[0].tot_step


def test_ammo_reserve_leaves_at_least_one_round():
    planner = _planner()
    red = _drone(x=100.0, ammo=1)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    task = result.tasks["t1:strike:0"]
    assert task.members == ["r1"]
    assert task.shots["r1"] == 1


def test_empty_ammo_unit_is_not_tasked():
    planner = _planner()
    red = _drone(x=100.0, ammo=0)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    # 没有可出价的单位时规划器直接返回空计划，不会生成无人任务。
    assert result.tasks == {}
    assert result.bundles == {}
    assert result.assignments == {}


# ── SEAD 先导 ───────────────────────────────────────────────────
def _sead_scene():
    red = _drone(x=330.0)                        # 距掩护兵力 ETA ≈ 16
    base = _base(x=450.0)                        # 距离 120，已在射程内
    defender = _drone("d1", team="blue", x=500.0)
    return red, base, defender


def test_sead_task_targets_the_defender_of_a_protected_base():
    planner = _planner(sead_enabled=True, sead_defense_radius=220.0)
    red, base, defender = _sead_scene()
    context = _balanced_context(enemy_units=[base, defender])
    result = planner.plan([red], [_sighting(base), _sighting(defender)], 0,
                          context=context)
    sead = result.tasks["d1:sead:0"]
    assert sead.role == "sead"
    assert sead.precedence == 0
    assert sead.order == 0


def test_sead_task_executes_before_the_base_attack():
    planner = _planner(sead_enabled=True)
    red, base, defender = _sead_scene()
    context = _balanced_context(enemy_units=[base, defender])
    result = planner.plan([red], [_sighting(base), _sighting(defender)], 0,
                          context=context)
    first_task = result.bundles["r1"][0]
    assert result.tasks[first_task].role == "sead"


def test_sead_required_damage_uses_the_effect_ratio():
    planner = _planner(sead_enabled=True, sead_effect_ratio=0.5)
    red, base, defender = _sead_scene()
    context = _balanced_context(enemy_units=[base, defender])
    result = planner.plan([red], [_sighting(base), _sighting(defender)], 0,
                          context=context)
    sead = result.tasks["d1:sead:0"]
    full = planner.allocator.effect_threshold(defender)
    assert sead.required_damage <= full * 0.5 + 1e-6
    assert sead.required_damage > 0


def test_sead_disabled_leaves_defender_untasked_as_sead():
    planner = _planner(sead_enabled=False)
    red, base, defender = _sead_scene()
    context = _balanced_context(enemy_units=[base, defender])
    result = planner.plan([red], [_sighting(base), _sighting(defender)], 0,
                          context=context)
    assert "d1:sead:0" not in result.tasks
    assert any(task.role == "strike" for task in result.tasks.values())


def test_sead_skips_defenders_outside_the_defense_radius():
    planner = _planner(sead_enabled=True, sead_defense_radius=10.0)
    red, base, defender = _sead_scene()
    context = _balanced_context(enemy_units=[base, defender])
    result = planner.plan([red], [_sighting(base), _sighting(defender)], 0,
                          context=context)
    assert "d1:sead:0" not in result.tasks


def test_base_target_gets_base_role_and_lower_precedence_priority():
    planner = _planner(sead_enabled=False)
    red, base, _defender = _sead_scene()
    result = planner.plan([red], [_sighting(base)], 0,
                          context=_balanced_context())
    task = result.tasks["b1:base:0"]
    assert task.role == "base"
    assert task.precedence == 2


# ── 再攻击与账本 ────────────────────────────────────────────────
def test_reattack_target_gets_reason_and_bonus_priority():
    from core.damage_ledger import DamageLedger

    planner = _planner(reattack_bonus=0.25)
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    plain = planner.plan([red], [_sighting(blue)], 0,
                         context=_balanced_context())
    ledger = DamageLedger()
    ledger.settle("gone", "t1", 40)
    result = planner.plan([red], [_sighting(blue)], 0,
                          context=_balanced_context(), ledger=ledger)
    task = result.tasks["t1:strike:0"]
    assert task.reason == "reattack"
    assert task.applied_at_plan == 40
    assert task.priority > plain.tasks["t1:strike:0"].priority


def test_task_dict_exposes_time_and_bundle_fields():
    planner = _planner()
    red = _drone(x=100.0)
    blue = _drone("t1", team="blue", x=250.0)
    result = planner.plan([red], [_sighting(blue)], 0, context=_balanced_context())
    payload = result.tasks["t1:strike:0"].to_dict()
    for key in ("task_id", "target_id", "wave", "precedence", "priority",
                "effective_priority", "eta_best", "order", "role", "reason",
                "required_damage", "planned_damage", "members", "shots",
                "tot_step", "window_start", "late_until", "state", "doctrine"):
        assert key in payload


def test_strike_task_defaults_are_safe():
    task = StrikeTask(task_id="t", target_id="x", target=_base(), wave=0,
                      precedence=1, priority=0.5, role="strike",
                      reason="strike", required_damage=10.0, tot_step=0,
                      window_start=0, late_until=0)
    assert task.members == []
    assert task.shots == {}
    assert task.state == "planned"
    assert task.effective_priority == 0.0
    assert task.assigned == []


def test_planner_reuses_allocator_scores():
    planner = _planner()
    assert planner.allocator.config is planner.config
