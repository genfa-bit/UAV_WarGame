from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import ScoutDrone


def test_unit_detects_enemy_in_range():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert "b1" in simulator.red_detected_targets


def test_unit_does_not_detect_enemy_out_of_range():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=500, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert "b1" not in simulator.red_detected_targets


def test_destroyed_unit_will_not_be_detected():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=180, y=100, hp=0)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert "b1" not in simulator.red_detected_targets
