"""时间协调（ETA / TOT / 火力门）单元测试。

这些是 HTCS 时间维的纯函数：不修改任何状态，因此可以直接用构造出来的
Unit 对象断言数值。
"""

from __future__ import annotations

import pytest

from core.time_coordination import (FirePlan, FireWindow, estimate_eta,
                                    estimate_eta_interval, plan_tot,
                                    staging_standoff)
from core.units import Unit


def _unit(uid="r1", x=100.0, y=100.0, *, attack_range=100.0, speed=5.0,
          reaction_delay=5):
    return Unit(id=uid, name=uid, team="red", x=x, y=y, domain="air",
                unit_type="strike_drone", hp=100, max_hp=100, speed=speed,
                detect_range=200, attack_range=attack_range,
                attack_power=10, ammo=5, reaction_delay=reaction_delay,
                attack_cooldown=0)


def _target(x=100.0, y=100.0):
    return _unit("t1", x, y)


# ── estimate_eta ────────────────────────────────────────────────
def test_eta_is_zero_inside_attack_range():
    unit = _unit(reaction_delay=0)
    assert estimate_eta(unit, _target(150, 100)) == 0


def test_eta_exactly_at_attack_range_is_zero():
    unit = _unit(attack_range=100.0, reaction_delay=0)
    assert estimate_eta(unit, _target(200, 100)) == 0


def test_eta_counts_reaction_delay_while_searching():
    unit = _unit(reaction_delay=5)
    assert unit.engagement_state.phase.name == "SEARCH"
    assert estimate_eta(unit, _target(150, 100)) == 5


def test_eta_can_skip_reaction_delay():
    unit = _unit(reaction_delay=5)
    assert estimate_eta(unit, _target(150, 100),
                        include_reaction=False) == 0


def test_eta_ignores_reaction_when_already_engaged():
    unit = _unit(reaction_delay=5)
    unit.engagement_state.on_target_spotted("t1")
    assert unit.engagement_state.phase.name == "REACTING"
    assert estimate_eta(unit, _target(150, 100)) == 0


def test_eta_travel_uses_standoff_ratio():
    # 距离 500、射程 100、待机距离 85 → 需走 415 像素 / 5 = 83 步
    unit = _unit(attack_range=100.0, speed=5.0, reaction_delay=5)
    assert estimate_eta(unit, _target(600, 100)) == 83 + 5


def test_eta_travel_scales_with_speed():
    fast = _unit(speed=10.0, reaction_delay=0)
    slow = _unit(speed=5.0, reaction_delay=0)
    target = _target(600, 100)
    assert estimate_eta(fast, target) == pytest.approx(42, abs=1)
    assert estimate_eta(slow, target) > estimate_eta(fast, target)


def test_eta_returns_horizon_cap_for_immobile_unit():
    unit = _unit(speed=0.0, attack_range=10.0)
    assert estimate_eta(unit, _target(600, 100)) == 999


def test_eta_is_never_negative():
    unit = _unit(reaction_delay=0)
    assert estimate_eta(unit, _target()) >= 0


def test_eta_uses_terrain_adjusted_speed_when_battlefield_given():
    from core.battlefield import Battlefield

    field = Battlefield(800, 600)
    unit = _unit(speed=5.0, reaction_delay=0)
    target = _target(600, 100)
    # 无地形时二者相同（战场无遮挡），只是验证参数路径可调用
    assert estimate_eta(unit, target, field) == \
        estimate_eta(unit, target, None)


# ── estimate_eta_interval ───────────────────────────────────────
def _ground_unit(uid="g1", x=100.0, y=300.0, *, terrain_effects=None):
    return Unit(id=uid, name=uid, team="red", x=x, y=y, domain="ground",
                unit_type="ground_vehicle", hp=100, max_hp=100, speed=5.0,
                detect_range=200, attack_range=100.0, attack_power=10,
                ammo=5, reaction_delay=0, attack_cooldown=0,
                terrain_effects=terrain_effects or {})


def _terrain_field(obstacle_type="mountain"):
    from core.battlefield import Battlefield, Obstacle

    return Battlefield(800, 600, obstacles=[
        Obstacle(300, 250, 200, 100, name="ridge", type=obstacle_type)])


def test_eta_interval_nominal_matches_estimate_eta():
    unit = _unit(reaction_delay=5)
    target = _target(600, 100)
    estimate = estimate_eta_interval(unit, target)
    assert estimate.nominal == estimate_eta(unit, target)
    assert estimate.upper >= estimate.nominal


