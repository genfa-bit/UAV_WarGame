"""路径规划测试。"""

from core.battlefield import Battlefield, Obstacle
from core.pathfinding import move_to, reset_path
from core.units import GroundVehicle, ScoutDrone


def test_air_unit_flies_straight():
    bf = Battlefield(800, 600, obstacles=[
        Obstacle(400, 200, 50, 50, name="block", type="building"),
    ])
    unit = ScoutDrone(id="R-1", name="红-侦察", team="red", x=100, y=300)
    reset_path(unit.id)
    result = move_to(unit, 700, 300, bf)
    assert result
    assert unit.x > 100  # moved toward target


def test_ground_unit_moves_when_clear():
    bf = Battlefield(800, 600)
    unit = GroundVehicle(id="R-1", name="红-战车", team="red", x=100, y=300)
    reset_path(unit.id)
    old_x = unit.x
    result = move_to(unit, 700, 300, bf)
    assert result
    assert unit.x > old_x


def test_ground_obstacle_avoidance():
    """地面单位遇到障碍物时不会卡死在原地。"""
    bf = Battlefield(800, 600, obstacles=[
        Obstacle(400, 250, 40, 100, name="wall", type="building"),
    ])
    unit = GroundVehicle(id="R-1", name="红-战车", team="red", x=350, y=300)
    reset_path(unit.id)
    start_x, start_y = unit.x, unit.y
    for _ in range(60):
        move_to(unit, 600, 300, bf)
    # 单位不应该卡死在原地
    dist_moved = ((unit.x - start_x) ** 2 + (unit.y - start_y) ** 2) ** 0.5
    assert dist_moved > 5


def test_reset_path():
    bf = Battlefield(800, 600, obstacles=[
        Obstacle(400, 200, 50, 50, name="block", type="building"),
    ])
    unit = GroundVehicle(id="R-1", name="红-战车", team="red", x=100, y=300)
    move_to(unit, 700, 300, bf)
    reset_path(unit.id)
    # 重置后应能正常移动
    result = move_to(unit, 100, 300, bf)
    assert result


def test_destroyed_unit_returns_false():
    bf = Battlefield(800, 600)
    unit = GroundVehicle(id="R-1", name="红-战车", team="red", x=100, y=300, hp=0)
    assert not move_to(unit, 700, 300, bf)
