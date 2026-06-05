"""战场态势感知测试。"""

from core.battlefield import Battlefield
from core.simulator import Simulator
from core.threat import situation_label, team_strength
from core.units import (CommandNode, GroundVehicle, MissileVehicle,
                        ScoutDrone, StrikeDrone)


def _ten_each():
    return [
        ScoutDrone(id="R-SD-1", name="红-侦察无人机", team="red", x=85, y=110),
        StrikeDrone(id="R-AD-1", name="红-打击无人机", team="red", x=105, y=225),
        GroundVehicle(id="R-GV-1", name="红-无人战车", team="red", x=145, y=335),
        MissileVehicle(id="R-MV-1", name="红-导弹发射车", team="red", x=135, y=460),
        CommandNode(id="R-CMD-1", name="红-指挥节点", team="red", x=55, y=520),
        ScoutDrone(id="B-SD-1", name="蓝-侦察无人机", team="blue", x=710, y=115),
        StrikeDrone(id="B-AD-1", name="蓝-打击无人机", team="blue", x=695, y=245),
        GroundVehicle(id="B-GV-1", name="蓝-无人战车", team="blue", x=650, y=355),
        MissileVehicle(id="B-MV-1", name="蓝-导弹发射车", team="blue", x=655, y=480),
        CommandNode(id="B-CMD-1", name="蓝-指挥节点", team="blue", x=745, y=525),
    ]


def test_team_strength_equal_initially():
    units = _ten_each()
    rs = team_strength([u for u in units if u.team == "red"])
    bs = team_strength([u for u in units if u.team == "blue"])
    assert rs == bs


def test_situation_equal():
    assert situation_label(100, 100, "red") == "均势"


def test_simulator_calculates_strength():
    bf = Battlefield(800, 600)
    sim = Simulator(bf, _ten_each())
    sim.step()
    snap = sim.status_snapshot()
    assert snap["red_strength"] > 0
    assert snap["blue_strength"] > 0
    assert snap["red_situation"] in ("优势", "均势", "劣势")
    assert snap["red_tactics"] in ("进攻", "协同推进", "保守推进")
    assert snap["red_behavior"] in ("攻击", "侦察", "规避", "巡逻", "待命")


def test_simulator_weak_side_shows_disadvantage():
    bf = Battlefield(800, 600)
    units = [
        ScoutDrone(id="R-1", name="红-侦察", team="red", x=85, y=110),
        MissileVehicle(id="R-MV-1", name="红-导弹", team="red", x=135, y=460),
        ScoutDrone(id="B-1", name="蓝-侦察", team="blue", x=710, y=115, hp=10),
    ]
    sim = Simulator(bf, units)
    for _ in range(5):
        sim.step()
        if sim.winner:
            break
    snap = sim.status_snapshot()
    assert snap["blue_situation"] in ("劣势",)
