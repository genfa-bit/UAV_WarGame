from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import CommandNode, GroundVehicle, ScoutDrone, StrikeDrone


def test_attack_count_statistics():
    red = StrikeDrone(id="r1", name="红打击无人机", team="red", x=100, y=100)
    blue = CommandNode(id="b1", name="蓝指挥节点", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    snapshot = simulator.status_snapshot()
    assert snapshot["red_attacks"] == 1
    assert snapshot["blue_attacks"] == 0


def test_total_damage_statistics():
    red = StrikeDrone(id="r1", name="红打击无人机", team="red", x=100, y=100)
    blue = CommandNode(id="b1", name="蓝指挥节点", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.status_snapshot()["red_damage"] == red.attack_power


def test_destroyed_count_statistics():
    red = GroundVehicle(id="r1", name="红无人车", team="red", x=100, y=100, attack_power=60)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    snapshot = simulator.status_snapshot()
    assert snapshot["red_kills"] == 1
    assert snapshot["blue_destroyed"] == 1
