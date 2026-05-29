from core.battlefield import Battlefield, Obstacle
from core.units import CommandNode, GroundVehicle, ScoutDrone, UnitDomain


def test_scout_drone_domain_is_air():
    unit = ScoutDrone(id="air1", name="侦察无人机", team="red", x=0, y=0)

    assert unit.domain == UnitDomain.AIR


def test_ground_vehicle_domain_is_ground():
    unit = GroundVehicle(id="g1", name="无人战车", team="red", x=0, y=0)

    assert unit.domain == UnitDomain.GROUND


def test_command_node_domain_is_command():
    unit = CommandNode(id="c1", name="指挥节点", team="red", x=0, y=0)

    assert unit.domain == UnitDomain.COMMAND


def test_air_unit_can_cross_obstacle():
    battlefield = Battlefield(100, 100, [Obstacle(x=40, y=0, width=30, height=100)])
    unit = ScoutDrone(id="air1", name="侦察无人机", team="red", x=35, y=50, speed=20)

    unit.move_towards(80, 50, battlefield)

    assert unit.x > 40


def test_ground_unit_cannot_enter_obstacle():
    battlefield = Battlefield(100, 100, [Obstacle(x=40, y=0, width=30, height=100)])
    unit = GroundVehicle(id="g1", name="无人战车", team="red", x=35, y=50, speed=10)

    unit.move_towards(80, 50, battlefield)

    assert unit.x == 35


def test_command_node_does_not_move():
    battlefield = Battlefield(100, 100)
    unit = CommandNode(id="c1", name="指挥节点", team="red", x=20, y=20)

    unit.move_towards(80, 80, battlefield)

    assert (unit.x, unit.y) == (20, 20)
