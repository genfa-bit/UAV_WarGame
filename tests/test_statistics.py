"""测试战斗统计 —— 第十阶段适配随机反应延迟。

通过传入 reaction_delay=0, attack_cooldown=0 使攻击即时触发。
通过 mock random.random 返回 0 保证命中，避免概率性失败。
"""

from unittest.mock import patch

from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import CommandNode, GroundVehicle, ScoutDrone, StrikeDrone


def test_attack_count_statistics():
    red = StrikeDrone(id="r1", name="红打击无人机", team="red", x=100, y=100,
                       reaction_delay=0, attack_cooldown=0)
    blue = CommandNode(id="b1", name="蓝指挥节点", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    with patch("random.random", side_effect=[1.0, 0.0]):
        simulator.step()

    snapshot = simulator.status_snapshot()
    assert snapshot["red_attacks"] == 1
    assert snapshot["blue_attacks"] == 0


def test_total_damage_statistics():
    red = StrikeDrone(id="r1", name="红打击无人机", team="red", x=100, y=100,
                       reaction_delay=0, attack_cooldown=0)
    blue = CommandNode(id="b1", name="蓝指挥节点", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    with patch("random.random", side_effect=[1.0, 0.0]):
        simulator.step()

    assert simulator.status_snapshot()["red_damage"] == red.attack_power


def test_destroyed_count_statistics():
    red = GroundVehicle(id="r1", name="红无人车", team="red", x=100, y=100,
                         attack_power=85, reaction_delay=0, attack_cooldown=0)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    with patch("random.random", side_effect=[1.0, 0.0]):
        simulator.step()

    snapshot = simulator.status_snapshot()
    assert snapshot["red_kills"] == 1
    assert snapshot["blue_destroyed"] == 1
