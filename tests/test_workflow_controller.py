"""Regression tests for scene persistence and repeated simulation workflows."""

import json
from copy import deepcopy

import pytest

from config import GAME_DEPLOYMENT, GAME_FINISHED, GAME_PAUSED, GAME_RUNNING, SIM_SPEED_LEVELS
from core.controller import DEFAULT_SCENARIO_PATH, SimulationController
from core.map_persistence import load_scenario_file, save_scenario, user_scenario_dir
from core.scenario_loader import load_scenario


@pytest.fixture(autouse=True)
def isolate_user_data(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))


def write_scene(tmp_path, *, terrain="custom_terrain", filename="editable.json"):
    data = json.loads(DEFAULT_SCENARIO_PATH.read_text(encoding="utf-8"))
    data["terrain"] = terrain
    data["units"][0]["x"] = 170
    path = tmp_path / filename
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path, data


def test_user_storage_override_and_default_save_survive_new_controller(tmp_path):
    assert user_scenario_dir() == tmp_path / "user-data" / "scenarios"
    first = SimulationController()
    first.deployment.deploy_units[0].x = 170
    assert first.save_map().ok
    expected_path = user_scenario_dir() / "saved_map.json"
    assert first.current_save_path == expected_path
    second = SimulationController()
    assert second.load_map().ok
    assert second.deployment.deploy_units[0].x == 170
    assert second.current_save_path == expected_path


def test_presets_are_selectable_and_custom_requires_both_sides():
    controller = SimulationController()
    scenes = controller.available_scenarios()
    assert [scene["id"] for scene in scenes[:3]] == ["standard", "obstacles", "custom"]
    assert controller.select_scene("obstacles").ok
    assert len(controller.battlefield.obstacles) > 3
    assert controller.current_save_path is None
    assert controller.select_scene("custom").ok
    assert controller.deployment.display_units() == []
    assert not controller.start().ok
    assert controller.game_state == GAME_DEPLOYMENT
    assert controller.select_scene("standard").ok
    assert len(controller.deployment.display_units()) == 10


def test_loaded_scene_remains_reset_baseline_and_editor_uses_loaded_map(tmp_path):
    path, data = write_scene(tmp_path)
    controller = SimulationController()
    assert controller.load_map(path).ok
    loaded_map = controller.battlefield
    assert controller.deployment.editor.battlefield is loaded_map
    controller.deployment.deploy_units[0].x = 200
    assert controller.reset().ok
    assert controller.scene_name == path.stem
    assert controller.deployment.deploy_units[0].x == data["units"][0]["x"]
    assert controller.battlefield.terrain == data["terrain"]


def test_runtime_reset_and_restart_restore_edited_initial_deployment(tmp_path):
    path, _ = write_scene(tmp_path)
    controller = SimulationController(path)
    controller.deployment.deploy_units[0].x = 220
    original_base_hp = controller.battlefield.red_base_obj.hp
    assert controller.start().ok
    controller.simulator.units[0].x = 790
    controller.simulator.units[0].hp = 1
    controller.battlefield.red_base_obj.hp = 1
    controller.simulator.time_step = 42
    controller.simulator.combat_logs.append("previous run")
    assert controller.restart().ok
    assert controller.game_state == GAME_RUNNING
    assert controller.simulator.time_step == 0
    assert controller.simulator.units[0].x == 220
    assert controller.simulator.units[0].hp > 1
    assert controller.battlefield.red_base_obj.hp == original_base_hp
    assert "previous run" not in controller.simulator.combat_logs
    controller.simulator.units[0].x = 780
    assert controller.reset().ok
    assert controller.game_state == GAME_DEPLOYMENT
    assert controller.simulator is None
    assert controller.deployment.deploy_units[0].x == 220


def test_runtime_save_uses_pre_run_deployment_and_terrain(tmp_path):
    path, _ = write_scene(tmp_path)
    controller = SimulationController(path)
    controller.deployment.deploy_units[0].x = 210
    assert controller.start().ok
    controller.simulator.units[0].x = 790
    save_path = tmp_path / "saved-in-running.json"
    assert controller.save_map(save_path).ok
    battlefield, units = load_scenario_file(save_path)
    assert battlefield.terrain == "custom_terrain"
    assert units[0].x == 210


def test_save_and_save_as_track_current_file_and_preserve_terrain(tmp_path):
    source, _ = write_scene(tmp_path)
    controller = SimulationController(source)
    assert controller.save_map().ok
    target = tmp_path / "another-scene.json"
    assert controller.save_map(target).ok
    assert controller.current_save_path == target
    controller.deployment.deploy_units[0].x = 180
    assert controller.save_map().ok
    assert json.loads(target.read_text(encoding="utf-8"))["units"][0]["x"] == 180
    assert json.loads(source.read_text(encoding="utf-8"))["units"][0]["x"] == 170
    assert json.loads(target.read_text(encoding="utf-8"))["terrain"] == "custom_terrain"


def test_save_does_not_overwrite_builtin_resource():
    controller = SimulationController()
    original = DEFAULT_SCENARIO_PATH.read_bytes()
    result = controller.save_map(DEFAULT_SCENARIO_PATH)
    assert not result.ok
    assert "只读" in result.message
    assert DEFAULT_SCENARIO_PATH.read_bytes() == original


