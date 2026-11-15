"""测试山地/建筑的可通行性与地形修正。

对应 data/unit_config.json 中的 ``terrain_effects``：
- 列出的地形表示该兵种可以进入；
- speed_factor / attack_hit_factor / cover_hit_factor 分别影响移动、攻击、受击。
"""

import warnings

import pytest

from core import unit_config_loader
from core.battlefield import Battlefield, Obstacle
from core.combat import calculate_hit_probability
from core.controller import SimulationController
from core.deployment import DeploymentManager
from core.obstacle_editor import MapEditor
from core.unit_config_loader import clear_config_cache, get_terrain_effects
from core.units import CommandNode, GroundVehicle, MissileVehicle, ScoutDrone


def _mountain(x=50, y=50, width=40, height=40) -> Obstacle:
    return Obstacle(x=x, y=y, width=width, height=height,
                    name="山地", type="mountain")


def _building(x=50, y=50, width=40, height=40) -> Obstacle:
    return Obstacle(x=x, y=y, width=width, height=height,
                    name="建筑", type="building")


def _restricted(x=50, y=50, width=40, height=40) -> Obstacle:
    return Obstacle(x=x, y=y, width=width, height=height,
                    name="禁行区", type="restricted")


def _ground(unit_type="ground_vehicle", **kwargs):
    cls = GroundVehicle if unit_type == "ground_vehicle" else MissileVehicle
    defaults = dict(id=f"{unit_type}-1", name=unit_type, team="red", x=10, y=10)
    defaults.update(kwargs)
    return cls(**defaults)


# ═══════════════════════════════════════════════════════════
#  配置读取
# ═══════════════════════════════════════════════════════════


def test_ground_vehicle_terrain_effects_loaded_from_config():
    effects = get_terrain_effects("ground_vehicle")
    assert set(effects) == {"mountain", "building"}
    assert effects["mountain"]["speed_factor"] == pytest.approx(0.55)
    assert effects["mountain"]["attack_hit_factor"] == pytest.approx(0.75)
    assert effects["mountain"]["cover_hit_factor"] == pytest.approx(0.80)
    assert effects["building"]["speed_factor"] == pytest.approx(0.70)


def test_missile_vehicle_terrain_effects_loaded_from_config():
    effects = get_terrain_effects("missile_vehicle")
    assert set(effects) == {"mountain", "building"}
    assert effects["mountain"]["speed_factor"] == pytest.approx(0.45)


def test_air_units_have_hit_modifiers_without_speed_penalty():
    for unit_type in ("scout_drone", "strike_drone"):
        effects = get_terrain_effects(unit_type)
        assert set(effects) == {"mountain", "building"}
        for terrain in ("mountain", "building"):
            assert effects[terrain]["speed_factor"] == pytest.approx(1.0)
            assert effects[terrain]["attack_hit_factor"] == pytest.approx(0.85)
            assert effects[terrain]["cover_hit_factor"] == pytest.approx(0.80)


def test_command_unit_has_no_terrain_effects():
    assert get_terrain_effects("command_node") == {}


def test_terrain_effects_returns_independent_copy():
    effects = get_terrain_effects("ground_vehicle")
    effects["mountain"]["speed_factor"] = 0.01
    assert get_terrain_effects("ground_vehicle")["mountain"]["speed_factor"] == pytest.approx(0.55)


def test_invalid_terrain_config_warns_once_and_falls_back(monkeypatch):
    fake = {
        "fake_unit": {
            "terrain_effects": {
                "mountain": {"speed_factor": 2.0, "attack_hit_factor": "bad"},
                "lava": {"speed_factor": 0.5},
            }
        }
    }
    monkeypatch.setattr(unit_config_loader, "load_config", lambda: fake)
    unit_config_loader._TERRAIN_WARNINGS.clear()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            effects = get_terrain_effects("fake_unit")
        assert "lava" not in effects
        assert effects["mountain"] == {
            "speed_factor": 1.0,
            "attack_hit_factor": 1.0,
            "cover_hit_factor": 1.0,
        }
        assert any("地形配置无效" in str(w.message) for w in caught)
    finally:
        unit_config_loader._TERRAIN_WARNINGS.clear()
        clear_config_cache()