def test_eta_interval_counts_terrain_slowdown_along_the_path():
    # 出发点在平地（速度 5），路径中段穿过山地（速度 2.5）。旧的点估计
    # 只用出发地速度，得到 103 步；上界按分段速度累加应显著更大。
    unit = _ground_unit(terrain_effects={
        "mountain": {"speed_factor": 0.5}})
    target = _target(700, 300)
    estimate = estimate_eta_interval(unit, target, _terrain_field())
    assert estimate.nominal == 103
    assert estimate.upper > estimate.nominal
    assert estimate.upper >= 140


def test_eta_interval_adds_detour_for_impassable_obstacle():
    # 没有该地形通行能力：地面单位必须绕行，附加路程应抬高上界。
    unit = _ground_unit()
    target = _target(700, 300)
    field = _terrain_field("building")
    estimate = estimate_eta_interval(unit, target, field)
    assert estimate.upper > estimate.nominal


def test_eta_interval_accounts_for_target_motion():
    unit = _ground_unit(terrain_effects={
        "mountain": {"speed_factor": 0.5}})
    target = _target(700, 300)
    field = _terrain_field()
    static = estimate_eta_interval(unit, target, field)
    moving = estimate_eta_interval(unit, target, field, target_speed=3.0)
    assert moving.upper > static.upper


def test_eta_interval_inside_attack_range_is_zero():
    unit = _unit(reaction_delay=0)
    estimate = estimate_eta_interval(unit, _target(150, 100))
    assert estimate.nominal == 0
    assert estimate.upper == 0


# ── plan_tot ────────────────────────────────────────────────────
def test_tot_is_latest_eta_from_now():
    assert plan_tot(10, [3, 5], 6) == 15


def test_tot_waits_at_least_one_step():
    assert plan_tot(10, [0], 6) == 11
    assert plan_tot(10, [], 6) == 11


def test_tot_is_capped_by_the_explicit_horizon():
    # 第三参数是时间视野而不是波次长度；超出视野的 ETA 才被截断。
    assert plan_tot(10, [40], 6) == 16


def test_tot_is_not_capped_by_wave_length_when_horizon_is_larger():
    # 慢速单位 40 步的 ETA 在 60 步视野内应得到真实 TOT，而不是被
    # 6 步的波次长度提前截断。
    assert plan_tot(10, [40], 60) == 50
    assert plan_tot(10, [61], 60) == 70


def test_tot_negative_etas_are_clamped():
    assert plan_tot(10, [-5], 6) == 11


def test_tot_uses_maximum_of_mixed_etas():
    assert plan_tot(20, [1, 4, 2], 6) == 24


# ── staging_standoff ────────────────────────────────────────────
def test_staging_standoff_is_range_times_ratio():
    assert staging_standoff(_unit(attack_range=100.0), 1.15) == pytest.approx(115.0)


def test_staging_standoff_has_a_24_pixel_floor():
    assert staging_standoff(_unit(attack_range=10.0), 1.15) == 24.0


# ── FireWindow ──────────────────────────────────────────────────
def test_fire_window_bounds():
    window = FireWindow(tot=10, tolerance=1, late=3)
    assert window.window_start == 9
    assert window.window_end == 10
    assert window.late_until == 13


def test_fire_window_permits_only_inside_the_window():
    window = FireWindow(tot=10, tolerance=1, late=3)
    assert window.permits(8) is False
    assert window.permits(9) is True
    assert window.permits(10) is True
    assert window.permits(11) is True
    assert window.permits(13) is True
    assert window.permits(14) is False


def test_fire_window_flags_early_and_late():
    window = FireWindow(tot=10, tolerance=1, late=3)
    assert window.is_early(8) is True
    assert window.is_early(9) is False
    assert window.is_late(13) is False
    assert window.is_late(14) is True
    assert window.expired(13) is False
    assert window.expired(14) is True


def test_fire_window_start_never_goes_negative():
    assert FireWindow(tot=0, tolerance=5, late=0).window_start == 0


def test_fire_window_zero_tolerance_only_allows_tot():
    window = FireWindow(tot=7, tolerance=0, late=0)
    assert [step for step in range(5, 10) if window.permits(step)] == [7]


# ── FirePlan ────────────────────────────────────────────────────
def test_fire_plan_delegates_to_its_window():
    plan = FirePlan(task_id="task-1", target_id="t1", wave=2, role="strike",
                    window=FireWindow(tot=12, tolerance=1, late=2))
    assert plan.tot == 12
    assert plan.window_start == 11
    assert plan.late_until == 14
    assert plan.permits(11) is True
    assert plan.permits(15) is False
    assert plan.is_early(10) is True
