"""控制器回放模式的回归测试：进入/退出、游标、记录过滤与写入抑制。"""

import json
from pathlib import Path

import pytest

from config import (GAME_DEPLOYMENT, GAME_FINISHED, GAME_PAUSED, GAME_REPLAY,
                    GAME_REPLAY_PAUSED, GAME_RUNNING)
from core.controller import DEFAULT_SCENARIO_PATH, SimulationController
from core.map_persistence import read_json_document


@pytest.fixture(autouse=True)
def isolated_record_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))


def finished_controller(max_steps=120, duration=0.2):
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.set_timing(duration, max_steps).ok
    assert controller.start().ok
    while controller.game_state == GAME_RUNNING:
        assert controller.advance().ok
    return controller


def journal_files(controller):
    return {path.name: path.read_bytes()
            for path in controller.recording_directory.glob("*.json")}


def journal_path(controller):
    return Path(controller._record_save_path)


def test_replay_opens_paused_at_the_first_frame():
    controller = finished_controller()
    final_step = controller.simulator.time_step
    unit_ids = [row["id"] for row in controller.snapshot()["units"]]
    assert controller.simulator.frame_buffer.frame_count == final_step + 1

    assert controller.replay_run(journal_path(controller)).ok
    snapshot = controller.snapshot()
    assert snapshot["game_state"] == GAME_REPLAY_PAUSED
    assert snapshot["state_label"] == "回放暂停"
    # 默认停在第一帧（部署帧），所以进度条、累计时间与运行记录都从开头起算。
    assert snapshot["replay"] == {
        "active": True, "playing": False, "cursor": 0, "frame_count": final_step + 1,
        "max_step": final_step, "run_id": controller._run_id,
        "scene_name": controller.scene_name,
        "step_duration_seconds": pytest.approx(0.2),
        "elapsed_seconds": pytest.approx(0.0, abs=1e-9),
        "records_up_to": len(controller._replay.records_up_to(0)),
        "finished": controller._replay.finished,
    }
    # 单位行与实时快照形状一致，且顺序稳定（QML 才能走逐角色动画）。
    assert [row["id"] for row in snapshot["units"]] == unit_ids
    assert snapshot["units"][0]["engagement_label"] in {"搜索", "反应", "攻击", "冷却"}
    json.dumps(snapshot, ensure_ascii=False, allow_nan=False)


def test_playing_pausing_and_stepping_move_the_cursor():
    controller = finished_controller()
    assert controller.replay_run(journal_path(controller)).ok
    # 进入回放就停在第一帧，不需要先定位。
    assert controller.snapshot()["replay"]["cursor"] == 0

    assert controller.toggle_pause().ok
    assert controller.game_state == GAME_REPLAY
    assert controller.snapshot()["replay"]["playing"] is True

    assert controller.advance().ok
    assert controller.snapshot()["replay"]["cursor"] == 1

    assert controller.toggle_pause().ok
    assert controller.game_state == GAME_REPLAY_PAUSED
    assert controller.step().ok
    assert controller.snapshot()["replay"]["cursor"] == 2

    assert controller.replay_step(-1).ok
    assert controller.snapshot()["replay"]["cursor"] == 1
    assert controller.seek_replay(-50).ok
    assert controller.snapshot()["replay"]["cursor"] == 0
    assert controller.seek_replay(10 ** 6).ok
    assert controller.snapshot()["replay"]["cursor"] == controller._replay.max_step


def test_playing_to_the_end_pauses_and_reports_finished():
    controller = finished_controller(max_steps=12)
    assert controller.replay_run(journal_path(controller)).ok
    assert controller.toggle_pause().ok
    while controller.game_state == GAME_REPLAY:
        assert controller.advance().ok
    assert controller.game_state == GAME_REPLAY_PAUSED
    assert controller.last_message == "回放结束"
    assert controller.snapshot()["replay"]["cursor"] == controller._replay.max_step
    # 末帧之后继续推进只重复结束提示，不越界。
    assert controller.advance().ok is False


def test_replay_opens_at_the_deployment_frame():
    """进入回放默认就在第一帧，不需要先定位：画的正是这一局的部署态。"""
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.start().ok
    deployment = {unit.id: (unit.x, unit.y) for unit in controller.simulator.units}
    while controller.game_state == GAME_RUNNING:
        assert controller.advance().ok
    assert controller.replay_run(journal_path(controller)).ok

    snapshot = controller.snapshot()
    assert snapshot["replay"]["cursor"] == 0
    for row in snapshot["units"]:
        x, y = deployment[row["id"]]
        assert row["x"] == pytest.approx(x, abs=0.05)
        assert row["y"] == pytest.approx(y, abs=0.05)
        assert row["destroyed"] is False
        assert row["destroyed_step"] is None
    assert snapshot["statistics"]["time_step"] == 0
    assert snapshot["attack_events"] == []


def test_recording_panel_follows_the_cursor():
    controller = finished_controller()
    assert controller.replay_run(journal_path(controller)).ok
    total = len(controller._replay.records)

    assert controller.seek_replay(0).ok
    early = controller.snapshot()["recording"]
    assert early["record_count"] == len(controller._replay.records_up_to(0))
    assert early["record_count"] < total
    assert early["replayable"] is True

    assert controller.seek_replay(controller._replay.max_step).ok
    late = controller.snapshot()["recording"]
    assert late["record_count"] == total
    assert late["run_id"] == controller._replay_run_id
    assert late["save_path"] == controller._replay_save_path


