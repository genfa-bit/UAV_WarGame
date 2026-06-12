import json

from config import GAME_DEPLOYMENT, GAME_PAUSED, GAME_RUNNING
from core.combat import AttackEvent
from core.controller import SimulationController


def test_controller_initial_snapshot_is_serializable():
    controller = SimulationController()

    snapshot = controller.snapshot()

    assert snapshot["game_state"] == GAME_DEPLOYMENT
    assert len(snapshot["units"]) == 10
    assert len(snapshot["map"]["obstacles"]) == 3
    json.dumps(snapshot, ensure_ascii=False)


def test_controller_start_pause_step_and_reset():
    controller = SimulationController()

    assert controller.start().ok
    assert controller.game_state == GAME_RUNNING

    assert controller.toggle_pause().ok
    assert controller.game_state == GAME_PAUSED

    assert controller.step().ok
    assert controller.simulator.time_step == 1
    assert controller.game_state == GAME_PAUSED

    assert controller.reset().ok
    assert controller.game_state == GAME_DEPLOYMENT
    assert controller.simulator is None


def test_controller_deployment_commands_update_snapshot():
    controller = SimulationController()

    controller.select_obstacle_type("building")
    assert controller.snapshot()["deployment"]["selected_obstacle_type"] == "building"

    controller.select_unit_type("ground_vehicle")
    controller.toggle_team()
    deployment = controller.snapshot()["deployment"]
    assert deployment["selected_unit_type"] == "ground_vehicle"
    assert deployment["selected_team"] == "blue"


def test_controller_speed_cycles():
    controller = SimulationController()
    first = controller.speed_label

    controller.cycle_speed()

    assert controller.speed_label != first
    assert controller.snapshot()["speed_interval_ms"] >= 0


def test_attack_event_snapshot_has_frontend_event_id():
    controller = SimulationController()
    controller.start()
    event = AttackEvent(
        attacker_id="R-SD-1",
        target_id="B-SD-1",
        start=(85, 110),
        end=(710, 115),
        damage=8,
        target_hp=47,
    )
    controller.simulator.attack_events.append(event)

    attack_event = controller.snapshot()["attack_events"][0]

    assert attack_event["event_id"] == str(event.event_id)
    assert attack_event["attacker_team"] == "red"
    assert attack_event["attacker_type"] == "scout_drone"
