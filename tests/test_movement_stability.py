from config import STATUS_ATTACK
from core.battlefield import Battlefield, Obstacle
from core.strategy import StrategyEngine
from core.units import GroundVehicle, ScoutDrone


def test_air_unit_crosses_obstacle_without_blocking():
    battlefield = Battlefield(100, 100, [Obstacle(x=40, y=0, width=30, height=100)])
    unit = ScoutDrone(id="air1", name="air", team="red", x=35, y=50, speed=20)

    unit.move_towards(80, 50, battlefield)

    assert unit.x > 40


def test_ground_unit_obstacle_move_does_not_crash_or_enter_obstacle():
    battlefield = Battlefield(100, 100, [Obstacle(x=40, y=40, width=20, height=20)])
    unit = GroundVehicle(id="g1", name="ground", team="red", x=35, y=50, speed=10)

    unit.move_towards(80, 50, battlefield)

    assert not battlefield.is_blocked(unit.x, unit.y)


def test_ground_unit_is_not_permanently_locked_by_finite_obstacle():
    battlefield = Battlefield(100, 100, [Obstacle(x=40, y=40, width=20, height=20)])
    unit = GroundVehicle(id="g1", name="ground", team="red", x=35, y=50, speed=10)
    start = (unit.x, unit.y)

    for _ in range(5):
        unit.move_towards(80, 50, battlefield)

    assert (unit.x, unit.y) != start
    assert not battlefield.is_blocked(unit.x, unit.y)


def test_unit_in_attack_range_does_not_move_closer():
    battlefield = Battlefield(200, 200)
    red = ScoutDrone(id="r1", name="red", team="red", x=20, y=20, attack_range=80)
    blue = ScoutDrone(id="b1", name="blue", team="blue", x=90, y=20)

    StrategyEngine().move_unit(red, battlefield, blue, [blue], [blue])

    assert red.status == STATUS_ATTACK
    assert (red.x, red.y) == (20, 20)


def test_move_away_from_zero_distance_does_not_divide_by_zero():
    battlefield = Battlefield(100, 100)
    red = ScoutDrone(id="r1", name="red", team="red", x=20, y=20)
    blue = ScoutDrone(id="b1", name="blue", team="blue", x=20, y=20)

    red.move_away_from(blue, battlefield)

    assert red.x > 20
