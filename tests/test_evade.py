from config import STATUS_EVADE
from core.battlefield import Battlefield, Obstacle
from core.simulator import Simulator
from core.units import GroundVehicle, ScoutDrone, StrikeDrone


def test_low_hp_unit_enters_evade():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=10)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=300, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert red.status == STATUS_EVADE


def test_zero_ammo_unit_enters_evade():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, ammo=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert red.status == STATUS_EVADE


def test_evade_moves_away_from_nearest_enemy():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, ammo=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    before_distance = red.distance_to(blue)
    simulator.step()
    after_distance = red.distance_to(blue)

    assert red.status == STATUS_EVADE
    assert after_distance > before_distance


def test_enemy_too_close_triggers_evade():
    red = StrikeDrone(id="r1", name="Red striker", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="Blue scout", team="blue", x=130, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert red.status == STATUS_EVADE


def test_ground_unit_evade_does_not_enter_obstacle():
    obstacle = Obstacle(x=101, y=99, width=10, height=5)
    battlefield = Battlefield(800, 600, obstacles=[obstacle])
    red = GroundVehicle(id="r1", name="Red vehicle", team="red", x=100, y=100, ammo=0)
    blue = ScoutDrone(id="b1", name="Blue scout", team="blue", x=90, y=100)
    simulator = Simulator(battlefield, [red, blue])

    simulator.step()

    assert red.status == STATUS_EVADE
    assert not battlefield.is_blocked(red.x, red.y)