# ═══════════════════════════════════════════════════════════
#  通行性
# ═══════════════════════════════════════════════════════════


def test_ground_vehicle_can_enter_mountain_and_building():
    battlefield = Battlefield(200, 200, [_mountain(50, 50), _building(120, 50)])
    unit = _ground()
    assert battlefield.is_position_valid(60, 60, unit)
    assert battlefield.is_position_valid(130, 60, unit)
    assert unit.can_traverse("mountain")
    assert unit.can_traverse("building")


def test_ground_vehicle_blocked_by_restricted_and_default_obstacle():
    battlefield = Battlefield(200, 200, [
        _restricted(50, 50),
        Obstacle(120, 50, 40, 40),
    ])
    unit = _ground()
    assert not battlefield.is_position_valid(60, 60, unit)
    assert not battlefield.is_position_valid(130, 60, unit)


def test_missile_vehicle_can_enter_mountain_but_not_restricted():
    battlefield = Battlefield(200, 200, [_mountain(50, 50), _restricted(120, 50)])
    unit = _ground("missile_vehicle")
    assert battlefield.is_position_valid(60, 60, unit)
    assert not battlefield.is_position_valid(130, 60, unit)


def test_air_unit_ignores_obstacles():
    battlefield = Battlefield(200, 200, [_mountain(50, 50), _restricted(120, 50)])
    drone = ScoutDrone(id="d", name="无人机", team="red", x=10, y=10)
    assert battlefield.is_position_valid(60, 60, drone)
    assert battlefield.is_position_valid(130, 60, drone)


def test_legacy_string_domain_still_blocks_all_obstacles():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    assert not battlefield.is_position_valid(60, 60, "ground")
    assert not battlefield.can_move_to(60, 60)


def test_obstacles_at_returns_all_overlaps():
    mountain = _mountain(50, 50)
    building = _building(55, 55)
    battlefield = Battlefield(200, 200, [mountain, building])
    assert set(battlefield.obstacles_at(60, 60)) == {mountain, building}
    assert battlefield.obstacles_at(10, 10) == ()


# ═══════════════════════════════════════════════════════════
#  移动减速
# ═══════════════════════════════════════════════════════════


def test_effective_speed_is_reduced_inside_passable_terrain():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    unit = _ground(x=60, y=60)
    assert unit.effective_speed(battlefield) == pytest.approx(unit.speed * 0.55)


def test_effective_speed_normal_outside_terrain():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    unit = _ground(x=10, y=10)
    assert unit.effective_speed(battlefield) == pytest.approx(unit.speed)


def test_move_towards_uses_reduced_step_inside_mountain():
    battlefield = Battlefield(200, 200, [_mountain(40, 40, width=60, height=60)])
    unit = _ground(x=60, y=60)
    unit.move_towards(100, 60, battlefield)
    assert unit.x - 60 == pytest.approx(unit.speed * 0.55, abs=1e-6)
    assert unit.y == pytest.approx(60)


def test_ground_vehicle_can_move_into_mountain():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    unit = _ground(x=49, y=60)
    unit.move_towards(80, 60, battlefield)
    assert unit.x > 50
    assert battlefield.obstacles_at(unit.x, unit.y)


def test_ground_vehicle_cannot_move_into_restricted():
    battlefield = Battlefield(200, 200, [_restricted(50, 50)])
    unit = _ground(x=49, y=60)
    unit.move_towards(80, 60, battlefield)
    assert not _restricted(50, 50).contains(unit.x, unit.y)


# ═══════════════════════════════════════════════════════════
#  命中率修正
# ═══════════════════════════════════════════════════════════


def _hit_prob(attacker, target, battlefield):
    return calculate_hit_probability(attacker, target, battlefield)


def test_attacker_inside_mountain_reduces_hit_probability():
    empty = Battlefield(200, 200)
    terrain = Battlefield(200, 200, [_mountain(40, 40, 60, 60)])
    attacker = _ground(x=60, y=60, base_hit_prob=0.85, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=130, y=60, speed=0)

    baseline = _hit_prob(attacker, target, empty)
    reduced = _hit_prob(attacker, target, terrain)
    assert reduced == pytest.approx(baseline * 0.75, rel=1e-6)


