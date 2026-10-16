"""Timing, full journal exports, and durable repeated-run regression coverage."""

import json
from pathlib import Path

import pytest

from config import GAME_DEPLOYMENT, GAME_FINISHED, GAME_PAUSED, GAME_RUNNING
from core.controller import DEFAULT_SCENARIO_PATH, SimulationController


@pytest.fixture(autouse=True)
def isolated_record_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))


def saved_payload(controller):
    return json.loads(Path(controller.snapshot()["recording"]["save_path"]).read_text(encoding="utf-8"))


def test_default_timing_keeps_existing_speed_intervals_and_snapshot_serializable():
    controller = SimulationController()
    snapshot = controller.snapshot()
    assert snapshot["timing"] == {"step_duration_seconds": 0.22, "max_steps": 2000, "editable": True}
    for index, interval in enumerate((220, 110, 55, 0)):
        assert controller.set_speed(index).ok
        assert controller.speed_interval_ms == interval
    json.dumps(snapshot, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("duration,max_steps", [
    (0, 100), (0.009, 100), (60.01, 100), (float("nan"), 100),
    (float("inf"), 100), (float("-inf"), 100), (True, 100), ("0.5", 100),
    (10 ** 400, 100), (0.5, 0), (0.5, 1000001), (0.5, True),
    (0.5, 2.5), (0.5, "100"),
])
def test_invalid_timing_update_is_atomic(duration, max_steps):
    controller = SimulationController()
    assert controller.set_timing(0.5, 100).ok
    assert not controller.set_timing(duration, max_steps).ok
    assert controller.snapshot()["timing"] == {"step_duration_seconds": 0.5, "max_steps": 100, "editable": True}
    assert controller.speed_interval_ms == 500


def test_paused_timing_preserves_elapsed_time_and_rejects_exhausted_step_limit():
    controller = SimulationController()
    assert controller.set_timing(0.5, 10).ok
    assert controller.start().ok
    assert not controller.set_timing(1, 20).ok
    assert controller.snapshot()["timing"]["editable"] is False
    controller.advance()
    controller.advance()
    assert controller.simulator.elapsed_seconds == 1
    assert controller.toggle_pause().ok
    assert controller.set_timing(1, 20).ok
    assert controller.simulator.elapsed_seconds == 1
    assert controller.simulator.step_duration_seconds == 1
    assert controller.simulator.max_steps == 20
    settings = [row for row in controller.simulator.records if row["category"] == "settings"]
    assert len(settings) == 1
    assert settings[0]["step"] == 2 and settings[0]["elapsed_seconds"] == 1
    assert controller.step().ok
    assert controller.simulator.elapsed_seconds == 2
    assert controller.game_state == GAME_PAUSED
    assert not controller.set_timing(0.1, 3).ok
    assert controller.step_duration_seconds == 1
    assert controller.max_steps == 20
    assert controller.simulator.step_duration_seconds == 1
    assert saved_payload(controller)["settings"] == {"step_duration_seconds": 1, "max_steps": 20}


def test_timing_survives_restart_reset_and_scene_change_and_run_ids_are_unique():
    controller = SimulationController()
    assert controller.set_timing(0.75, 12).ok
    assert controller.start().ok
    first_id = controller.snapshot()["recording"]["run_id"]
    controller.advance()
    assert controller.restart().ok
    second_id = controller.snapshot()["recording"]["run_id"]
    assert second_id != first_id
    assert controller.simulator.elapsed_seconds == 0
    assert controller.simulator.max_steps == 12
    assert controller.simulator.step_duration_seconds == 0.75
    assert controller.reset().ok
    assert controller.select_scene("valley").ok
    assert controller.start().ok
    assert controller.simulator.max_steps == 12
    assert controller.simulator.step_duration_seconds == 0.75
    history = controller.snapshot()["recording"]["history"]
    assert len(history) == 3
    assert {row["run_id"] for row in history} >= {first_id, second_id}


def test_pause_and_finish_persist_result_events_and_history_survives_new_controller():
    controller = SimulationController()
    assert controller.set_timing(0.5, 2).ok
    assert controller.start().ok
    controller.advance()
    assert controller.toggle_pause().ok
    paused = saved_payload(controller)
    assert paused["phase"] == GAME_PAUSED
    assert paused["statistics"]["elapsed_seconds"] == 0.5
    assert paused["records"][-1]["action"] == "pause"
    assert controller.toggle_pause().ok
    assert controller.advance().ok
    assert controller.game_state == GAME_FINISHED
    assert not controller.set_timing(1, 100).ok
    finished = saved_payload(controller)
    assert finished["schema_version"] == 3
    assert finished["finished"] is True
    assert finished["result"]["elapsed_seconds"] == 1
    assert len([row for row in finished["records"] if row["category"] == "result"]) == 1
    second = SimulationController()
    history = second.snapshot()["recording"]["history"]
    assert len(history) == 1
    assert history[0]["run_id"] == finished["run_id"]
    assert history[0]["finished"] is True
    assert history[0]["steps"] == 2
    assert history[0]["elapsed_seconds"] == 1


def test_full_export_is_not_truncated_to_recent_rows_and_filter_preserves_other_fields(tmp_path):
    controller = SimulationController()
    assert controller.start().ok
    for index in range(350):
        controller.simulator.record_event("scout", f"observation {index}", target_id=f"target-{index}")
    controller.simulator.record_event("sharing", "delivered", target_id="target-1")
    total = len(controller.simulator.records)
    snapshot = controller.snapshot()["recording"]
    assert snapshot["record_count"] == total
    assert len(snapshot["records"]) == 200
    path = tmp_path / "records"
    assert controller.export_records(path).ok
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert len(data["records"]) == total
    assert [row["seq"] for row in data["records"]] == list(range(1, total + 1))
    assert data["records"][0]["step"] == 0
    assert data["settings"]["max_steps"] == 2000
    assert "history" in data and "destroyed_units" in data and "units" in data and "result" in data
    filtered = tmp_path / "shared.json"
    assert controller.export_records(filtered, "sharing").ok
    selected = json.loads(filtered.read_text(encoding="utf-8"))
    assert len(selected["records"]) == 1
    assert selected["records"][0]["category"] == "sharing"
    assert selected["units"] == data["units"]
    assert selected["statistics"] == data["statistics"]
    assert not controller.export_records(filtered, "invalid").ok
    assert json.loads(filtered.read_text(encoding="utf-8")) == selected


def test_auto_save_failure_keeps_simulation_and_archived_records_exportable(tmp_path, monkeypatch):
    from core import controller as module

    original_writer = module.write_json_atomic

    def failing_writer(path, data):
        raise PermissionError("record directory is read-only")

    monkeypatch.setattr(module, "write_json_atomic", failing_writer)
    controller = SimulationController()
    assert controller.start().ok
    assert controller.game_state == GAME_RUNNING
    controller.simulator.record_event("scout", "must survive reset", target_id="retained")
    snapshot = controller.snapshot()["recording"]
    assert "只读" in controller.last_message or "read-only" in controller.last_message
    assert snapshot["last_error"]
    assert snapshot["unsaved_count"] == 1
    assert not controller.flush_records().ok
    assert controller.reset().ok
    assert controller.game_state == GAME_DEPLOYMENT
    assert controller.simulator is None
    assert controller.snapshot()["recording"]["has_run"] is True
    monkeypatch.setattr(module, "write_json_atomic", original_writer)
    path = tmp_path / "recovered.json"
    assert controller.export_records(path).ok
    data = json.loads(path.read_text(encoding="utf-8"))
    assert any(row.get("target_id") == "retained" for row in data["records"])
    assert data["records"][-1]["action"] == "reset"


def test_normal_shutdown_flush_saves_latest_steps_without_duplicate_events():
    controller = SimulationController()
    assert controller.start().ok
    controller.advance()
    count = len(controller.simulator.records)
    assert saved_payload(controller)["statistics"]["time_step"] == 0
    assert controller.flush_records().ok
    data = saved_payload(controller)
    assert data["statistics"]["time_step"] == 1
    assert len(data["records"]) == count
    assert controller.game_state == GAME_RUNNING


def test_periodic_save_covers_long_running_simulation_after_wall_clock_interval(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("core.controller.monotonic", lambda: clock[0])
    controller = SimulationController()
    assert controller.start().ok
    for _ in range(50):
        assert controller.advance().ok
    assert saved_payload(controller)["statistics"]["time_step"] == 0
    clock[0] += 5
    controller.advance()
    payload = saved_payload(controller)
    assert payload["statistics"]["time_step"] == 51
    assert payload["statistics"]["elapsed_seconds"] == 11.22


def test_fast_compute_throttles_complete_journal_writes_but_finish_flushes(monkeypatch):
    from core import controller as module

    clock = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    original_writer = module.write_json_atomic
    saved_steps = []

    def counted_writer(path, data):
        saved_steps.append(data["statistics"]["time_step"])
        original_writer(path, data)

    monkeypatch.setattr(module, "write_json_atomic", counted_writer)
    controller = SimulationController()
    controller.set_timing(0.22, 120)
    assert controller.start().ok
    for _ in range(100):
        assert controller.advance().ok
    assert saved_steps == [0]
    clock[0] += 5
    controller.advance()
    assert saved_steps == [0, 101]
    for _ in range(19):
        assert controller.advance().ok
    assert controller.game_state == GAME_FINISHED
    assert saved_steps == [0, 101, 120]
    payload = saved_payload(controller)
    assert payload["finished"] is True
    assert len(payload["records"]) == len(controller.simulator.records)


def test_failed_periodic_save_waits_before_retry_and_pause_still_saves(monkeypatch):
    from core import controller as module

    clock = [100.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    original_writer = module.write_json_atomic
    attempts = []

    def failing_writer(path, data):
        attempts.append(data["statistics"]["time_step"])
        raise PermissionError("temporary storage outage")

    monkeypatch.setattr(module, "write_json_atomic", failing_writer)
    controller = SimulationController()
    assert controller.start().ok
    for _ in range(60):
        controller.advance()
    assert attempts == [0]
    clock[0] += 5
    controller.advance()
    assert attempts == [0, 61]
    for _ in range(50):
        controller.advance()
    assert attempts == [0, 61]
    clock[0] += 5
    controller.advance()
    assert attempts == [0, 61, 112]
    assert controller.last_message.count("temporary storage outage") == 1
    monkeypatch.setattr(module, "write_json_atomic", original_writer)
    for _ in range(50):
        controller.advance()
    clock[0] += 5
    controller.advance()
    assert not controller.snapshot()["recording"]["last_error"]
    assert "temporary storage outage" not in controller.last_message
    assert "自动保存记录失败" not in controller.last_message
    monkeypatch.setattr(module, "write_json_atomic", failing_writer)
    assert controller.toggle_pause().ok
    assert attempts == [0, 61, 112, 163]
    assert controller.game_state == GAME_PAUSED


def test_exports_reject_empty_run_and_builtin_scene_and_result_requires_finish(tmp_path):
    controller = SimulationController()
    assert not controller.export_records(tmp_path / "none.json").ok
    before = DEFAULT_SCENARIO_PATH.read_bytes()
    assert controller.start().ok
    assert not controller.export_records(DEFAULT_SCENARIO_PATH).ok
    assert not controller.export_result(tmp_path / "unfinished.json").ok
    assert DEFAULT_SCENARIO_PATH.read_bytes() == before
    controller.simulator.winner = "red"
    controller.game_state = GAME_FINISHED
    assert controller.export_result(tmp_path / "result.json").ok
    data = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 3 and data["result"]["winner"] == "red"
    assert data["statistics"] == controller.snapshot()["statistics"]


def test_destruction_time_and_killer_are_available_in_unit_detail_snapshot():
    controller = SimulationController()
    controller.start()
    unit = controller.simulator.units[0]
    unit.hp = 0
    controller.simulator.destroyed_units.append({
        "unit_id": unit.id, "name": unit.name, "team": unit.team,
        "unit_type": unit.unit_type, "step": 7, "elapsed_seconds": 1.54,
        "killer_id": "B-SD-1", "killer_name": "enemy", "is_base": False,
    })
    snapshot = controller.snapshot()
    detail = next(row for row in snapshot["units"] if row["id"] == unit.id)
    assert detail["destroyed_step"] == 7
    assert detail["destroyed_elapsed_seconds"] == 1.54
    assert detail["killer_id"] == "B-SD-1"
    assert snapshot["recording"]["destroyed_units"][0]["unit_id"] == unit.id


def test_history_ignores_corrupt_files_and_is_cached_for_snapshot_refresh(tmp_path, monkeypatch):
    controller = SimulationController()
    directory = controller.recording_directory
    directory.mkdir(parents=True)
    (directory / "bad.json").write_text("{broken", encoding="utf-8")
    (directory / "shape.json").write_text(json.dumps({"schema_version": 2, "run_id": "bad", "statistics": []}), encoding="utf-8")
    assert controller.start().ok
    assert len(controller.snapshot()["recording"]["history"]) == 1

    def unexpected_rescan(*args, **kwargs):
        raise AssertionError("history must not rescan storage on every redraw")

    monkeypatch.setattr(Path, "glob", unexpected_rescan)
    # available_scenarios does not scan a missing scenarios directory.
    assert len(controller.snapshot()["recording"]["history"]) == 1


def test_view_model_timing_export_and_local_recording_url(tmp_path):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication
    from ui.qt_models import SimulationViewModel

    app = QGuiApplication.instance() or QGuiApplication([])
    controller = SimulationController()
    model = SimulationViewModel(controller)
    model.setTiming(0.4, 10)
    assert model.snapshot["timing"]["step_duration_seconds"] == 0.4
    assert model.snapshot["speed_interval_ms"] == 400
    model.startSimulation()
    assert model._timer.interval() == 400
    model.togglePause()
    model.setTiming(0.6, 20)
    assert model._timer.interval() == 600
    path = tmp_path / "qml-export.json"
    model.exportRecordsToUrl(QUrl.fromLocalFile(str(path)), "all")
    assert path.exists()
    assert Path(model.recordingDirectoryUrl.toLocalFile()) == controller.recording_directory
    model.flushRecords()
    assert controller.snapshot()["recording"]["save_path"]
    assert app is not None


def test_failed_archived_runs_retry_on_shutdown_without_an_active_simulator(tmp_path, monkeypatch):
    from core import controller as module

    original_writer = module.write_json_atomic

    def failing_writer(path, data):
        raise PermissionError("temporary storage outage")

    monkeypatch.setattr(module, "write_json_atomic", failing_writer)
    controller = SimulationController()
    controller.start()
    first_id = controller.snapshot()["recording"]["run_id"]
    controller.simulator.record_event("scout", "first unsaved run", target_id="first")
    controller.restart()
    second_id = controller.snapshot()["recording"]["run_id"]
    controller.simulator.record_event("sharing", "second unsaved run", target_id="second")
    controller.reset()
    assert controller.simulator is None
    assert controller.snapshot()["recording"]["unsaved_count"] == 2
    monkeypatch.setattr(module, "write_json_atomic", original_writer)
    assert controller.flush_records().ok
    snapshot = controller.snapshot()["recording"]
    assert snapshot["unsaved_count"] == 0
    assert snapshot["last_error"] == ""
    assert len(snapshot["history"]) == 2
    for run_id, target in ((first_id, "first"), (second_id, "second")):
        data = json.loads((controller.recording_directory / f"{run_id}.json").read_text(encoding="utf-8"))
        assert any(row.get("target_id") == target for row in data["records"])
        assert any(row["run_id"] == run_id and row["save_path"] for row in snapshot["history"])
