"""Workflow regressions for sighting delivery, engagement and combat reporting."""

from unittest.mock import patch

import pytest

from config import DETECTION_TIMEOUT_STEPS, STATUS_EVADE, TARGET_LOCK_TIME
from core import pathfinding
from core.battlefield import Battlefield, Obstacle
from core.controller import SimulationController
from core.engagement import EngagementPhase
from core.simulator import Simulator
from core.target_pool import TargetPool
from core.unit_config_loader import get_unit_stats
from core.units import (CommandNode, GroundVehicle, MissileVehicle,
                        ScoutDrone, StrikeDrone)


def test_continuous_observation_keeps_initial_delivery_deadline():
    target = CommandNode(id="blue", name="Blue", team="blue", x=180, y=100)
    pool = TargetPool()

    assert pool.sight(target, step=1, available_step=4)
    for step in range(2, 5):
        assert not pool.sight(target, step=step, available_step=step + 3)
        assert pool.last_seen_step(target.id) == step
        assert pool.values_available(step) == ([] if step < 4 else [target])


def test_nearer_observer_can_deliver_pending_information_sooner():
    target = CommandNode(id="blue", name="Blue", team="blue", x=180, y=100)
    pool = TargetPool()
    pool.sight(target, step=1, available_step=20)
    pool.sight(target, step=2, available_step=4)

    assert pool.values_available(3) == []
    assert pool.values_available(4) == [target]


def _sharing_simulator():
    observer = ScoutDrone(id="observer", name="Observer", team="red", x=100, y=100,
                          speed=0, attack_power=0, detect_range=100, reaction_delay=0)
    receiver = MissileVehicle(id="receiver", name="Receiver", team="red", x=50, y=100,
                              speed=0, detect_range=5, reaction_delay=2)
    command = CommandNode(id="command", name="Command", team="red", x=80, y=100,
                          detect_range=0)
    target = CommandNode(id="target", name="Target", team="blue", x=180, y=100,
                         detect_range=0)
    return Simulator(Battlefield(800, 600), [observer, receiver, command, target]), observer, receiver, target


def test_delivered_shared_sighting_starts_receivers_reaction_period():
    simulator, _, receiver, target = _sharing_simulator()

    for _ in range(3):
        simulator.step()
        assert receiver.engagement_state.phase == EngagementPhase.SEARCH
        assert target.id not in simulator._own_sightings[receiver.id]
        assert simulator._attack_target_for(receiver) is None

    simulator.step()

    assert simulator.time_step == 4
    assert receiver.engagement_state.phase == EngagementPhase.REACTING
    assert receiver.engagement_state.current_target_id == target.id
    assert receiver.engagement_state.reaction_progress == 0
    assert simulator._attack_target_for(receiver) is target


def test_unreceived_team_focus_does_not_leak_into_movement_or_evasion_attack(monkeypatch):
    simulator, observer, receiver, target = _sharing_simulator()
    simulator.time_step = 1
    simulator._reconnaissance_phase()
    simulator._select_focus_targets()
    assert simulator.focus_targets["red"] is target
    movements = {}

    def record_movement(**kwargs):
        movements[kwargs["unit"].id] = kwargs
        return False

    monkeypatch.setattr(simulator.strategy, "move_unit", record_movement)
    simulator._movement_phase()

    assert movements[observer.id]["target"] is target
    assert movements[receiver.id]["target"] is None
    assert movements[receiver.id]["visible_enemies"] == []
    assert movements[receiver.id]["all_enemies"] == []
    receiver.status = STATUS_EVADE
    assert simulator._attack_target_for(receiver) is None


def test_leaving_detection_range_clears_own_sighting_and_reaction_in_same_step():
    observer = ScoutDrone(id="red", name="Observer", team="red", x=100, y=100,
                          speed=0, attack_power=0, detect_range=80, reaction_delay=3)
    target = CommandNode(id="blue", name="Target", team="blue", x=140, y=100,
                         detect_range=0)
    simulator = Simulator(Battlefield(800, 600), [observer, target])
    simulator.step()
    assert observer.engagement_state.phase == EngagementPhase.REACTING
    assert observer.engagement_state.reaction_progress == 0
    target.x = 400

    simulator.step()

    assert simulator._own_sightings[observer.id] == set()
    assert observer.engagement_state.phase == EngagementPhase.SEARCH
    assert observer.engagement_state.current_target_id is None
    assert simulator.focus_targets["red"] is None
    assert simulator._attack_target_for(observer) is None


