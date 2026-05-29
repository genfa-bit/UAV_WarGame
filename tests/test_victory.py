from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import GroundVehicle, ScoutDrone


def test_red_destroyed_blue_wins():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "blue"


def test_blue_destroyed_red_wins():
    red = GroundVehicle(id="r1", name="红无人车", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=180, y=100, hp=0)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "red"


def test_both_sides_destroyed_is_draw():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=180, y=100, hp=0)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "draw"


def test_victory_result_is_in_status_snapshot():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.status_snapshot()["winner"] == "blue"
