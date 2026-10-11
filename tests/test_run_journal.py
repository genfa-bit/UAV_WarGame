"""可配置模拟时钟及完整战局记录的确定性回归测试。"""

import json
import math

import pytest

from config import STATUS_SCOUT
from core.battlefield import Battlefield
from core.engagement import EngagementPhase
from core.simulator import Simulator
from core.units import CommandNode, ScoutDrone


def stationary_unit(unit_id, team, x, **kwargs):
    options = dict(id=unit_id, name=unit_id, team=team, x=x, y=200,
                   speed=0, attack_power=0, detect_range=0, reaction_delay=0,
                   hp=60, max_hp=60)
    options.update(kwargs)
    return ScoutDrone(**options)


def quiet_simulator(**kwargs):
    return Simulator(Battlefield(800, 600), [stationary_unit("red-1", "red", 200),
                                           stationary_unit("blue-1", "blue", 600)], **kwargs)


def rows(sim, category, event=None):
    return [row for row in sim.records if row["category"] == category
            and (event is None or row.get("event") == event)]


@pytest.mark.parametrize("duration", [True, "1", None, math.nan, math.inf, -math.inf,
                                      0, -1, 0.009, 60.001, 10 ** 1000])
def test_constructor_rejects_invalid_duration(duration):
    with pytest.raises(ValueError, match="单步时长"):
        quiet_simulator(step_duration_seconds=duration)


@pytest.mark.parametrize("maximum", [True, "4", None, 1.0, 0, -1, 1_000_001])
def test_constructor_rejects_invalid_limit(maximum):
    with pytest.raises(ValueError, match="最大运行步数"):
        quiet_simulator(max_steps=maximum)


@pytest.mark.parametrize("duration,maximum", [(0.01, 1), (60, 1_000_000)])
def test_configured_timing_accepts_both_boundaries(duration, maximum):
    sim = quiet_simulator(step_duration_seconds=duration, max_steps=maximum)
    assert sim.step_duration_seconds == duration
    assert sim.max_steps == maximum


def test_clock_accumulates_each_duration_and_final_result_is_stable():
    sim = quiet_simulator(step_duration_seconds=0.25, max_steps=5)
    sim.step()
    existing = json.loads(json.dumps(sim.records))
    sim.configure_timing(0.75, 4)
    settings = rows(sim, "settings", "timing_changed")
    assert settings[-1]["step"] == 1
    assert settings[-1]["elapsed_seconds"] == 0.25
    assert json.loads(json.dumps(sim.records[:len(existing)])) == existing
    count = len(sim.records)
    sim.configure_timing(0.75, 4)
    assert len(sim.records) == count
    sim.step()
    assert sim.elapsed_seconds == 1.0
    sim.step()
    sim.step()
    assert (sim.time_step, sim.elapsed_seconds, sim.winner, sim.finish_reason) == (4, 2.5, "draw", "step_limit")
    result = rows(sim, "result")
    assert len(result) == 1
    assert result[0]["elapsed_seconds"] == 2.5
    assert result[0]["step"] == 4
    before = json.loads(json.dumps(sim.records))
    for _ in range(3):
        sim.step()
    assert json.loads(json.dumps(sim.records)) == before
    assert sim.elapsed_seconds == 2.5
    with pytest.raises(ValueError, match="结束"):
        sim.configure_timing(0.5, 6)
    snapshot = sim.status_snapshot()
    assert snapshot["elapsed_seconds"] == 2.5
    assert snapshot["step_duration_seconds"] == 0.75
    assert snapshot["record_count"] == len(sim.records)


@pytest.mark.parametrize("duration,maximum", [(0.5, 1), (0.5, 0), (0.5, True),
                                             (math.nan, 20), (61, 20), (0.5, 1_000_001)])
def test_pause_timing_validation_is_atomic(duration, maximum):
    sim = quiet_simulator(step_duration_seconds=0.25, max_steps=10)
    sim.step()
    before = (sim.step_duration_seconds, sim.max_steps, len(sim.records), sim.elapsed_seconds)
    with pytest.raises(ValueError):
        sim.configure_timing(duration, maximum)
    assert (sim.step_duration_seconds, sim.max_steps, len(sim.records), sim.elapsed_seconds) == before