def test_shared_sighting_expires_after_last_observation():
    simulator, _, receiver, target = _sharing_simulator()
    simulator.time_step = 4
    simulator.red_detected_targets.sight(target, step=1, available_step=4)
    simulator._update_engagement_states()
    assert receiver.engagement_state.phase == EngagementPhase.REACTING
    simulator.time_step = 1 + DETECTION_TIMEOUT_STEPS + 1

    simulator._cleanup_target_pools()
    simulator._update_engagement_states()

    assert target.id not in simulator.red_detected_targets
    assert receiver.engagement_state.phase == EngagementPhase.SEARCH


def test_focus_lock_expires_and_higher_threat_can_be_selected():
    friendly = GroundVehicle(id="red", name="Red", team="red", x=100, y=100)
    low = ScoutDrone(id="low", name="Low", team="blue", x=180, y=100)
    high = MissileVehicle(id="high", name="High", team="blue", x=180, y=110)
    simulator = Simulator(Battlefield(800, 600), [friendly, low, high])
    simulator.red_detected_targets.sight(low, step=0)
    simulator._select_focus_targets()
    assert simulator.focus_targets["red"] is low
    simulator.red_detected_targets.sight(high, step=0)
    for _ in range(TARGET_LOCK_TIME - 1):
        simulator.strategy.behavior_mgr.tick_target_locks()
        simulator._select_focus_targets()
        assert simulator.focus_targets["red"] is low

    simulator.strategy.behavior_mgr.tick_target_locks()
    simulator._select_focus_targets()

    assert simulator.focus_targets["red"] is high
    assert simulator.focus_lock["red"] == high.id


def test_expired_lock_is_cleared_when_same_focus_remains():
    friendly = GroundVehicle(id="red", name="Red", team="red", x=100, y=100)
    target = ScoutDrone(id="blue", name="Blue", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [friendly, target])
    simulator.red_detected_targets.sight(target, step=0)
    simulator._select_focus_targets()
    for _ in range(TARGET_LOCK_TIME):
        simulator.strategy.behavior_mgr.tick_target_locks()

    simulator._select_focus_targets()

    assert simulator.focus_targets["red"] is target
    assert simulator.focus_lock["red"] is None


def test_missed_shot_counts_as_attack_but_not_hit_or_damage():
    attacker = StrikeDrone(id="red", name="Red", team="red", x=100, y=100,
                           base_hit_prob=0)
    target = CommandNode(id="blue", name="Blue", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [attacker, target])
    original_hp = target.hp
    original_ammo = attacker.ammo
    with patch("core.combat.random.random", return_value=1.0):
        assert simulator.combat.queue_attack(attacker, target, simulator.battlefield)
        simulator._resolve_attacks()

    snapshot = simulator.status_snapshot()
    assert attacker.ammo == original_ammo - 1
    assert target.hp == original_hp
    assert snapshot["red_attacks"] == 1
    assert snapshot["red_hits"] == 0
    assert snapshot["red_damage"] == 0
    assert simulator.attack_events[0].is_miss


def test_successful_shot_counts_as_attack_and_hit():
    attacker = StrikeDrone(id="red", name="Red", team="red", x=100, y=100)
    target = CommandNode(id="blue", name="Blue", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [attacker, target])
    with patch("core.combat.random.random", side_effect=[1.0, 0.0]):
        assert simulator.combat.queue_attack(attacker, target, simulator.battlefield)
        simulator._resolve_attacks()

    snapshot = simulator.status_snapshot()
    assert snapshot["red_attacks"] == 1
    assert snapshot["red_hits"] == 1
    assert snapshot["red_damage"] == attacker.attack_power


@pytest.mark.parametrize("unit_class", [ScoutDrone, StrikeDrone, GroundVehicle, MissileVehicle, CommandNode])
def test_resupply_uses_each_units_configured_ammo_limit(unit_class):
    battlefield = Battlefield(800, 600)
    base = battlefield.base_obj("red")
    unit = unit_class(id="red", name="Red", team="red", x=base.x, y=base.y,
                      ammo=0, hp=1)
    simulator = Simulator(battlefield, [unit])
    max_ammo = get_unit_stats(unit.unit_type)["ammo"]
    for step in range(40):
        simulator.time_step = step
        simulator._replenish_phase()
        assert 0 <= unit.ammo <= max_ammo
        assert unit.hp <= unit.max_hp

    assert unit.ammo == max_ammo


def test_ammo_resupply_keeps_two_step_cadence():
    battlefield = Battlefield(800, 600)
    base = battlefield.base_obj("red")
    unit = ScoutDrone(id="red", name="Red", team="red", x=base.x, y=base.y, ammo=0)
    simulator = Simulator(battlefield, [unit])
    for step, expected_ammo in [(1, 1), (2, 1), (3, 2)]:
        simulator.time_step = step
        simulator._replenish_phase()
        assert unit.ammo == expected_ammo


