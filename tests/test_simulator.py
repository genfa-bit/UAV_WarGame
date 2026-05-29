from pathlib import Path

from core.battlefield import Battlefield
from core.scenario_loader import load_scenario
from core.simulator import Simulator
from core.units import GroundVehicle, ScoutDrone


def test_simulator_initializes_from_scenario():
    path = Path(__file__).resolve().parents[1] / "data" / "scenario_1.json"
    battlefield, units = load_scenario(path)
    simulator = Simulator(battlefield, units)

    assert battlefield.width == 800
    assert battlefield.red_base == (80, 300)
    assert battlefield.blue_base == (720, 300)
    assert battlefield.terrain == "mixed_training_area"
    assert len(battlefield.obstacles) == 3
    assert len(simulator.units) == 10


def test_winner_when_one_team_destroyed():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "blue"


def test_target_pool_cleans_destroyed_units():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100)
    dead_blue = ScoutDrone(id="b-dead", name="蓝已摧毁", team="blue", x=150, y=100, hp=0)
    alive_blue = ScoutDrone(id="b-live", name="蓝存活", team="blue", x=600, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, dead_blue, alive_blue])
    simulator.red_detected_targets[dead_blue.id] = dead_blue

    simulator.step()

    assert dead_blue.id not in simulator.red_detected_targets


def test_focus_target_prefers_lowest_hp():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100)
    low_hp_blue = ScoutDrone(id="b-low", name="蓝低血量", team="blue", x=180, y=100, hp=20)
    high_hp_blue = ScoutDrone(id="b-high", name="蓝高血量", team="blue", x=190, y=100, hp=60)
    simulator = Simulator(Battlefield(800, 600), [red, low_hp_blue, high_hp_blue])

    simulator.step()

    assert simulator.focus_targets["red"] == low_hp_blue
