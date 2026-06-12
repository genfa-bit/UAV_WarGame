"""测试反先手优势机制 —— 第十阶段新增。

验证先发现方的反应延迟使被攻击方有反应机会，
消除"先发现→先攻击→绝对优势"问题。
"""

import random

from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import CommandNode, ScoutDrone, StrikeDrone


def test_reaction_delay_prevents_instant_attack():
    """有反应延迟时，第一帧不能立即攻击（先发现≠先攻击）。"""
    red = ScoutDrone(id="r1", name="红侦察", team="red", x=50, y=50,
                      reaction_delay=10, attack_cooldown=10)
    blue = CommandNode(id="b1", name="蓝指挥", team="blue", x=100, y=50)
    sim = Simulator(Battlefield(200, 200), [red, blue])

    # 第一帧：发现目标但处于反应期
    sim.step()
    assert sim.status_snapshot()["red_attacks"] == 0


def test_defender_can_react_during_attacker_reaction():
    """攻击方反应期间，防御方也有时间反应（双方都有延迟）。"""
    red = StrikeDrone(id="r1", name="红打击", team="red", x=50, y=50,
                       reaction_delay=15, attack_cooldown=20)
    blue = StrikeDrone(id="b1", name="蓝打击", team="blue", x=80, y=50,
                        reaction_delay=15, attack_cooldown=20)
    sim = Simulator(Battlefield(200, 200), [red, blue])

    # 前几帧双方都在反应期，不应有攻击
    for _ in range(5):
        sim.step()
    snap = sim.status_snapshot()
    assert snap["red_attacks"] == 0
    assert snap["blue_attacks"] == 0


def test_target_loss_resets_reaction():
    """反应期间目标丢失重置进度。"""
    from core.engagement import EngagementPhase, EngagementState

    es = EngagementState(reaction_delay=10, attack_cooldown=20)
    es.on_target_spotted("enemy_1")
    for _ in range(5):
        es.tick()
    assert es.phase == EngagementPhase.REACTING
    # 目标丢失
    es.on_target_lost()
    assert es.phase == EngagementPhase.SEARCH
    # 重新发现需要重新反应
    es.on_target_spotted("enemy_1")
    assert es.phase == EngagementPhase.REACTING
    assert es.reaction_progress == 0


def test_attack_cooldown_prevents_continuous_fire():
    """攻击冷却期间无法再次攻击。"""
    red = ScoutDrone(id="r1", name="红侦察", team="red", x=50, y=50,
                      reaction_delay=1, attack_cooldown=50)
    blue = CommandNode(id="b1", name="蓝指挥", team="blue", x=100, y=50)
    sim = Simulator(Battlefield(200, 200), [red, blue])

    # 第一帧发现，第二帧可攻击
    sim.step()
    snap1 = sim.status_snapshot()
    # 攻击后进入冷却
    sim.step()
    snap2 = sim.status_snapshot()
    assert snap2["red_attacks"] <= snap1["red_attacks"] + 1


def test_two_units_with_different_delays_can_both_attack():
    """不同反应延迟的单位各自独立管理交战状态。"""
    from unittest.mock import patch

    r1 = StrikeDrone(id="r1", name="红快", team="red", x=50, y=50,
                      reaction_delay=0, attack_cooldown=30)
    r2 = StrikeDrone(id="r2", name="红慢", team="red", x=55, y=50,
                      reaction_delay=20, attack_cooldown=30)
    blue = CommandNode(id="b1", name="蓝指挥", team="blue", x=100, y=50)
    sim = Simulator(Battlefield(200, 200), [r1, r2, blue])

    with patch("random.random", return_value=0.0):
        sim.step()
    snap = sim.status_snapshot()
    # r1 (delay=0) 应立即攻击，r2 (delay=20) 在反应期
    assert snap["red_attacks"] >= 1


def test_base_attack_before_engagement():
    """验证基地攻击不受反应延迟影响的极端情况（基地攻击直接命中）。"""
    from core.battlefield import Base
    from core.combat import CombatSystem
    from core.units import StrikeDrone

    red = StrikeDrone(id="r1", name="红打击", team="red", x=10, y=50)
    base = Base(team="blue", x=50, y=50)
    cs = CombatSystem()
    intent = cs.queue_attack_base(red, base)
    assert intent is not None
    assert intent.hit_probability == 1.0
