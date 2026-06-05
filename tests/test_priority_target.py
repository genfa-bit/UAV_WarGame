"""多目标优先级决策测试。"""

from core.battlefield import Battlefield
from core.simulator import Simulator
from core.strategy import StrategyEngine
from core.units import (CommandNode, GroundVehicle, MissileVehicle,
                        ScoutDrone, StrikeDrone)


def _full_units():
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


def test_simulator_has_priority_targets():
    bf = Battlefield(800, 600)
    sim = Simulator(bf, _full_units())
    sim.step()
    assert len(sim.priority_targets["red"]) > 0
    assert len(sim.priority_targets["blue"]) > 0
    assert sim.priority_targets["red"][0].unit_type == "missile_vehicle"


def test_simulator_runs_multi_steps():
    bf = Battlefield(800, 600)
    sim = Simulator(bf, _full_units())
    for _ in range(10):
        sim.step()
        if sim.winner:
            break
    assert sim.time_step > 0


def test_strategy_chooses_high_threat_target():
    engine = StrategyEngine()
    enemies = [
        MissileVehicle(id="B-MV-1", name="蓝-导弹", team="blue", x=400, y=300),
        ScoutDrone(id="B-SD-1", name="蓝-侦察", team="blue", x=500, y=200),
    ]
    friendlies = [ScoutDrone(id="R-1", name="红-侦察", team="red", x=100, y=100)]
    target = engine.choose_focus_target(enemies, friendlies)
    assert target is not None
    assert target.unit_type == "missile_vehicle"


def test_focus_lock_keeps_target():
    engine = StrategyEngine()
    enemies = [
        MissileVehicle(id="B-MV-1", name="蓝-导弹", team="blue", x=400, y=300),
        StrikeDrone(id="B-AD-1", name="蓝-打击", team="blue", x=420, y=310),
    ]
    friendlies = [ScoutDrone(id="R-1", name="红-侦察", team="red", x=100, y=100)]
    # With lock, should keep the locked target even if another has higher threat
    target = engine.choose_focus_target(enemies, friendlies, "B-AD-1")
    assert target is not None
    assert target.id == "B-AD-1"