def test_full_history_preserves_text_beyond_visible_log_limit_and_sequences():
    sim = quiet_simulator()
    initial = len(sim.records)
    for i in range(30):
        sim._add_log("Attack", f"test event {i}", source_id="red-1", target_id="blue-1")
    assert len(sim.combat_logs) == 12
    assert len(sim.records) == initial + 30
    assert [row["message"] for row in rows(sim, "combat")] == [f"test event {i}" for i in range(30)]
    assert [row["seq"] for row in sim.records] == list(range(1, len(sim.records) + 1))
    assert sim.combat_logs[0] == "[Attack] test event 18"
    json.dumps(sim.records, ensure_ascii=False, allow_nan=False)


def test_tactical_baselines_and_only_actual_unit_or_team_changes_are_recorded():
    sim = quiet_simulator()
    initial_units = rows(sim, "tactical", "unit_state")
    assert len(initial_units) == 2
    assert all(row["initial"] and row["step"] == 0 for row in initial_units)
    assert len(rows(sim, "tactical", "team_state")) == 2
    count = len(sim.records)
    sim._record_unit_tactical_changes()
    sim._record_team_tactical_changes()
    assert len(sim.records) == count
    unit = sim.units[0]
    unit.status = STATUS_SCOUT
    unit.engagement_state.phase = EngagementPhase.REACTING
    unit.engagement_state.current_target_id = "blue-1"
    sim._record_unit_tactical_changes()
    change = rows(sim, "tactical", "unit_state")[-1]
    assert change["unit_id"] == "red-1"
    assert change["status"] == STATUS_SCOUT
    assert change["engagement"] == "REACTING"
    assert change["previous_engagement"] == "SEARCH"
    assert change["target_id"] == "blue-1"
    unit.hp = 1
    unit.ammo = 0
    sim._record_team_tactical_changes()
    assert len(rows(sim, "tactical", "team_state")) == 4
    sim._record_team_tactical_changes()
    assert len(rows(sim, "tactical", "team_state")) == 4


def test_observers_get_individual_detection_records_and_sharing_is_not_delivery():
    red = stationary_unit("r1", "red", 200, detect_range=50)
    red2 = stationary_unit("r2", "red", 201, detect_range=50)
    blue = stationary_unit("b1", "blue", 230)
    command = CommandNode(id="rc", name="rc", team="red", x=180, y=200,
                          detect_range=0, attack_power=0)
    sim = Simulator(Battlefield(800, 600), [red, red2, blue, command], step_duration_seconds=0.25)
    sim.step()
    detected = rows(sim, "scout", "detected")
    assert {row["source_id"] for row in detected if row["target_id"] == "b1"} == {"r1", "r2"}
    queued = rows(sim, "sharing", "queued")
    assert len(queued) == 1
    assert queued[0]["available_step"] == 4
    assert not rows(sim, "sharing", "delivered")
    sim.step()
    sim.configure_timing(0.5, 100)
    sim.step()
    assert not rows(sim, "sharing", "delivered")
    sim.step()
    delivered = rows(sim, "sharing", "delivered")
    assert len(delivered) == 1
    assert delivered[0]["target_id"] == "b1"
    assert delivered[0]["step"] == 4
    assert delivered[0]["elapsed_seconds"] == 1.5
    assert queued[0]["seq"] < delivered[0]["seq"]
    blue.x = 600
    sim.step()
    lost = rows(sim, "scout", "lost")
    assert {row["source_id"] for row in lost} == {"r1", "r2"}
    assert all(row["reason"] == "out_of_sight" for row in lost)
    while sim.time_step < 13:
        sim.step()
    expired = rows(sim, "sharing", "expired")
    assert len(expired) == 1 and expired[0]["delivered"] is True
    assert len(rows(sim, "sharing", "delivered")) == 1
    assert len(rows(sim, "scout", "detected")) == 2


def test_pending_target_can_expire_without_ever_being_delivered():
    red = stationary_unit("r1", "red", 200, detect_range=50)
    blue = stationary_unit("b1", "blue", 230)
    sim = Simulator(Battlefield(800, 600), [red, blue])
    sim.step()
    assert rows(sim, "sharing", "queued")[0]["available_step"] == 100
    blue.x = 600
    while sim.time_step < 10:
        sim.step()
    assert not rows(sim, "sharing", "delivered")
    expired = rows(sim, "sharing", "expired")
    assert len(expired) == 1
    assert expired[0]["delivered"] is False
    assert expired[0]["step"] == 10


