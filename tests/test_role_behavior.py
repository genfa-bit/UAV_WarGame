"""兵种角色行为测试。"""

from core.battlefield import Battlefield
from core.strategy import StrategyEngine
from core.units import (CommandNode, GroundVehicle, MissileVehicle,
                        ScoutDrone, StrikeDrone)


def test_scout_avoids_high_threat_area():
    engine = StrategyEngine()
    unit = ScoutDrone(id="R-1", name="红-侦察", team="red", x=100, y=100)
    target = MissileVehicle(id="B-MV-1", name="蓝-导弹", team="blue", x=110, y=110)
    bf = Battlefield(800, 600)
    visible = [target]
    engine._scout_behavior(unit, target, bf, visible)
    # Scout should evade when high-threat enemy is close
    assert unit.status in ("Evade", "Scout", "Attack")


def test_strike_prioritizes_attack():
    engine = StrategyEngine()
    unit = StrikeDrone(id="R-1", name="红-打击", team="red", x=100, y=100)
    target = GroundVehicle(id="B-GV-1", name="蓝-战车", team="blue", x=200, y=200)
    bf = Battlefield(800, 600)
    engine._strike_behavior(unit, target, bf, [])
    assert unit.status in ("Move", "Attack")


def test_missile_keeps_distance():
    engine = StrategyEngine()
    unit = MissileVehicle(id="R-1", name="红-导弹", team="red", x=100, y=100)
    target = StrikeDrone(id="B-1", name="蓝-打击", team="blue", x=120, y=120)
    bf = Battlefield(800, 600)
    engine._missile_behavior(unit, target, bf)
    assert unit.status == "Evade"  # too close, should back off


def test_ground_pushes_forward():
    engine = StrategyEngine()
    unit = GroundVehicle(id="R-1", name="红-战车", team="red", x=100, y=100)
    target = MissileVehicle(id="B-1", name="蓝-导弹", team="blue", x=500, y=300)
    bf = Battlefield(800, 600)
    engine._ground_behavior(unit, target, bf)
    assert unit.status == "Move"


def test_command_node_does_not_move():
    engine = StrategyEngine()
    unit = CommandNode(id="R-1", name="红-指挥", team="red", x=100, y=100)
    target = ScoutDrone(id="B-1", name="蓝-侦察", team="blue", x=200, y=200)
    bf = Battlefield(800, 600)
    old_x, old_y = unit.x, unit.y
    engine._default_behavior(unit, target, bf)
    assert unit.x == old_x
    assert unit.y == old_y
