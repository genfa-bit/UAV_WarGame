"""测试按兵种配置的障碍物直线命中衰减与叠加。

配置位于 data/unit_config.json 的 obstacle_hit_factors：攻击直线每穿过
一个障碍物，就乘以攻击方兵种对该障碍物类型的倍率；多个障碍物依次相乘。
导弹发射车基本不受影响，无人机次之，无人战车受影响最严重。
"""

import warnings

import pytest

from core import unit_config_loader
from core.battlefield import Battlefield, Obstacle
from core.combat import calculate_hit_probability
from core.unit_config_loader import (
    clear_config_cache,
    get_obstacle_hit_factors,
)
from core.units import GroundVehicle, MissileVehicle, ScoutDrone, StrikeDrone


def _wall(x, obstacle_type="obstacle", width=10, height=200):
    return Obstacle(x=x, y=0, width=width, height=height, type=obstacle_type)


def _attacker(unit_class=GroundVehicle, x=20, y=50, **kwargs):
    defaults = dict(id="a", name="攻击者", team="red", x=x, y=y,
                    base_hit_prob=0.8, attack_range=400, speed=0)
    defaults.update(kwargs)
    return unit_class(**defaults)


def _target(x=300, y=50, **kwargs):
    defaults = dict(id="t", name="目标", team="blue", x=x, y=y, speed=0)
    defaults.update(kwargs)
    return ScoutDrone(**defaults)


def _hit(attacker, target, obstacles):
    terrain = Battlefield(400, 200, obstacles)
    baseline = calculate_hit_probability(
        attacker, target, Battlefield(400, 200))
    return baseline, calculate_hit_probability(attacker, target, terrain)


# ═══════════════════════════════════════════════════════════
#  配置读取
# ═══════════════════════════════════════════════════════════


def test_obstacle_hit_factors_loaded_per_unit():
    ground = get_obstacle_hit_factors("ground_vehicle")
    assert ground["obstacle"] == pytest.approx(0.30)
    assert ground["mountain"] == pytest.approx(0.30)
    assert ground["building"] == pytest.approx(0.25)
    assert ground["restricted"] == pytest.approx(0.30)
    assert get_obstacle_hit_factors("scout_drone")["mountain"] == pytest.approx(0.60)
    assert get_obstacle_hit_factors("strike_drone")["building"] == pytest.approx(0.52)
    assert get_obstacle_hit_factors("missile_vehicle")["mountain"] == pytest.approx(0.95)


def test_missile_vehicle_least_affected_drone_middle_ground_most():
    for obstacle_type in ("obstacle", "mountain", "building", "restricted"):
        missile = get_obstacle_hit_factors("missile_vehicle")[obstacle_type]
        scout = get_obstacle_hit_factors("scout_drone")[obstacle_type]
        strike = get_obstacle_hit_factors("strike_drone")[obstacle_type]
        ground = get_obstacle_hit_factors("ground_vehicle")[obstacle_type]
        assert missile > scout > ground
        assert missile > strike > ground


def test_unit_exposes_its_configured_factor():
    ground = _attacker(GroundVehicle)
    missile = _attacker(MissileVehicle)
    assert ground.obstacle_hit_factor("mountain") == pytest.approx(0.30)
    assert missile.obstacle_hit_factor("mountain") == pytest.approx(0.95)


def test_unconfigured_obstacle_type_does_not_decay():
    assert _attacker(GroundVehicle).obstacle_hit_factor("lava") == pytest.approx(1.0)
    assert "lava" not in get_obstacle_hit_factors("ground_vehicle")


def test_invalid_obstacle_factors_warn_once_and_fall_back(monkeypatch):
    fake = {
        "ground_vehicle": {
            "obstacle_hit_factors": {
                "mountain": 2.0,
                "building": "bad",
                "lava": 0.5,
            },
        },
        "scout_drone": {"obstacle_hit_factors": ["bad"]},
    }
    monkeypatch.setattr(unit_config_loader, "load_config", lambda: fake)
    unit_config_loader._OBSTACLE_WARNINGS.clear()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            factors = get_obstacle_hit_factors("ground_vehicle")
            assert factors["mountain"] == pytest.approx(1.0)
            assert factors["building"] == pytest.approx(1.0)
            assert "lava" not in factors
            assert get_obstacle_hit_factors("scout_drone") == {}
            get_obstacle_hit_factors("ground_vehicle")
        messages = [str(w.message) for w in caught]
        assert sum("障碍物命中配置无效" in message for message in messages) == 4
    finally:
        unit_config_loader._OBSTACLE_WARNINGS.clear()
        clear_config_cache()


