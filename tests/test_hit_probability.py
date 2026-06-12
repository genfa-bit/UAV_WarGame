"""测试动态命中概率 —— 第十阶段新增。"""

from core.battlefield import Battlefield, Obstacle
from core.combat import _segment_intersects_rect, calculate_hit_probability
from core.units import ScoutDrone, StrikeDrone, GroundVehicle


def test_segment_intersects_rect_crossing():
    """线段穿过矩形应返回 True。"""
    assert _segment_intersects_rect(0, 5, 10, 5, 4, 0, 2, 10)


def test_segment_does_not_intersect_rect():
    """线段未穿过矩形应返回 False。"""
    assert not _segment_intersects_rect(0, 0, 10, 0, 0, 5, 10, 2)


def test_base_hit_probability_no_modifiers():
    """近距离无掩体无规避时命中率接近基础值。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=0,
                           base_hit_prob=0.8, attack_range=100)
    target = ScoutDrone(id="t", name="目标", team="blue", x=1, y=0, speed=0)
    battlefield = Battlefield(200, 200)
    prob = calculate_hit_probability(attacker, target, battlefield)
    assert 0.7 < prob < 0.95


def test_distance_factor_reduces_at_max_range():
    """射程边缘命中率明显衰减。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=0,
                           base_hit_prob=0.8, attack_range=100)
    target = ScoutDrone(id="t", name="目标", team="blue", x=99, y=0, speed=0)
    battlefield = Battlefield(200, 200)
    prob_far = calculate_hit_probability(attacker, target, battlefield)
    target.x = 1
    prob_near = calculate_hit_probability(attacker, target, battlefield)
    assert prob_near > prob_far


def test_speed_factor_reduces_for_fast_target():
    """快速目标更难命中。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=0,
                           base_hit_prob=0.8, attack_range=100)
    fast = ScoutDrone(id="f", name="快速", team="blue", x=50, y=0, speed=8)
    slow = ScoutDrone(id="s", name="慢速", team="blue", x=50, y=0, speed=1)
    battlefield = Battlefield(200, 200)
    prob_fast = calculate_hit_probability(attacker, fast, battlefield)
    prob_slow = calculate_hit_probability(attacker, slow, battlefield)
    assert prob_slow > prob_fast


def test_evading_reduces_hit_probability():
    """规避状态命中率下降。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=0,
                           base_hit_prob=0.8, attack_range=100)
    target = ScoutDrone(id="t", name="目标", team="blue", x=10, y=0, speed=0)
    battlefield = Battlefield(200, 200)
    prob_normal = calculate_hit_probability(attacker, target, battlefield, is_evading=False)
    prob_evading = calculate_hit_probability(attacker, target, battlefield, is_evading=True)
    assert prob_normal > prob_evading


def test_cover_factor_when_obstacle_between():
    """掩体遮挡大幅降低命中率。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=50,
                           base_hit_prob=0.8, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=150, y=50, speed=0)
    obs = Obstacle(x=70, y=20, width=10, height=60)
    battlefield = Battlefield(200, 200, [obs])
    prob = calculate_hit_probability(attacker, target, battlefield)
    assert prob < 0.5  # 0.3 factor applied


def test_no_cover_without_obstacles():
    """无掩体时不触发遮挡因子。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=50,
                           base_hit_prob=0.8, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=100, y=50, speed=0)
    battlefield = Battlefield(200, 200, [])
    prob = calculate_hit_probability(attacker, target, battlefield)
    assert prob > 0.6


def test_probability_clamped_to_minimum_5pct():
    """命中率最低为 5%。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=50,
                           base_hit_prob=0.01, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=199, y=50, speed=10)
    obs = Obstacle(x=100, y=20, width=10, height=60)
    battlefield = Battlefield(200, 200, [obs])
    prob = calculate_hit_probability(attacker, target, battlefield, is_evading=True)
    assert prob >= 0.05


def test_probability_clamped_to_maximum_95pct():
    """命中率最高为 95%。"""
    attacker = ScoutDrone(id="a", name="攻击者", team="red", x=0, y=50,
                           base_hit_prob=1.5, attack_range=200)
    target = ScoutDrone(id="t", name="目标", team="blue", x=1, y=50, speed=0)
    battlefield = Battlefield(200, 200, [])
    prob = calculate_hit_probability(attacker, target, battlefield)
    assert prob <= 0.95


def test_combined_factors():
    """多因子叠加计算验证（距离 + 速度 + 规避 + 掩体）。"""
    attacker = StrikeDrone(id="a", name="攻击者", team="red", x=0, y=50,
                            base_hit_prob=0.9, attack_range=200)
    target = GroundVehicle(id="t", name="目标", team="blue", x=180, y=50, speed=3)
    obs = Obstacle(x=90, y=20, width=10, height=60)
    battlefield = Battlefield(200, 200, [obs])
    prob = calculate_hit_probability(attacker, target, battlefield, is_evading=True)
    # base 0.9 * dist_factor * speed_factor * 0.7 * 0.3
    # should be significantly reduced
    assert prob < 0.3
