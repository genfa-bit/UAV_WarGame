"""Qt model workflow regressions without a QML engine or real preferences."""

import os
from copy import deepcopy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QGuiApplication

from ui import qt_models
from ui.qt_models import SimulationViewModel, UnitListModel


@pytest.fixture(scope="module")
def qt_application():
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


@pytest.fixture
def view_model(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    # The help preference stays isolated even if its constructor later changes.
    monkeypatch.setattr(qt_models, "QSettings", lambda *_: QSettings(
        str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    model = SimulationViewModel()
    yield model
    model._timer.stop()


def _world_snapshot(model):
    return deepcopy({key: model.snapshot[key] for key in
                     ("game_state", "scene_id", "scene_name", "units", "map", "statistics")})


def test_unit_click_selects_live_details_and_step_refreshes_them(view_model):
    view_model.startSimulation()
    initial = deepcopy(view_model.snapshot["units"][0])
    view_model.pointerPress(1, initial["x"], initial["y"])
    assert view_model.selectedUnitId == initial["id"]
    assert view_model.selectedUnit == initial
    live_unit = next(unit for unit in view_model.controller.simulator.units
                     if unit.id == initial["id"])
    live_unit.hp -= 7
    live_unit.ammo -= 2

    view_model.stepSimulation()

    detail = view_model.selectedUnit
    assert detail["hp"] == live_unit.hp
    assert detail["ammo"] == live_unit.ammo
    assert detail["x"] == live_unit.x
    assert detail["y"] == live_unit.y
    assert detail["engagement_label"] == live_unit.engagement_state.phase_name
    assert detail["max_ammo"] >= detail["ammo"]
    assert view_model.snapshot["statistics"]["time_step"] == 1


def test_clicking_empty_battlefield_clears_selected_details(view_model):
    view_model.startSimulation()
    view_model.selectUnit(view_model.snapshot["units"][0]["id"])

    view_model.pointerPress(1, 400, 40)

    assert view_model.selectedUnitId == ""
    assert view_model.selectedUnit == {}


def test_restarting_same_deployment_clears_previous_match_selection(view_model):
    view_model.startSimulation()
    unit_id = view_model.snapshot["units"][0]["id"]
    view_model.selectUnit(unit_id)
    assert view_model.selectedUnitId == unit_id
    view_model.stepSimulation()

    view_model.restartSimulation()

    assert view_model.snapshot["game_state"] == "running"
    assert view_model.snapshot["statistics"]["time_step"] == 0
    assert unit_id in {row["id"] for row in view_model.snapshot["units"]}
    assert view_model.selectedUnitId == ""
    assert view_model.selectedUnit == {}


def test_successful_scene_change_clears_selection_and_stops_run(view_model):
    view_model.startSimulation()
    view_model.selectUnit(view_model.snapshot["units"][0]["id"])

    view_model.loadScenario("custom")

    assert view_model.snapshot["scene_id"] == "custom"
    assert view_model.snapshot["game_state"] == "deployment"
    assert view_model.selectedUnitId == ""
    assert view_model.selectedUnit == {}
    assert view_model.unitModel.rowCount() == 0
    assert not view_model._timer.isActive()


def test_local_url_save_and_reload_handles_spaces_and_chinese_name(view_model, tmp_path):
    original_units = deepcopy(view_model.snapshot["units"])
    path = tmp_path / "演示 场景.json"
    view_model.saveMapToUrl(QUrl.fromLocalFile(str(path)))
    assert path.is_file()
    assert view_model.snapshot["current_save_path"] == str(path)
    view_model.loadScenario("custom")

    view_model.loadMapFromUrl(QUrl.fromLocalFile(str(path)))

    assert [row["id"] for row in view_model.snapshot["units"]] == [row["id"] for row in original_units]
    assert view_model.snapshot["scene_name"] == path.stem
    assert view_model.unitModel.rowCount() == len(original_units)


@pytest.mark.parametrize("command", ["saveMapToUrl", "loadMapFromUrl"])
def test_remote_url_is_rejected_without_replacing_current_world(view_model, command):
    view_model.startSimulation()
    view_model.selectUnit(view_model.snapshot["units"][0]["id"])
    before = _world_snapshot(view_model)
    selected = deepcopy(view_model.selectedUnit)
    simulator = view_model.controller.simulator

    getattr(view_model, command)(QUrl("https://example.com/scene.json"))

    assert _world_snapshot(view_model) == before
    assert view_model.controller.simulator is simulator
    assert view_model.selectedUnit == selected
    assert view_model.snapshot["message"] == "请选择本机上的文件"
    assert view_model._timer.isActive()


def test_invalid_local_map_keeps_running_world_and_selection(view_model, tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"map":', encoding="utf-8")
    view_model.startSimulation()
    view_model.selectUnit(view_model.snapshot["units"][0]["id"])
    before = _world_snapshot(view_model)
    selected = deepcopy(view_model.selectedUnit)
    simulator = view_model.controller.simulator

    view_model.loadMapFromUrl(QUrl.fromLocalFile(str(path)))

    assert _world_snapshot(view_model) == before
    assert view_model.controller.simulator is simulator
    assert view_model.selectedUnit == selected
    assert "加载失败" in view_model.snapshot["message"]
    assert view_model._timer.isActive()


def test_failed_save_does_not_change_world_or_active_save_path(view_model, tmp_path):
    path = tmp_path / "directory.json"
    path.mkdir()
    before = _world_snapshot(view_model)
    original_save_path = view_model.snapshot["current_save_path"]

    view_model.saveMapToUrl(QUrl.fromLocalFile(str(path)))

    assert _world_snapshot(view_model) == before
    assert view_model.snapshot["current_save_path"] == original_save_path
    assert "保存失败" in view_model.snapshot["message"]
    assert path.is_dir()
    assert list(tmp_path.glob(".directory.json.*.tmp")) == []


def test_fast_compute_uses_responsive_timer_and_bounded_batch(view_model, monkeypatch):
    view_model.startSimulation()
    view_model.setSpeed(3)
    assert view_model.snapshot["speed_label"] == "快速计算"
    assert view_model._timer.interval() == 33
    assert view_model._timer.isActive()
    changes = []
    view_model.snapshotChanged.connect(lambda: changes.append(True))
    # If computations are cheap, the per-batch step cap still yields to Qt.
    monkeypatch.setattr(qt_models, "perf_counter", lambda: 0)

    view_model._advance()

    assert 1 < view_model.snapshot["statistics"]["time_step"] <= 24
    assert len(changes) == 1
    view_model.togglePause()
    paused_step = view_model.snapshot["statistics"]["time_step"]
    assert view_model.snapshot["game_state"] == "paused"
    assert not view_model._timer.isActive()
    view_model._advance()
    assert view_model.snapshot["statistics"]["time_step"] == paused_step


def test_fast_batch_yields_when_time_budget_is_spent(view_model, monkeypatch):
    view_model.startSimulation()
    view_model.setSpeed(3)
    clock_values = iter([0, 0.020])
    monkeypatch.setattr(qt_models, "perf_counter", lambda: next(clock_values))

    view_model._advance()

    assert view_model.snapshot["statistics"]["time_step"] == 1


def test_fast_batch_stops_as_soon_as_controller_is_paused(view_model, monkeypatch):
    view_model.startSimulation()
    view_model.setSpeed(3)
    advance = view_model.controller.advance

    def advance_then_pause():
        result = advance()
        view_model.controller.toggle_pause()
        return result

    monkeypatch.setattr(view_model.controller, "advance", advance_then_pause)
    monkeypatch.setattr(qt_models, "perf_counter", lambda: 0)

    view_model._advance()

    assert view_model.snapshot["statistics"]["time_step"] == 1
    assert view_model.snapshot["game_state"] == "paused"
    assert not view_model._timer.isActive()


@pytest.mark.parametrize("start_paused", [False, True])
def test_single_step_leaves_nonterminal_simulation_paused(view_model, start_paused):
    view_model.startSimulation()
    if start_paused:
        view_model.togglePause()

    view_model.stepSimulation()

    assert view_model.snapshot["statistics"]["time_step"] == 1
    assert view_model.snapshot["game_state"] == "paused"
    assert not view_model._timer.isActive()
    view_model.stepSimulation()
    assert view_model.snapshot["statistics"]["time_step"] == 2
    assert view_model.snapshot["game_state"] == "paused"


@pytest.mark.parametrize("return_to_editor", [False, True])
def test_finished_run_restores_original_units_for_edit_or_restart(view_model, return_to_editor):
    view_model.startSimulation()
    original = deepcopy(view_model.snapshot["units"])
    old_simulator = view_model.controller.simulator
    view_model.selectUnit(original[0]["id"])
    for unit in old_simulator.units:
        if unit.team == "blue":
            unit.take_damage(unit.hp)
    view_model.stepSimulation()
    assert view_model.snapshot["game_state"] == "finished"
    assert not view_model._timer.isActive()

    if return_to_editor:
        view_model.resetSimulation()
        assert view_model.snapshot["game_state"] == "deployment"
        assert view_model.selectedUnitId == ""
        assert view_model.selectedUnit == {}
        assert view_model.snapshot["units"] == original
        view_model.startSimulation()
    else:
        view_model.restartSimulation()

    assert view_model.controller.simulator is not old_simulator
    assert view_model.snapshot["game_state"] == "running"
    assert view_model.snapshot["statistics"]["time_step"] == 0
    assert view_model.snapshot["statistics"]["winner"] is None
    assert view_model.snapshot["units"] == original
    assert view_model._timer.isActive()


def test_unit_model_emits_only_for_changed_roles_and_reuses_existing_rows(qt_application):
    model = UnitListModel()
    row = {"id": "red", "name": "Red", "x": 10, "y": 20, "hp": 80, "ammo": 6}
    model.set_rows([row])
    changes = []
    resets = []
    model.dataChanged.connect(lambda top, bottom, roles: changes.append(
        (top.row(), bottom.row(), set(roles))))
    model.modelReset.connect(lambda: resets.append(True))

    model.set_rows([dict(row)])
    model.set_rows([dict(row)])
    assert changes == []
    assert resets == []
    # Changing the caller's row after a refresh cannot silently mutate the model.
    row["hp"] = 73
    row["ammo"] = 5
    assert model.data(model.index(0, 0), UnitListModel.HpRole) == 80
    model.set_rows([row])
    assert changes == [(0, 0, {UnitListModel.HpRole, UnitListModel.AmmoRole})]
    assert resets == []
    model.set_rows([dict(row)])
    assert len(changes) == 1
    assert model.data(model.index(0, 0), UnitListModel.AmmoRole) == 5
