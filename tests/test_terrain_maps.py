"""Map presentation persistence and traversable rich-scenario regressions."""

import json
from collections import deque

import pytest

from core.battlefield import Battlefield, Obstacle
from core.controller import SimulationController
from core.map_persistence import (BUILTIN_SCENARIO_DIR, load_scenario_file,
                                  save_scenario)
from core.scenario_loader import scenario_from_data, validate_scenario
from core.terrain_catalog import map_presentation


def test_legacy_json_without_style_uses_tactical_presentation():
    field, _ = scenario_from_data({"map": {"width": 1200, "height": 800}, "units": []})
    assert field.map_style == "tactical"
    assert map_presentation(field.map_style, field.width, field.height)["background"] == ""


@pytest.mark.parametrize("style", ["tactical", "valley", "river"])
def test_map_style_survives_save_and_load_with_editable_geometry(tmp_path, style):
    field = Battlefield(1200, 800, terrain="custom_training", map_style=style,
                        obstacles=[Obstacle(350, 220, 90, 65, "街区", "building")],
                        red_base=(120, 400), blue_base=(1080, 400))
    destination = tmp_path / "地图样式.json"
    assert save_scenario(field, [], destination)
    assert json.loads(destination.read_text(encoding="utf-8"))["map"]["style"] == style

    loaded, _ = load_scenario_file(destination)

    assert loaded.map_style == style
    assert (loaded.width, loaded.height) == (1200, 800)
    assert loaded.terrain == field.terrain
    assert loaded.red_base == field.red_base
    assert loaded.blue_base == field.blue_base
    assert loaded.obstacles == field.obstacles


@pytest.mark.parametrize("invalid_style", [None, True, 42, [], {}, "forest"])
def test_scenario_style_validation_rejects_unsupported_and_nontext_values(invalid_style):
    with pytest.raises(ValueError, match="map.style"):
        validate_scenario({"map": {"style": invalid_style}, "units": []})


def test_invalid_style_load_keeps_current_map_and_units(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    controller = SimulationController()
    field = controller.battlefield
    units = controller.deployment.deploy_units
    path = tmp_path / "invalid-style.json"
    path.write_text(json.dumps({"map": {"width": 800, "height": 600, "style": "forest"}, "units": []}), encoding="utf-8")

    result = controller.load_map(path)

    assert not result.ok
    assert "map.style" in result.message
    assert controller.battlefield is field
    assert controller.deployment.deploy_units is units
    assert controller.battlefield.map_style == "river"


def test_presentation_landmarks_scale_with_world_size_and_cannot_mutate_catalog():
    small = map_presentation("valley", 600, 400)
    large = map_presentation("valley", 1200, 800)
    assert small["background"] == large["background"] == "terrain_valley.png"
    assert len(large["landmarks"]) == 8
    for small_point, large_point in zip(small["landmarks"], large["landmarks"]):
        assert large_point["name"] == small_point["name"]
        assert large_point["kind"] == small_point["kind"]
        assert large_point["x"] == pytest.approx(small_point["x"] * 2)
        assert large_point["y"] == pytest.approx(small_point["y"] * 2)
    large["landmarks"][0]["name"] = "修改外部快照"
    large["routes"].append("外部路径")
    fresh = map_presentation("valley", 1200, 800)
    assert fresh["landmarks"][0]["name"] == "青岚湖"
    assert fresh["routes"] == []


def test_deployment_style_change_updates_snapshot_without_changing_collision_or_units(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    controller = SimulationController()
    before = controller.snapshot()
    obstacle_objects = controller.battlefield.obstacles

    assert controller.set_map_style("valley").ok
    after = controller.snapshot()

    assert after["map"]["style"] == "valley"
    assert after["map"]["visual"]["background"] == "terrain_valley.png"
    assert after["map"]["visual"]["title"] == "山区河谷"
    assert after["units"] == before["units"]
    assert after["map"]["obstacles"] == before["map"]["obstacles"]
    assert controller.battlefield.obstacles is obstacle_objects
    path = tmp_path / "new-style.json"
    assert controller.save_map(path).ok
    assert controller.set_map_style("tactical").ok
    assert controller.load_map(path).ok
    assert controller.snapshot()["map"]["style"] == "valley"


def test_style_change_is_rejected_during_running_and_paused_simulation(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    controller = SimulationController()
    assert controller.start().ok
    assert not controller.set_map_style("valley").ok
    assert controller.battlefield.map_style == "river"
    controller.toggle_pause()
    assert not controller.set_map_style("tactical").ok
    assert controller.battlefield.map_style == "river"


def _reachable_grid(field, origin, spacing=10):
    """Independent coarse flood fill checks scenario connectivity, not AI behavior."""
    start = tuple(round(coordinate / spacing) for coordinate in origin)
    visited = {start}
    pending = deque([start])
    while pending:
        x, y = pending.popleft()
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            point = (x + dx, y + dy)
            if point not in visited and field.can_move_to(point[0] * spacing, point[1] * spacing):
                visited.add(point)
                pending.append(point)
    return visited


@pytest.mark.parametrize("scene_id,filename,style", [
    ("valley", "scenario_valley.json", "valley"),
    ("river_city", "scenario_river_city.json", "river"),
])
def test_rich_scenes_have_valid_starts_and_two_clear_accessible_bridge_corridors(scene_id, filename, style):
    path = BUILTIN_SCENARIO_DIR / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_scenario(data)
    field, units = load_scenario_file(path)
    assert (field.width, field.height) == (1200, 800)
    assert field.map_style == style
    assert len(field.obstacles) >= 12
    assert len(units) >= 12
    assert {unit.team for unit in units} == {"red", "blue"}
    for base in (field.red_base, field.blue_base):
        assert field.is_position_valid(*base)
    for unit in units:
        assert field.is_position_valid(unit.x, unit.y, unit.domain)

    from_red = _reachable_grid(field, field.red_base)
    from_blue = _reachable_grid(field, field.blue_base)
    blue_grid = tuple(round(coordinate / 10) for coordinate in field.blue_base)
    assert blue_grid in from_red
    for unit in units:
        if unit.domain != "air":
            assert (round(unit.x / 10), round(unit.y / 10)) in from_red
    bridges = [point for point in map_presentation(style, field.width, field.height)["landmarks"]
               if point["kind"] == "bridge"]
    assert len(bridges) == 2
    for bridge in bridges:
        bridge_grid = (round(bridge["x"] / 10), round(bridge["y"] / 10))
        assert bridge_grid in from_red and bridge_grid in from_blue
        # Preserve a broad crossing rather than a single passable marker pixel.
        for dx in range(-60, 61, 10):
            for dy in (-15, 0, 15):
                assert field.can_move_to(bridge["x"] + dx, bridge["y"] + dy)
    controller = SimulationController(path)
    snapshot = controller.snapshot()
    assert snapshot["scene_id"] == scene_id
    assert snapshot["map"]["style"] == style
    assert snapshot["map"]["visual"]["landmarks"] == map_presentation(style, 1200, 800)["landmarks"]


def test_rich_scene_registration_preserves_first_three_and_standard_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    controller = SimulationController()
    assert [scene["id"] for scene in controller.available_scenarios()] == [
        "standard", "obstacles", "custom", "valley", "river_city"]
    assert len(controller.snapshot()["units"]) == 10
    assert len(controller.snapshot()["map"]["obstacles"]) == 3
