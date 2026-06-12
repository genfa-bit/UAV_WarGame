"""无人装备单位与兵种体系定义。

第三阶段将单位划分为空中、地面和指挥节点三类平台，并在统一 Unit
接口下扩展具体兵种，方便后续继续新增单位。

第十阶段：Unit 增加反应延迟、攻击冷却、基础命中率字段，通过随机范围
取值生成实例值，并自动创建 EngagementState。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import hypot
from typing import Optional

from config import STATUS_DESTROYED, STATUS_MOVE, THREAT_VALUE_BY_TYPE
from core.battlefield import Battlefield
from core.engagement import EngagementState
from core.entity import Entity


class UnitDomain:
    """单位平台类型常量。"""

    AIR = "air"
    GROUND = "ground"
    COMMAND = "command"


@dataclass
class Unit(Entity):
    """所有兵种共用的基础接口。"""

    domain: str
    unit_type: str
    hp: int
    max_hp: int
    speed: float
    detect_range: float
    attack_range: float
    attack_power: int
    ammo: int
    status: str = STATUS_MOVE
    target_id: Optional[str] = None
    can_attack_air: bool = True
    can_attack_ground: bool = True
    threat_value: int = 1
    reaction_delay: int = 0
    attack_cooldown: int = 0
    base_hit_prob: float = 0.8
    engagement_state: EngagementState = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.engagement_state = EngagementState(self.reaction_delay, self.attack_cooldown)

    @property
    def is_destroyed(self) -> bool:
        return self.hp <= 0 or self.status == STATUS_DESTROYED

    @property
    def is_combat_unit(self) -> bool:
        """当前版本所有未摧毁单位都参与胜负统计。"""
        return not self.is_destroyed

    @property
    def hp_ratio(self) -> float:
        if self.max_hp <= 0:
            return 0
        return self.hp / self.max_hp

    @property
    def threat_score(self) -> float:
        """保留威胁评分接口，便于未来扩展更复杂目标选择。"""
        return self.threat_value

    def is_alive(self) -> bool:
        """判断单位是否仍然存活。"""
        return not self.is_destroyed

    def can_detect(self, other: "Unit") -> bool:
        """判断能否探测到另一个单位。"""
        return self.is_alive() and other.is_alive() and self.team != other.team and self.distance_to(other) <= self.detect_range

    def can_attack(self, other: "Unit") -> bool:
        """判断能否攻击另一个单位。

        本阶段所有作战单位默认可攻击空中和地面目标，但保留 can_attack_air /
        can_attack_ground 字段，为后续防空和对地能力扩展预留接口。
        """
        if not self.is_alive() or not other.is_alive():
            return False
        if self.ammo <= 0 or self.attack_power <= 0:
            return False
        if other.domain == UnitDomain.AIR and not self.can_attack_air:
            return False
        if other.domain in (UnitDomain.GROUND, UnitDomain.COMMAND) and not self.can_attack_ground:
            return False
        return self.distance_to(other) <= self.attack_range

    def take_damage(self, amount: int) -> int:
        """受到伤害并在生命归零时标记为摧毁，返回实际伤害。"""
        before_hp = self.hp
        self.hp = max(0, self.hp - amount)
        if self.hp <= 0:
            self.status = STATUS_DESTROYED
            self.target_id = None
        return before_hp - self.hp

    def move_towards(self, target_x: float, target_y: float, battlefield: Battlefield) -> None:
        """向指定坐标移动一步。"""
        if self.speed <= 0 or self.is_destroyed or self.domain == UnitDomain.COMMAND:
            return
        dx, dy = target_x - self.x, target_y - self.y
        distance = hypot(dx, dy)
        if distance == 0:
            return
        step = min(self.speed, distance)
        next_x = self.x + dx / distance * step
        next_y = self.y + dy / distance * step
        self.try_move(next_x, next_y, battlefield)

    def move_away_from(self, enemy: "Unit", battlefield: Battlefield) -> None:
        """向远离敌方单位的方向移动一步。"""
        if self.speed <= 0 or self.is_destroyed or self.domain == UnitDomain.COMMAND:
            return
        dx, dy = self.x - enemy.x, self.y - enemy.y
        distance = hypot(dx, dy)
        if distance == 0:
            dx, dy, distance = 1.0, 0.0, 1.0
        next_x = self.x + dx / distance * self.speed
        next_y = self.y + dy / distance * self.speed
        self.try_move(next_x, next_y, battlefield)

    def patrol(self, battlefield: Battlefield, direction: tuple[float, float]) -> None:
        """无明确目标时执行简单巡逻。"""
        if self.speed <= 0 or self.is_destroyed or self.domain == UnitDomain.COMMAND:
            return
        dx, dy = direction
        distance = hypot(dx, dy)
        if distance == 0:
            return
        next_x = self.x + dx / distance * self.speed
        next_y = self.y + dy / distance * self.speed
        self.try_move(next_x, next_y, battlefield)

    def try_move(self, next_x: float, next_y: float, battlefield: Battlefield) -> None:
        """执行带平台差异的移动。

        空中单位只受地图边界限制，可以越过普通障碍物；地面单位不能进入障碍物；
        指挥节点不移动。
        """
        if self.domain == UnitDomain.COMMAND:
            return
        next_x, next_y = battlefield.clamp_position(next_x, next_y)
        if self.domain == UnitDomain.AIR:
            self.x, self.y = next_x, next_y
            return

        if battlefield.can_move_to(next_x, next_y, self.domain):
            self.x, self.y = next_x, next_y
            return

        dx, dy = next_x - self.x, next_y - self.y
        candidates = [
            (next_x, self.y),
            (self.x, next_y),
            (self.x - dy * 0.6, self.y + dx * 0.6),
            (self.x + dy * 0.6, self.y - dx * 0.6),
        ]
        for candidate_x, candidate_y in candidates:
            candidate_x, candidate_y = battlefield.clamp_position(candidate_x, candidate_y)
            if (candidate_x, candidate_y) == (self.x, self.y):
                continue
            if battlefield.can_move_to(candidate_x, candidate_y, self.domain):
                self.x, self.y = candidate_x, candidate_y
                return


def _unit_defaults(unit_type: str) -> dict:
    """从配置文件逐兵种读取默认属性，威胁值从 config.py 补充。

    第十阶段：反应延迟和攻击冷却在配置范围内随机取值。
    """
    from core.unit_config_loader import get_unit_stats
    cfg = get_unit_stats(unit_type)
    rxn_min = cfg.get("reaction_delay_min", 2)
    rxn_max = cfg.get("reaction_delay_max", 5)
    cd_min = cfg.get("attack_cooldown_min", 10)
    cd_max = cfg.get("attack_cooldown_max", 20)
    return dict(
        domain=cfg["domain"],
        unit_type=unit_type,
        max_hp=cfg["max_hp"],
        hp=cfg["max_hp"],
        speed=cfg["speed"],
        detect_range=cfg["detect_range"],
        attack_range=cfg["attack_range"],
        attack_power=cfg["attack_power"],
        ammo=cfg["ammo"],
        can_attack_air=cfg.get("can_attack_air", True),
        can_attack_ground=cfg.get("can_attack_ground", True),
        threat_value=THREAT_VALUE_BY_TYPE.get(unit_type, 1),
        reaction_delay=random.randint(rxn_min, rxn_max),
        attack_cooldown=random.randint(cd_min, cd_max),
        base_hit_prob=cfg.get("base_hit_prob", 0.8),
    )


class ScoutDrone(Unit):
    """侦察无人机：高速、高侦察、低攻击、低生命。"""

    def __init__(self, **kwargs):
        defaults = _unit_defaults("scout_drone")
        defaults.update(kwargs)
        super().__init__(**defaults)


class StrikeDrone(Unit):
    """打击无人机：中速、中攻击，适合协同打击。"""

    def __init__(self, **kwargs):
        defaults = _unit_defaults("strike_drone")
        defaults.update(kwargs)
        super().__init__(**defaults)


class GroundVehicle(Unit):
    """无人战车：低速、高生命、高攻击，适合正面对抗。"""

    def __init__(self, **kwargs):
        defaults = _unit_defaults("ground_vehicle")
        defaults.update(kwargs)
        super().__init__(**defaults)


class MissileVehicle(Unit):
    """导弹发射车：远程、高伤害、低弹药。"""

    def __init__(self, **kwargs):
        defaults = _unit_defaults("missile_vehicle")
        defaults.update(kwargs)
        super().__init__(**defaults)


class CommandNode(Unit):
    """指挥节点：固定不动，生命值较高，通信枢纽。"""

    def __init__(self, **kwargs):
        defaults = _unit_defaults("command_node")
        defaults.update(kwargs)
        super().__init__(**defaults)
        self.comm_range = 250


class BaseUnit(Unit):
    """基地：固定不动，高生命值，为周围友军提供补给。"""

    def __init__(self, **kwargs):
        defaults = _unit_defaults("base")
        defaults.update(kwargs)
        super().__init__(**defaults)


# 兼容第一、二阶段命名，避免旧测试或旧场景短期内失效。
class UAV(ScoutDrone):
    """兼容旧名称：UAV 默认等价于 ScoutDrone。"""


class UGV(GroundVehicle):
    """兼容旧名称：UGV 默认等价于 GroundVehicle。"""
