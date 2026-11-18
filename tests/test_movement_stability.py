from config import BASE_REPAIR_RADIUS, STATUS_ATTACK, UNIT_SEPARATION_DISTANCE
from core.battlefield import Battlefield, Obstacle
from core.simulator import Simulator
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
    red = ScoutDrone(id="r1", name="red", team="red", x=20, y=20, attack_range=80,
                      reaction_delay=0, attack_cooldown=0)
    blue = ScoutDrone(id="b1", name="blue", team="blue", x=90, y=20)

    # 第十阶段：交战状态机需要先发现目标才能进入攻击态
    red.engagement_state.on_target_spotted(blue.id)
    StrategyEngine().move_unit(red, battlefield, blue, [blue], [blue])

    assert red.status == STATUS_ATTACK
    assert (red.x, red.y) == (20, 20)


def test_move_away_from_zero_distance_does_not_divide_by_zero():
    battlefield = Battlefield(100, 100)
    red = ScoutDrone(id="r1", name="red", team="red", x=20, y=20)
    blue = ScoutDrone(id="b1", name="blue", team="blue", x=20, y=20)

    red.move_away_from(blue, battlefield)

    assert red.x > 20


def test_units_assigned_to_same_target_hold_distinct_standoff_points():
    battlefield = Battlefield(800, 600)
    target = ScoutDrone(id="b1", name="target", team="blue", x=400, y=300)
    first = ScoutDrone(id="r1", name="first", team="red", x=100, y=300)
    second = ScoutDrone(id="r2", name="second", team="red", x=700, y=300)
    engine = StrategyEngine()

    for _ in range(120):
        engine._do_approach_target(first, target, battlefield)
        engine._do_approach_target(second, target, battlefield)

    assert (first.x, first.y) != (target.x, target.y)
    assert (second.x, second.y) != (target.x, target.y)
    assert (first.x, first.y) != (second.x, second.y)
    assert first.distance_to(target) <= first.attack_range
    assert second.distance_to(target) <= second.attack_range


def test_resupply_units_wait_on_distinct_base_slots():
    battlefield = Battlefield(800, 600)
    first = ScoutDrone(id="r1", name="first", team="red", x=220, y=300)
    second = ScoutDrone(id="r2", name="second", team="red", x=240, y=340)
    engine = StrategyEngine()
    base_x, base_y = battlefield.base_for_team("red")

    for _ in range(120):
        engine._do_resupply(first, battlefield)
        engine._do_resupply(second, battlefield)

    assert (first.x, first.y) != (second.x, second.y)
    assert (first.x, first.y) != (base_x, base_y)
    assert (second.x, second.y) != (base_x, base_y)
    for unit in (first, second):
        assert ((unit.x - base_x) ** 2 + (unit.y - base_y) ** 2) ** 0.5 \
            <= BASE_REPAIR_RADIUS


def test_overlapping_units_are_pushed_apart():
    battlefield = Battlefield(400, 400)
    first = ScoutDrone(id="r1", name="first", team="red", x=200, y=200)
    second = ScoutDrone(id="r2", name="second", team="red", x=200, y=200)
    simulator = Simulator(battlefield, [first, second])

    for _ in range(10):
        simulator._separate_overlapping_units()

    assert first.distance_to(second) >= UNIT_SEPARATION_DISTANCE - 1e-6
