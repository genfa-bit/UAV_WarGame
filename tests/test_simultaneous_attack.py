"""测试同步伤害结算 — 第十阶段新增。

通过 mock random.random 控制命中判定，消除概率性失败。
"""

from unittest.mock import patch

from core.battlefield import Battlefield
from core.combat import CombatSystem
from core.simulator import Simulator
from core.units import GroundVehicle, ScoutDrone, StrikeDrone


def test_both_units_can_attack_same_frame():
    """双方单位可在同一帧互相攻击（通过意图队列）。"""
    red = StrikeDrone(id="r1", name="红打击", team="red", x=50, y=50,
                       reaction_delay=0, attack_cooldown=0)
    blue = StrikeDrone(id="b1", name="蓝打击", team="blue", x=60, y=50,
                        reaction_delay=0, attack_cooldown=0)
    cs = CombatSystem()
    cs.queue_attack(red, blue)
    cs.queue_attack(blue, red)
    assert len(cs._intents) == 2
    with patch("random.random", side_effect=[0.0, 0.0, 0.0, 0.0]):
        events = cs.resolve_all_attacks()
    assert len(events) == 2


def test_attack_intent_not_applied_until_resolve():
    """攻击意图加入队列后不立即扣血。"""
    red = StrikeDrone(id="r1", name="红打击", team="red", x=50, y=50,
                       reaction_delay=0, attack_cooldown=0)
    blue = StrikeDrone(id="b1", name="蓝打击", team="blue", x=60, y=50,
                        reaction_delay=0, attack_cooldown=0)
    blue_hp_before = blue.hp
    cs = CombatSystem()
    cs.queue_attack(red, blue)
    assert blue.hp == blue_hp_before
    with patch("random.random", return_value=0.0):
        cs.resolve_all_attacks()
    assert blue.hp <= blue_hp_before


def test_mutual_destruction_same_frame():
    """双方同时被摧毁（同一帧内互相击杀）。"""
    red = StrikeDrone(id="r1", name="红打击", team="red", x=50, y=50,
                       attack_power=200, reaction_delay=0, attack_cooldown=0)
    blue = StrikeDrone(id="b1", name="蓝打击", team="blue", x=60, y=50,
                        attack_power=200, reaction_delay=0, attack_cooldown=0)
    cs = CombatSystem()
    cs.queue_attack(red, blue)
    cs.queue_attack(blue, red)
    with patch("random.random", return_value=0.0):
        cs.resolve_all_attacks()
    assert red.is_destroyed
    assert blue.is_destroyed


def test_miss_does_no_damage():
    """未命中不造成伤害（mock random 返回 1.0 保证未命中）。"""
    red = StrikeDrone(id="r1", name="红打击", team="red", x=50, y=50,
                       base_hit_prob=0.8, reaction_delay=0, attack_cooldown=0)
    blue = StrikeDrone(id="b1", name="蓝打击", team="blue", x=60, y=50)
    blue_hp_before = blue.hp
    cs = CombatSystem()
    cs.queue_attack(red, blue)
    with patch("random.random", return_value=1.0):
        events = cs.resolve_all_attacks()
    assert events[0].is_miss
    assert blue.hp == blue_hp_before


def test_multiple_attacks_on_same_target():
    """多个单位攻击同一目标同步结算。"""
    r1 = StrikeDrone(id="r1", name="红1", team="red", x=50, y=50,
                      reaction_delay=0, attack_cooldown=0)
    r2 = StrikeDrone(id="r2", name="红2", team="red", x=55, y=50,
                      reaction_delay=0, attack_cooldown=0)
    blue = GroundVehicle(id="b1", name="蓝车", team="blue", x=60, y=50,
                          max_hp=200, hp=200)
    cs = CombatSystem()
    cs.queue_attack(r1, blue)
    cs.queue_attack(r2, blue)
    with patch("random.random", return_value=0.0):
        events = cs.resolve_all_attacks()
    assert len(events) == 2
    total_dmg = sum(e.damage for e in events)
    assert total_dmg > 0


def test_attack_intent_cleared_after_resolve():
    """结算后意图队列清空。"""
    red = StrikeDrone(id="r1", name="红打击", team="red", x=50, y=50,
                       reaction_delay=0, attack_cooldown=0)
    blue = StrikeDrone(id="b1", name="蓝打击", team="blue", x=60, y=50)
    cs = CombatSystem()
    cs.queue_attack(red, blue)
    assert len(cs._intents) == 1
    with patch("random.random", return_value=0.0):
        cs.resolve_all_attacks()
    assert len(cs._intents) == 0