def test_nearer_observer_accelerates_delivery_and_receives_correct_attribution():
    red = stationary_unit("far", "red", 200, detect_range=50)
    near = stationary_unit("near", "red", 100)
    blue = stationary_unit("b1", "blue", 230)
    command = CommandNode(id="rc", name="rc", team="red", x=100, y=200,
                          detect_range=0, attack_power=0)
    sim = Simulator(Battlefield(800, 600), [red, near, blue, command])
    sim.step()
    assert rows(sim, "sharing", "queued")[0]["available_step"] == 16
    near.detect_range = 150
    sim.step()
    rescheduled = rows(sim, "sharing", "rescheduled")
    assert len(rescheduled) == 1 and rescheduled[0]["source_id"] == "near"
    delivered = rows(sim, "sharing", "delivered")
    assert len(delivered) == 1
    assert delivered[0]["source_id"] == "near"
    assert delivered[0]["available_step"] == 2


def test_mutual_destruction_records_each_killer_once_at_cumulative_time(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.5)
    red = stationary_unit("r1", "red", 300, attack_power=100, attack_range=100)
    blue = stationary_unit("b1", "blue", 330, attack_power=100, attack_range=100)
    sim = Simulator(Battlefield(800, 600), [red, blue], step_duration_seconds=0.25)
    sim.step()
    sim.configure_timing(0.5, 100)
    red.detect_range = blue.detect_range = 100
    sim.step()
    assert sim.winner == "draw" and sim.finish_reason == "elimination"
    destroyed = {item["unit_id"]: item for item in sim.destroyed_units}
    assert set(destroyed) == {"r1", "b1"}
    assert destroyed["r1"]["killer_id"] == "b1"
    assert destroyed["b1"]["killer_id"] == "r1"
    assert all(item["step"] == 2 and item["elapsed_seconds"] == 0.75
               and not item["is_base"] for item in destroyed.values())
    assert len(rows(sim, "destroyed")) == 2
    assert sim.kill_count == {"red": 1, "blue": 1}
    assert len(rows(sim, "scout", "lost")) == 2
    assert all(row["step"] == 2 and row["elapsed_seconds"] == 0.75
               for row in rows(sim, "scout", "lost"))
    focus_cleared = [row for row in rows(sim, "tactical", "focus_changed")
                     if row["target_id"] is None]
    assert {row["team"] for row in focus_cleared} == {"red", "blue"}
    assert all(row["delivered"] is False for row in rows(sim, "sharing", "removed"))
    before = len(sim.records)
    sim.step()
    sim._update_destroyed_stats()
    sim._judge_winner()
    assert len(sim.records) == before
    assert len(rows(sim, "result")) == 1
    assert rows(sim, "result")[0]["seq"] > max(row["seq"] for row in rows(sim, "destroyed"))
    assert sim.records[-1]["category"] == "result"


def test_both_bases_have_destruction_time_and_known_killers(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.5)
    red = stationary_unit("r1", "red", 700, y=300, attack_power=400,
                          attack_range=100, detect_range=50)
    blue = stationary_unit("b1", "blue", 100, y=300, attack_power=400,
                           attack_range=100, detect_range=50)
    sim = Simulator(Battlefield(800, 600), [red, blue], step_duration_seconds=1.25)
    sim.step()
    assert sim.winner == "draw" and sim.finish_reason == "base_destroyed"
    destroyed = {item["unit_id"]: item for item in sim.destroyed_units}
    assert set(destroyed) == {"red_base", "blue_base"}
    assert destroyed["red_base"]["killer_id"] == "b1"
    assert destroyed["blue_base"]["killer_id"] == "r1"
    assert all(item["is_base"] and item["elapsed_seconds"] == 1.25
               for item in destroyed.values())
    assert len(rows(sim, "destroyed")) == 2
    assert len(rows(sim, "scout", "detected")) == 2


def test_external_destruction_uses_unknown_killer_and_fresh_run_clears_history():
    sim = quiet_simulator()
    sim.units[0].hp = 0
    sim.battlefield.base_obj("red").hp = 0
    sim.step()
    assert len(sim.destroyed_units) == 2
    assert all(item["killer_id"] is None and item["killer_name"] is None
               for item in sim.destroyed_units)
    fresh = quiet_simulator()
    assert fresh.destroyed_units == []
    assert fresh.elapsed_seconds == 0
    assert not rows(fresh, "destroyed")
    assert not rows(fresh, "result")
    assert fresh.records[0]["seq"] == 1