@pytest.mark.parametrize("change", [
    lambda scene: scene.update(map={"width": 0, "height": 600}),
    lambda scene: scene.update(obstacles="bad"),
    lambda scene: scene["units"][0].update(team="unknown"),
    lambda scene: scene["units"][0].update(x=float("nan")),
    lambda scene: scene["units"][0].update(unit_type="unknown"),
    lambda scene: scene["units"].append(deepcopy(scene["units"][0])),
    lambda scene: scene.update(red_base=[-1, 0]),
    lambda scene: scene["obstacles"][0].update(width=-1),
])
def test_invalid_load_leaves_active_simulation_intact(tmp_path, change):
    path, data = write_scene(tmp_path)
    controller = SimulationController()
    assert controller.start().ok
    original_simulator = controller.simulator
    original_battlefield = controller.battlefield
    original_path = controller.scenario_path
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    result = controller.load_map(path)
    assert not result.ok
    assert controller.simulator is original_simulator
    assert controller.battlefield is original_battlefield
    assert controller.scenario_path == original_path
    assert controller.game_state == GAME_RUNNING


def test_malformed_json_and_missing_file_do_not_replace_deployment(tmp_path):
    controller = SimulationController()
    original_deployment = controller.deployment
    malformed = tmp_path / "broken.json"
    malformed.write_text("{incomplete", encoding="utf-8")
    assert not controller.load_map(malformed).ok
    assert not controller.load_map(tmp_path / "missing.json").ok
    assert controller.deployment is original_deployment


def test_atomic_save_failure_retains_previous_file_and_cleans_temporary(tmp_path, monkeypatch):
    battlefield, units = load_scenario(DEFAULT_SCENARIO_PATH)
    path = tmp_path / "existing.json"
    path.write_text("previous contents", encoding="utf-8")

    def fail_replace(source, destination):
        raise PermissionError("simulated write protection")

    monkeypatch.setattr("core.map_persistence.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        save_scenario(battlefield, units, path)
    assert path.read_text(encoding="utf-8") == "previous contents"
    assert not list(tmp_path.glob("*.tmp"))


def test_edit_commands_are_rejected_while_running():
    controller = SimulationController()
    assert controller.start().ok
    before = deepcopy(controller.snapshot()["deployment"])
    before_count = len(controller.deployment.display_units())
    commands = [
        lambda: controller.toggle_team(), lambda: controller.select_unit_type("ground_vehicle"),
        lambda: controller.select_obstacle_type("building"), lambda: controller.place_at(200, 200),
        lambda: controller.pointer_press(1, 200, 200), lambda: controller.pointer_move(220, 220),
        lambda: controller.pointer_release(1, 220, 220), lambda: controller.undo(),
        lambda: controller.clear_deployment(), lambda: controller.delete_selected(),
    ]
    assert all(not command().ok for command in commands)
    assert controller.snapshot()["deployment"] == before
    assert len(controller.deployment.display_units()) == before_count


def test_speed_selection_rejects_bad_values_and_explains_fast_mode():
    controller = SimulationController()
    for invalid in (-1, len(SIM_SPEED_LEVELS), "1", True):
        assert not controller.set_speed(invalid).ok
    assert controller.set_speed(len(SIM_SPEED_LEVELS) - 1).ok
    assert controller.speed_label == "快速计算"
    assert controller.snapshot()["speed_index"] == len(SIM_SPEED_LEVELS) - 1


def test_export_requires_finished_result_and_writes_matching_statistics(tmp_path):
    controller = SimulationController()
    path = tmp_path / "result"
    assert not controller.export_result(path).ok
    assert controller.start().ok
    assert not controller.export_result(path).ok
    controller.simulator.winner = "red"
    controller.game_state = GAME_FINISHED
    assert controller.export_result(path).ok
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["statistics"] == controller.snapshot()["statistics"]
    assert data["statistics"]["winner"] == "red"
    assert "red_hits" in data["statistics"]
    assert data["scene_name"] == "标准对抗"


def test_pygame_load_from_runtime_returns_to_deployment_and_reset_keeps_loaded_scene(tmp_path):
    from pygame_main import create_deployment, handle_runtime_key, pygame

    controller = SimulationController()
    controller.deployment.deploy_units[0].x = 180
    assert controller.save_map().ok
    deployment, battlefield = create_deployment()
    result = handle_runtime_key(pygame.K_l, object(), GAME_PAUSED, deployment, battlefield, 0)
    simulator, state, loaded_deployment, loaded_battlefield, _ = result
    assert simulator is None
    assert state == GAME_DEPLOYMENT
    assert loaded_deployment.display_units()[0].x == 180
    assert loaded_deployment.editor.battlefield is loaded_battlefield
    result = handle_runtime_key(pygame.K_r, object(), GAME_RUNNING, loaded_deployment, loaded_battlefield, 0)
    assert result[2].display_units()[0].x == 180


def test_pygame_runtime_reset_preserves_pre_start_edit():
    from pygame_main import create_deployment, handle_deployment_event, handle_runtime_key, pygame

    deployment, battlefield = create_deployment()
    deployment.deploy_units[0].x = 180
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r")
    simulator, state, deployment, battlefield, _ = handle_deployment_event(
        event, deployment, battlefield, None, GAME_DEPLOYMENT)
    simulator.units[0].x = 790
    result = handle_runtime_key(pygame.K_r, simulator, state, deployment, battlefield, 0)
    assert result[1] == GAME_DEPLOYMENT
    assert result[2].display_units()[0].x == 180