# ═══════════════════════════════════════════════════════════
#  直线遮挡与叠加
# ═══════════════════════════════════════════════════════════


def test_ground_vehicle_single_obstacle_uses_its_factor():
    baseline, prob = _hit(
        _attacker(GroundVehicle), _target(), [_wall(100, "mountain")])
    assert prob == pytest.approx(baseline * 0.30, rel=1e-6)


def test_missile_vehicle_is_barely_affected():
    baseline, prob = _hit(
        _attacker(MissileVehicle), _target(), [_wall(100, "mountain")])
    assert prob == pytest.approx(baseline * 0.95, rel=1e-6)


def test_drone_decay_is_between_missile_and_ground():
    target = _target()
    baseline = calculate_hit_probability(
        _attacker(ScoutDrone), target, Battlefield(400, 200))
    _, ground_prob = _hit(_attacker(GroundVehicle), target, [_wall(100, "mountain")])
    _, scout_prob = _hit(_attacker(ScoutDrone), target, [_wall(100, "mountain")])
    _, missile_prob = _hit(_attacker(MissileVehicle), target, [_wall(100, "mountain")])
    assert scout_prob == pytest.approx(baseline * 0.60, rel=1e-6)
    assert ground_prob < scout_prob < missile_prob


def test_strike_drone_uses_its_own_factor():
    baseline, prob = _hit(
        _attacker(StrikeDrone), _target(), [_wall(100, "building")])
    assert prob == pytest.approx(baseline * 0.52, rel=1e-6)


def test_multiple_obstacles_stack_multiplicatively():
    baseline, prob = _hit(_attacker(GroundVehicle), _target(), [
        _wall(80, "mountain"),
        _wall(150, "building"),
    ])
    assert prob == pytest.approx(baseline * 0.30 * 0.25, rel=1e-6)


def test_same_type_obstacles_also_stack():
    baseline, prob = _hit(_attacker(GroundVehicle), _target(), [
        _wall(80, "mountain"),
        _wall(160, "mountain"),
    ])
    assert prob == pytest.approx(baseline * 0.30 * 0.30, rel=1e-6)


def test_obstacle_outside_attack_line_has_no_effect():
    baseline, prob = _hit(_attacker(GroundVehicle, y=50), _target(y=50), [
        Obstacle(x=100, y=150, width=10, height=40, type="building"),
    ])
    assert prob == pytest.approx(baseline, rel=1e-6)


def test_own_traversable_terrain_is_not_counted_as_cover():
    """攻击方所在且可通行的山地只走地形因子，不再额外计一次遮挡。"""
    attacker = _attacker(GroundVehicle, x=60, y=60)
    target = _target(x=300, y=60)
    obstacles = [
        Obstacle(x=40, y=40, width=60, height=60, type="mountain"),
        _wall(150, "building"),
    ]
    baseline, prob = _hit(attacker, target, obstacles)
    assert prob == pytest.approx(baseline * 0.75 * 0.25, rel=1e-6)


def test_air_unit_own_building_is_not_counted_as_cover():
    attacker = _attacker(ScoutDrone, x=60, y=60)
    target = _target(x=300, y=60)
    obstacles = [
        Obstacle(x=40, y=40, width=60, height=60, type="building"),
        _wall(150, "mountain"),
    ]
    baseline, prob = _hit(attacker, target, obstacles)
    assert prob == pytest.approx(baseline * 0.85 * 0.60, rel=1e-6)


def test_stacked_obstacles_still_respect_minimum_clamp():
    obstacles = [_wall(x, "mountain") for x in (60, 120, 180, 240)]
    _, prob = _hit(_attacker(GroundVehicle), _target(), obstacles)
    assert prob == pytest.approx(0.05)
