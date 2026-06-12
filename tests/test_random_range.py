"""测试反应延迟与冷却的随机范围 — 第十阶段新增。

验证单位创建时 reaction_delay 和 attack_cooldown 在配置范围内随机分布。
"""

from core.unit_config_loader import get_unit_stats
from core.units import ScoutDrone, StrikeDrone, GroundVehicle, MissileVehicle


def test_reaction_delay_within_range():
    """多次创建的侦察无人机反应延迟在 8~15 范围内。"""
    cfg = get_unit_stats("scout_drone")
    rxn_min = cfg["reaction_delay_min"]
    rxn_max = cfg["reaction_delay_max"]
    for _ in range(50):
        unit = ScoutDrone(id="s", name="测试", team="red", x=0, y=0)
        assert rxn_min <= unit.reaction_delay <= rxn_max


def test_attack_cooldown_within_range():
    """多次创建的打击无人机冷却在配置范围内。"""
    cfg = get_unit_stats("strike_drone")
    cd_min = cfg["attack_cooldown_min"]
    cd_max = cfg["attack_cooldown_max"]
    for _ in range(50):
        unit = StrikeDrone(id="s", name="测试", team="red", x=0, y=0)
        assert cd_min <= unit.attack_cooldown <= cd_max


def test_different_unit_types_have_different_ranges():
    """不同兵种的延迟范围不同。"""
    scout = ScoutDrone(id="a", name="侦察", team="red", x=0, y=0)
    missile = MissileVehicle(id="b", name="导弹", team="red", x=10, y=0)
    # 导弹车反应应慢于侦察无人机
    scout_cfg = get_unit_stats("scout_drone")
    missile_cfg = get_unit_stats("missile_vehicle")
    assert missile_cfg["reaction_delay_min"] >= scout_cfg["reaction_delay_min"]


def test_reaction_delay_and_cooldown_are_integers():
    """反应延迟和冷却均为整数帧数。"""
    for _ in range(20):
        unit = GroundVehicle(id="g", name="战车", team="red", x=0, y=0)
        assert isinstance(unit.reaction_delay, int)
        assert isinstance(unit.attack_cooldown, int)