def test_target_inside_building_reduces_hit_probability():
    empty = Battlefield(200, 200)
    terrain = Battlefield(200, 200, [_building(60, 40, 60, 60)])
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=20, y=60,
                          base_hit_prob=0.85, attack_range=200)
    target = _ground(x=70, y=60, speed=0)

    baseline = _hit_prob(attacker, target, empty)
    reduced = _hit_prob(attacker, target, terrain)
    assert reduced == pytest.approx(baseline * 0.60, rel=1e-6)


def test_attacker_and_target_terrain_factors_stack():
    empty = Battlefield(200, 200)
    terrain = Battlefield(200, 200, [_mountain(40, 40, 60, 60)])
    attacker = _ground(x=60, y=60, base_hit_prob=0.85, attack_range=200)
    target = _ground(x=70, y=60, speed=0, team="blue")

    baseline = _hit_prob(attacker, target, empty)
    reduced = _hit_prob(attacker, target, terrain)
    assert reduced == pytest.approx(baseline * 0.75 * 0.80, rel=1e-6)


def test_separate_obstacle_between_units_still_applies_cover():
    terrain = Battlefield(200, 200, [
        _mountain(40, 40, 40, 40),
        _restricted(100, 0, 10, 200),
    ])
    attacker = _ground(x=60, y=60, base_hit_prob=0.85, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=150, y=60, speed=0)
    prob = _hit_prob(attacker, target, terrain)
    baseline = _hit_prob(attacker, target, Battlefield(200, 200))
    assert prob == pytest.approx(baseline * 0.75 * 0.3, rel=1e-6)


def test_air_effective_speed_unchanged_inside_terrain():
    for terrain in (_mountain(50, 50), _building(50, 50)):
        battlefield = Battlefield(200, 200, [terrain])
        drone = ScoutDrone(id="d", name="无人机", team="red", x=60, y=60)
        assert drone.terrain_factor(battlefield, "speed_factor") == pytest.approx(1.0)
        assert drone.effective_speed(battlefield) == pytest.approx(drone.speed)


def test_air_attacker_inside_building_reduces_hit_probability():
    empty = Battlefield(200, 200)
    terrain = Battlefield(200, 200, [_building(40, 40, 60, 60)])
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=60, y=60,
                          base_hit_prob=0.85, attack_range=200)
    target = _ground(x=150, y=60, speed=0)

    baseline = _hit_prob(attacker, target, empty)
    reduced = _hit_prob(attacker, target, terrain)
    assert reduced == pytest.approx(baseline * 0.85, rel=1e-6)


def test_air_target_inside_mountain_reduces_incoming_hit_probability():
    empty = Battlefield(200, 200)
    terrain = Battlefield(200, 200, [_mountain(60, 40, 60, 60)])
    attacker = _ground(x=20, y=60, base_hit_prob=0.85, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=70, y=60, speed=0)

    baseline = _hit_prob(attacker, target, empty)
    reduced = _hit_prob(attacker, target, terrain)
    assert reduced == pytest.approx(baseline * 0.80, rel=1e-6)


def test_air_unit_over_restricted_still_uses_line_of_sight_cover():
    terrain = Battlefield(200, 200, [_restricted(50, 50, 40, 40)])
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=60, y=60,
                          base_hit_prob=0.85, attack_range=200)
    target = _ground(x=150, y=60, speed=0)
    prob = _hit_prob(attacker, target, terrain)
    baseline = _hit_prob(attacker, target, Battlefield(200, 200))
    assert prob == pytest.approx(baseline * 0.3, rel=1e-6)


def test_units_without_terrain_effects_ignore_terrain_factors():
    """没有 terrain_effects 的兵种不会获得地形命中修正。"""
    terrain = Battlefield(200, 200, [_mountain(40, 40, 60, 60)])
    node = CommandNode(id="c", name="指挥节点", team="red", x=60, y=60)
    assert node.terrain_factor(terrain, "attack_hit_factor") == pytest.approx(1.0)
    assert node.terrain_factor(terrain, "cover_hit_factor") == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════
#  详情面板快照
# ═══════════════════════════════════════════════════════════