def test_new_run_with_same_unit_id_does_not_inherit_previous_obstacle_route():
    old_field = Battlefield(800, 600, obstacles=[Obstacle(100, 80, 40, 80)])
    old_unit = GroundVehicle(id="reused", name="Red", team="red", x=99, y=120)
    Simulator(old_field, [old_unit])
    assert pathfinding.move_to(old_unit, 200, 120, old_field)
    assert old_unit.id in pathfinding._EDGE_FOLLOW
    # Include a previous corner escape, which also caches a stuck counter.
    pathfinding._corner_escape(old_unit, 200, 120, old_field)
    assert old_unit.id in pathfinding._STUCK_COUNTERS

    new_field = Battlefield(800, 600, obstacles=[Obstacle(80, 100, 80, 40)])
    new_unit = GroundVehicle(id="reused", name="Red", team="red", x=120, y=99)
    new_simulator = Simulator(new_field, [new_unit])
    reference = GroundVehicle(id="fresh", name="Reference", team="red", x=120, y=99)

    assert new_simulator.time_step == 0
    assert new_unit.id not in pathfinding._EDGE_FOLLOW
    assert new_unit.id not in pathfinding._EDGE_FOLLOW_DURATION
    assert new_unit.id not in pathfinding._STUCK_COUNTERS
    assert pathfinding.move_to(new_unit, 120, 200, new_field)
    assert pathfinding.move_to(reference, 120, 200, new_field)
    assert (new_unit.x, new_unit.y) == (reference.x, reference.y)
    assert new_unit.x < 120 and new_unit.y == 99
    pathfinding.cleanup_destroyed(set())


def _standoff_units():
    return [
        CommandNode(id="red", name="Red command", team="red", x=50, y=50),
        CommandNode(id="blue", name="Blue command", team="blue", x=750, y=50),
    ]


@pytest.mark.parametrize("invalid_limit", [0, -1, True, 1.5, None, "20"])
def test_simulation_limit_must_be_a_positive_integer(invalid_limit):
    with pytest.raises(ValueError, match="正整数"):
        Simulator(Battlefield(800, 600), _standoff_units(), max_steps=invalid_limit)


def test_persistent_standoff_finishes_at_configured_limit_without_changing_combat():
    units = _standoff_units()
    simulator = Simulator(Battlefield(800, 600), units, max_steps=3)
    initial_hp = [unit.hp for unit in units]
    for step in range(1, 3):
        simulator.step()
        assert simulator.time_step == step
        assert simulator.winner is None
        assert simulator.finish_reason is None

    simulator.step()

    snapshot = simulator.status_snapshot()
    assert snapshot["time_step"] == snapshot["max_steps"] == 3
    assert snapshot["winner"] == "draw"
    assert snapshot["finish_reason"] == "step_limit"
    assert [unit.hp for unit in units] == initial_hp
    assert snapshot["red_attacks"] == snapshot["blue_attacks"] == 0
    assert any("达到时间步上限（3），本局平局" in line for line in simulator.combat_logs)
    for _ in range(5):
        simulator.step()
    assert simulator.time_step == 3
    assert sum(line.startswith("[Result]") for line in simulator.combat_logs) == 1


@pytest.mark.parametrize("winner", ["red", "blue", "draw"])
@pytest.mark.parametrize("cause", ["elimination", "base_destroyed"])
def test_natural_result_has_priority_over_limit_on_final_step(winner, cause):
    simulator = Simulator(Battlefield(800, 600), _standoff_units(), max_steps=1)
    losing_teams = ["blue"] if winner == "red" else ["red"] if winner == "blue" else ["red", "blue"]
    for team in losing_teams:
        if cause == "base_destroyed":
            base = simulator.battlefield.base_obj(team)
            base.take_damage(base.hp)
        else:
            for unit in simulator.units:
                if unit.team == team:
                    unit.take_damage(unit.hp)

    simulator.step()

    assert simulator.winner == winner
    assert simulator.finish_reason == cause
    assert simulator.time_step == simulator.max_steps == 1
    assert not any("时间步上限" in line for line in simulator.combat_logs)


def test_controller_stops_advancing_after_standoff_limit(monkeypatch):
    # Use the public simulator limit through the controller's creation boundary.
    monkeypatch.setattr("core.controller.Simulator", lambda field, units: Simulator(
        field, units, max_steps=1))
    controller = SimulationController()
    assert controller.start().ok
    assert controller.advance().ok
    assert controller.game_state == "finished"
    assert controller.simulator.finish_reason == "step_limit"

    for _ in range(5):
        assert not controller.advance().ok
    assert controller.simulator.time_step == 1
