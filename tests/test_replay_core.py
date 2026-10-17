"""运行记录逐帧回放数据（schema 3 replay 块）的核心回归测试。"""

import json
from copy import deepcopy

import pytest

from config import (GAME_RUNNING, STATUS_ATTACK, STATUS_DESTROYED, STATUS_EVADE,
                    STATUS_MOVE, STATUS_SCOUT, TEAM_BLUE, TEAM_RED)
from core.battlefield import Battlefield
from core.controller import DEFAULT_SCENARIO_PATH, SimulationController
from core.engagement import EngagementPhase
from core.replay import (ATTACK_EVENT_LIFE, ENGAGEMENT_CODES, FIELD_LAYOUT,
                         POSITION_SCALE, STATUS_CODES, FrameBuffer, ReplayError,
                         ReplayTrack, decode_frames, encode_replay_block,
                         pack_unit)
from core.simulator import Simulator
from core.units import ScoutDrone


@pytest.fixture(autouse=True)
def isolated_record_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))


@pytest.fixture
def always_hits(monkeypatch):
    """固定命中与暴击骰子，让对战过程可复现。"""
    monkeypatch.setattr("core.combat.random.random", lambda: 0.0)


def run_to_finish(max_steps=30, duration=0.2):
    """跑完一局并记录每步的实时状态，返回 (controller, 逐步实时快照)。"""
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.set_timing(duration, max_steps).ok
    assert controller.start().ok
    live_units = {0: {unit.id: unit_snapshot(unit) for unit in controller.simulator.units}}
    live_events = {0: deepcopy(controller._attack_event_snapshot())}
    while controller.game_state == GAME_RUNNING:
        assert controller.advance().ok
        simulator = controller.simulator
        live_units[simulator.time_step] = {
            unit.id: unit_snapshot(unit) for unit in simulator.units}
        live_events[simulator.time_step] = deepcopy(controller._attack_event_snapshot())
    return controller, live_units, live_events


def unit_snapshot(unit):
    return (unit.x, unit.y, unit.hp, unit.ammo, unit.status,
            unit.engagement_state.phase_name, unit.is_destroyed)


def strip_event_ids(events):
    return [{key: value for key, value in row.items() if key != "event_id"} for row in events]


def test_packed_fields_cover_every_status_and_engagement_phase():
    """码表冻结：新增状态或阶段必须先追加到码表，否则回放会读到错误的索引。"""
    assert FIELD_LAYOUT == ("x", "y", "hp", "ammo", "status", "engagement", "destroyed")
    for status in (STATUS_SCOUT, STATUS_MOVE, STATUS_ATTACK, STATUS_EVADE, STATUS_DESTROYED):
        assert status in STATUS_CODES
    assert len(STATUS_CODES) == 5
    assert len(ENGAGEMENT_CODES) == len(EngagementPhase)
    assert set(ENGAGEMENT_CODES) == {"搜索", "反应", "攻击", "冷却"}


def test_frame_buffer_freezes_unit_order_including_bases():
    battlefield = Battlefield(800, 600)
    units = [ScoutDrone(id="red-1", name="R", team=TEAM_RED, x=100, y=100, speed=0),
             ScoutDrone(id="blue-1", name="B", team=TEAM_BLUE, x=700, y=100, speed=0)]
    simulator = Simulator(battlefield, units, max_steps=5, step_duration_seconds=0.2)

    buffer = simulator.frame_buffer
    assert buffer.unit_ids == ["red-1", "blue-1", "red_base", "blue_base"]
    assert buffer.frame_count == 1  # 部署帧
    for _ in range(3):
        simulator.step()
    assert buffer.frame_count == simulator.time_step + 1 == 4


def test_pack_unit_encodes_scaled_positions_and_phase_codes():
    unit = ScoutDrone(id="red-1", name="R", team=TEAM_RED, x=89.44, y=111.36, speed=0)
    unit.status = STATUS_ATTACK
    values = pack_unit(unit)
    assert len(values) == len(FIELD_LAYOUT)
    assert values[:2] == [round(89.44 * POSITION_SCALE), round(111.36 * POSITION_SCALE)]
    assert values[4] == STATUS_CODES.index(STATUS_ATTACK)
    assert values[5] == ENGAGEMENT_CODES.index(unit.engagement_state.phase_name)
    assert values[6] == 0


