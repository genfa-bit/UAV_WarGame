from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import CommandNode, GroundVehicle, ScoutDrone, StrikeDrone


def test_focus_target_prefers_lowest_hp():
    red = StrikeDrone(id="r1", name="Red striker", team="red", x=100, y=100)
    low_hp = GroundVehicle(id="b1", name="Low hp", team="blue", x=180, y=100, hp=20)
    high_hp = GroundVehicle(id="b2", name="High hp", team="blue", x=190, y=100, hp=90)
    simulator = Simulator(Battlefield(800, 600), [red, low_hp, high_hp])

    simulator.step()

    assert simulator.focus_targets["red"] == low_hp


def test_threat_value_breaks_same_hp_tie():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    low_threat = ScoutDrone(id="b1", name="Blue scout", team="blue", x=170, y=100, hp=40)
    high_threat = CommandNode(id="b2", name="Blue command", team="blue", x=180, y=100, hp=40)
    simulator = Simulator(Battlefield(800, 600), [red, low_threat, high_threat])

    simulator.step()

    assert simulator.focus_targets["red"] == high_threat


def test_focus_target_reselects_after_current_target_destroyed():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    destroyed = GroundVehicle(id="b1", name="Destroyed vehicle", team="blue", x=500, y=100, hp=0)
    alive = GroundVehicle(id="b2", name="Alive vehicle", team="blue", x=550, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, destroyed, alive])
    simulator.red_detected_targets["b1"] = destroyed
    simulator.red_detected_targets["b2"] = alive
    simulator.focus_targets["red"] = destroyed

    simulator.step()

    assert simulator.focus_targets["red"] == alive