def test_exiting_replay_returns_to_the_pre_replay_deployment():
    controller = finished_controller()
    expected = {unit.id: (unit.x, unit.y) for unit in controller._run_deployment[1]}
    assert controller.replay_run(journal_path(controller)).ok
    assert controller.seek_replay(0).ok

    assert controller.exit_replay().ok
    snapshot = controller.snapshot()
    assert snapshot["game_state"] == GAME_DEPLOYMENT
    assert snapshot["replay"]["active"] is False
    assert snapshot["show_wrecks"] is True
    deployed = {row["id"]: (row["x"], row["y"]) for row in snapshot["units"]}
    assert deployed == expected


def test_replay_started_from_deployment_keeps_the_layout_being_edited():
    controller = finished_controller(max_steps=20)
    path = journal_path(controller)
    assert controller.reset().ok
    # 返回部署后继续编辑：这份布局既不是上一局开跑前的部署，也不是场景初始部署。
    edited_unit = controller.deployment.deploy_units[0]
    edited_unit.x = min(controller.battlefield.width - 5, edited_unit.x + 40)
    expected = {row["id"]: (row["x"], row["y"]) for row in controller.snapshot()["units"]}
    assert controller._run_deployment is None
    assert expected != {unit.id: (unit.x, unit.y) for unit in controller._initial_deployment[1]}

    assert controller.replay_run(path).ok
    assert controller.game_state == GAME_REPLAY_PAUSED
    assert controller.exit_replay().ok
    assert controller.game_state == GAME_DEPLOYMENT
    deployed = {row["id"]: (row["x"], row["y"]) for row in controller.snapshot()["units"]}
    assert deployed == expected


def test_replaying_never_writes_or_overwrites_a_journal():
    controller = finished_controller(max_steps=20)
    assert controller.replay_run(journal_path(controller)).ok
    before = journal_files(controller)
    assert before  # 本局记录已经存在

    controller.toggle_pause()
    for _ in range(5):
        controller.advance()
    controller.seek_replay(0)
    assert controller.flush_records().ok
    assert controller.toggle_wrecks().ok
    assert controller.exit_replay().ok

    assert journal_files(controller) == before


def test_replay_blocks_commands_that_would_need_a_live_run(tmp_path):
    controller = finished_controller()
    assert controller.replay_run(journal_path(controller)).ok

    assert not controller.save_map(tmp_path / "map.json").ok
    assert "回放中" in controller.last_message
    assert not controller.restart().ok
    assert not controller.set_timing(1.0, 500).ok
    assert controller.snapshot()["timing"]["editable"] is False
    assert not (tmp_path / "map.json").exists()


def test_wreck_visibility_toggles_without_a_simulator():
    controller = finished_controller()
    assert controller.replay_run(journal_path(controller)).ok

    assert controller.snapshot()["show_wrecks"] is True
    assert controller.toggle_wrecks().ok
    assert controller.snapshot()["show_wrecks"] is False
    assert controller.last_message == "已隐藏残骸"


def test_old_schema_two_records_are_listed_but_not_replayable(tmp_path):
    controller = finished_controller(max_steps=12)
    legacy = read_json_document(journal_path(controller))
    legacy.pop("replay")
    legacy.pop("map")
    legacy["schema_version"] = 2
    legacy["run_id"] = "20200101T000000000000Z-legacy"
    legacy_path = controller.recording_directory / f"{legacy['run_id']}.json"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    fresh = SimulationController(DEFAULT_SCENARIO_PATH)
    history = {row["run_id"]: row for row in fresh.snapshot()["recording"]["history"]}
    assert legacy["run_id"] in history
    assert history[legacy["run_id"]]["replayable"] is False
    assert history[controller._run_id]["replayable"] is True

    result = fresh.replay_run(legacy_path)
    assert not result.ok
    assert "旧版本" in result.message
    assert fresh.snapshot()["replay"]["active"] is False


def test_replay_survives_a_second_controller_reading_the_same_file():
    controller = finished_controller(max_steps=60)
    path = journal_path(controller)
    assert controller.replay_run(path).ok
    assert controller.seek_replay(3).ok
    expected = [(row["id"], row["x"], row["y"]) for row in controller.snapshot()["units"]]

    other = SimulationController(DEFAULT_SCENARIO_PATH)
    assert other.replay_run(path).ok
    assert other.seek_replay(3).ok
    assert [(row["id"], row["x"], row["y"]) for row in other.snapshot()["units"]] == expected


def test_replay_reports_a_missing_or_corrupt_file(tmp_path):
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert not controller.replay_run(tmp_path / "missing.json").ok
    assert "无法读取" in controller.last_message

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert not controller.replay_run(broken).ok

    unknown = tmp_path / "unknown.json"
    unknown.write_text(json.dumps({"schema_version": 9, "run_id": "x"}), encoding="utf-8")
    assert not controller.replay_run(unknown).ok
    assert "版本" in controller.last_message
    assert controller.snapshot()["replay"]["active"] is False


def test_replay_without_a_previous_deployment_is_rejected():
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert not controller.exit_replay().ok
    assert not controller.seek_replay(3).ok