def test_encode_and_decode_round_trip_preserves_every_step(always_hits):
    controller, live_units, _ = run_to_finish()
    payload = controller._run_payload()
    track = ReplayTrack.from_payload(payload)

    assert track.frame_count == controller.simulator.time_step + 1
    assert track.frame_count == len(live_units)
    assert track.unit_ids == list(controller.simulator.frame_buffer.unit_ids)
    for step, expected in live_units.items():
        frame = track.frame(step)
        for unit_id, (x, y, hp, ammo, status, phase, destroyed) in expected.items():
            values = frame[unit_id]
            assert values[0] / track.scale == pytest.approx(x, abs=0.05)
            assert values[1] / track.scale == pytest.approx(y, abs=0.05)
            assert values[2] == hp
            assert values[3] == ammo
            assert STATUS_CODES[values[4]] == status
            assert ENGAGEMENT_CODES[values[5]] == phase
            assert bool(values[6]) is destroyed


def test_first_frame_is_the_deployment_state_without_any_step():
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.start().ok
    track = ReplayTrack.from_payload(controller._run_payload())

    assert track.frame_count == 1
    assert track.max_step == 0
    frame = track.frame(0)
    for unit in controller.simulator.units:
        assert frame[unit.id][0] / track.scale == pytest.approx(unit.x, abs=0.05)
    assert track.statistics(0)["time_step"] == 0
    assert track.statistics(0)["elapsed_seconds"] == 0.0


def test_reconstructed_attack_events_match_the_live_snapshot(always_hits):
    controller, _, live_events = run_to_finish(max_steps=120)
    track = ReplayTrack.from_payload(controller._run_payload())

    assert any(live_events[step] for step in live_events), "这一局应当发生过攻击"
    for step, expected in live_events.items():
        actual = track.attack_events(step)
        assert len(actual) == len(expected)
        for mine, theirs in zip(actual, strip_event_ids(expected)):
            assert mine["attacker_id"] == theirs["attacker_id"]
            assert mine["target_id"] == theirs["target_id"]
            assert mine["attacker_team"] == theirs["attacker_team"]
            assert mine["attacker_type"] == theirs["attacker_type"]
            assert mine["damage"] == theirs["damage"]
            assert mine["target_hp"] == theirs["target_hp"]
            assert mine["critical"] == theirs["critical"]
            assert mine["miss"] == theirs["miss"]
            assert mine["target_destroyed"] == theirs["target_destroyed"]
            assert mine["life"] == theirs["life"]
            assert 1 <= mine["life"] <= ATTACK_EVENT_LIFE
            for index in (0, 1):
                assert mine["start"][index] == pytest.approx(theirs["start"][index], abs=0.05)
                assert mine["end"][index] == pytest.approx(theirs["end"][index], abs=0.05)
    assert any(row["life"] == ATTACK_EVENT_LIFE
               for step in live_events for row in live_events[step])


def test_attack_lines_persist_for_a_short_tail_then_expire(always_hits):
    controller, _, live_events = run_to_finish(max_steps=120)
    track = ReplayTrack.from_payload(controller._run_payload())
    first_step = min(step for step in live_events if live_events[step])
    prefix = f"{first_step}:"

    def lines_from_first_step(step):
        return [row for row in track.attack_events(step) if row["event_id"].startswith(prefix)]

    assert all(row["life"] == ATTACK_EVENT_LIFE for row in lines_from_first_step(first_step))
    assert all(row["life"] == 1 for row in lines_from_first_step(first_step + ATTACK_EVENT_LIFE - 1))
    assert lines_from_first_step(first_step + ATTACK_EVENT_LIFE) == []


def test_statistics_follow_the_cursor_and_keep_qualitative_final_fields(always_hits):
    controller, _, _ = run_to_finish(max_steps=120)
    payload = controller._run_payload()
    track = ReplayTrack.from_payload(payload)
    final = payload["statistics"]

    start = track.statistics(0)
    assert start["time_step"] == 0
    assert start["elapsed_seconds"] == 0.0
    assert start["record_count"] < final["record_count"]
    assert start["winner"] == final["winner"]  # 定性字段沿用该局最终值
    assert start["red_remaining"] + start["blue_remaining"] > 0

    tail = track.statistics(track.max_step)
    assert tail["time_step"] == track.max_step
    assert tail["elapsed_seconds"] == pytest.approx(
        track.max_step * track.step_duration_seconds, abs=1e-9)
    assert tail["red_remaining"] == final["red_remaining"]
    assert tail["blue_remaining"] == final["blue_remaining"]
    assert tail["red_destroyed"] == final["red_destroyed"]
    assert tail["blue_destroyed"] == final["blue_destroyed"]
    assert tail["red_attacks"] == final["red_attacks"]
    assert tail["blue_hits"] == final["blue_hits"]
    assert tail["red_damage"] == final["red_damage"]
    assert tail["red_base_hp"] == final["red_base_hp"]
    assert tail["blue_base_hp"] == final["blue_base_hp"]
    assert tail["record_count"] == final["record_count"]