def test_terrain_snapshot_reports_current_terrain_and_factors():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    unit = _ground(x=60, y=60)

    snapshot = SimulationController._terrain_snapshot(unit, battlefield)

    assert snapshot["terrain_type"] == "mountain"
    assert snapshot["terrain_label"] == "山地"
    assert snapshot["speed_factor"] == pytest.approx(0.55)
    assert snapshot["attack_hit_factor"] == pytest.approx(0.75)
    assert snapshot["cover_hit_factor"] == pytest.approx(0.80)
    assert snapshot["effective_speed"] == pytest.approx(unit.speed * 0.55)


def test_terrain_snapshot_defaults_outside_terrain():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    unit = _ground(x=10, y=10)

    snapshot = SimulationController._terrain_snapshot(unit, battlefield)

    assert snapshot["terrain_type"] == ""
    assert snapshot["terrain_label"] == ""
    assert snapshot["speed_factor"] == pytest.approx(1.0)
    assert snapshot["effective_speed"] == pytest.approx(unit.speed)


# ═══════════════════════════════════════════════════════════
#  部署与地图编辑
# ═══════════════════════════════════════════════════════════


def _manager(*obstacles) -> DeploymentManager:
    battlefield = Battlefield(200, 200, list(obstacles))
    return DeploymentManager(battlefield, [])


def test_deploy_ground_vehicle_on_mountain_and_building():
    manager = _manager(_mountain(50, 50), _building(100, 50))
    manager.selected_unit_type = "ground_vehicle"

    assert manager._place_unit_at(60, 60)
    manager.selected_unit_type = "missile_vehicle"
    assert manager._place_unit_at(110, 60)


def test_deploy_ground_vehicle_on_restricted_still_blocked():
    manager = _manager(_restricted(50, 50))
    manager.selected_unit_type = "ground_vehicle"

    assert not manager._place_unit_at(60, 60)
    assert "不能进入此地形" in manager.last_message


def test_deploy_air_unit_on_mountain_still_blocked():
    manager = _manager(_mountain(50, 50))
    manager.selected_unit_type = "scout_drone"

    assert not manager._place_unit_at(60, 60)


def test_editor_drag_ground_vehicle_into_mountain():
    battlefield = Battlefield(200, 200, [_mountain(50, 50)])
    editor = MapEditor(battlefield)
    unit = _ground(x=10, y=10)
    units = [unit]

    editor.start_drag_unit(0, units)
    editor.update_drag_unit(60, 60, units)
    assert editor.finish_drag_unit(unit, units, 0)
    assert (unit.x, unit.y) == pytest.approx((60, 60))


def test_editor_drag_ground_vehicle_into_restricted_reverts():
    battlefield = Battlefield(200, 200, [_restricted(50, 50)])
    editor = MapEditor(battlefield)
    unit = _ground(x=10, y=10)
    units = [unit]

    editor.start_drag_unit(0, units)
    editor.update_drag_unit(60, 60, units)
    assert not editor.finish_drag_unit(unit, units, 0)
    assert (unit.x, unit.y) == pytest.approx((10, 10))


def test_editor_can_create_mountain_over_ground_vehicle():
    battlefield = Battlefield(200, 200)
    editor = MapEditor(battlefield)
    unit = _ground(x=60, y=60)
    editor._deploy_units = [unit]

    editor.start_create_obstacle(50, 50)
    idx = editor.finish_create_obstacle(100, 100, "mountain")
    assert idx is not None
    assert battlefield.obstacles[idx].type == "mountain"


def test_editor_cannot_create_restricted_over_ground_vehicle():
    battlefield = Battlefield(200, 200)
    editor = MapEditor(battlefield)
    editor._deploy_units = [_ground(x=60, y=60)]

    editor.start_create_obstacle(50, 50)
    assert editor.finish_create_obstacle(100, 100, "restricted") is None


def test_editor_cannot_create_terrain_over_air_unit():
    battlefield = Battlefield(200, 200)
    editor = MapEditor(battlefield)
    editor._deploy_units = [ScoutDrone(id="d", name="无人机", team="red", x=60, y=60)]

    editor.start_create_obstacle(50, 50)
    # 空中单位本来就不受障碍物影响，创建山地必须成功。
    assert editor.finish_create_obstacle(100, 100, "mountain") is not None