def test_records_destroyed_and_logs_are_filtered_by_the_cursor(always_hits):
    controller, _, _ = run_to_finish(max_steps=120)
    payload = controller._run_payload()
    track = ReplayTrack.from_payload(payload)
    midpoint = track.max_step // 2

    early = track.records_up_to(midpoint)
    assert early == [row for row in payload["records"] if row["step"] <= midpoint]
    assert len(early) < len(payload["records"])
    assert all(row["step"] <= midpoint for row in track.destroyed_up_to(midpoint))
    logs = track.logs_up_to(midpoint)
    assert len(logs) <= 12
    assert all(line.startswith("[") for line in logs)
    assert track.logs_up_to(track.max_step) == payload["logs"][-12:]


def test_journal_block_is_json_safe_and_stays_small():
    controller, _, _ = run_to_finish(max_steps=200)
    payload = controller._run_payload()
    block = payload["replay"]

    json.dumps(payload, ensure_ascii=False, allow_nan=False)
    assert block["dtype"] == "int16" and block["scale"] == POSITION_SCALE
    assert block["frame_count"] == payload["statistics"]["time_step"] + 1
    # 每单位每帧 7 个 int16，base64 后约为 14 字节的 4/3。
    raw = block["frame_count"] * block["unit_count"] * len(FIELD_LAYOUT) * 2
    assert len(block["frames"]) <= raw * 4 // 3 + 4
    assert payload["map"]["width"] == controller.battlefield.width
    assert payload["map"]["red_base"]["hp"] is not None
    assert all("selected" not in row for row in payload["map"]["obstacles"])


def test_decoder_rejects_corrupt_or_truncated_buffers():
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.start().ok
    block = controller._run_payload()["replay"]

    with pytest.raises(ReplayError, match="没有回放数据"):
        ReplayTrack.from_payload({"run_id": "old"})
    broken = dict(block)
    broken["frame_count"] = block["frame_count"] + 5
    with pytest.raises(ReplayError, match="长度不一致"):
        decode_frames(broken)
    with pytest.raises(ReplayError, match="无法解码"):
        decode_frames(dict(block, frames="not base64!!"))
    with pytest.raises(ReplayError, match="字节长度无效"):
        decode_frames(dict(block, frames="eA=="))


def test_replay_clock_preserves_mid_run_timing_changes():
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.set_timing(0.2, 20).ok
    assert controller.start().ok
    for _ in range(5):
        assert controller.advance().ok
    assert controller.toggle_pause().ok
    assert controller.set_timing(0.5, 20).ok
    assert controller.toggle_pause().ok
    for _ in range(5):
        assert controller.advance().ok

    track = ReplayTrack.from_payload(controller._run_payload())
    assert track.timing_at(5) == pytest.approx((0.5, 1.0))
    assert track.timing_at(10) == pytest.approx((0.5, 3.5))
    assert track.statistics(10)["elapsed_seconds"] == pytest.approx(3.5)


def test_replay_clock_handles_repeated_changes_at_same_step():
    controller = SimulationController(DEFAULT_SCENARIO_PATH)
    assert controller.set_timing(0.2, 20).ok
    assert controller.start().ok
    for _ in range(5):
        assert controller.advance().ok
    assert controller.toggle_pause().ok
    assert controller.set_timing(0.5, 20).ok
    assert controller.set_timing(1.0, 20).ok
    assert controller.toggle_pause().ok
    assert controller.advance().ok
    track = ReplayTrack.from_payload(controller._run_payload())
    assert track.timing_at(0) == pytest.approx((0.2, 0.0))
    assert track.timing_at(4) == pytest.approx((0.2, 0.8))
    assert track.timing_at(5) == pytest.approx((1.0, 1.0))
    assert track.timing_at(6) == pytest.approx((1.0, 2.0))


def test_replay_clock_falls_back_for_records_without_timing_events():
    controller, _, _ = run_to_finish(max_steps=10, duration=0.2)
    payload = controller._run_payload()
    payload["records"] = []
    track = ReplayTrack.from_payload(payload)
    assert track.timing_at(5) == pytest.approx((0.2, 1.0))


def test_empty_frame_buffer_encodes_an_empty_track():
    buffer = FrameBuffer(["red_base", "blue_base"])
    assert buffer.frame_count == 0
    assert buffer.encode() == ""
    assert encode_replay_block(buffer, {})["unit_count"] == 2
