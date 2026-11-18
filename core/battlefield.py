"""战场地图模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from config import BASE_MAX_HP, BASE_REPAIR_PER_STEP
from core.terrain_catalog import MAP_STYLES


OBSTACLE_DISPLAY_NAMES = {
    "mountain": "山地",
    "building": "建筑群",
    "restricted": "禁行区",
}


def obstacle_display_name(obstacle: "Obstacle") -> str:
    """返回界面显示名，隐藏自动生成的英文内部名称。"""
    generated_prefix = f"{obstacle.type}_"
    if obstacle.name == obstacle.type or obstacle.name.startswith(generated_prefix):
        return OBSTACLE_DISPLAY_NAMES.get(obstacle.type, "障碍物")
    return obstacle.name


@dataclass(frozen=True)
class Obstacle:
    """矩形障碍物。"""
    x: float
    y: float
    width: float
    height: float
    name: str = "障碍物"
    type: str = "obstacle"

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        return self.x, self.y, self.width, self.height


# Base 类已移除，替换为 core.units.BaseUnit（Unit 子类）


class Battlefield:
    """二维战场：边界、障碍物、基地对象。"""

    def __init__(
        self,
        width: int,
        height: int,
        obstacles: Iterable[Obstacle] | None = None,
        terrain: str = "plain",
        red_base: tuple[float, float] = (80, 300),
        blue_base: tuple[float, float] = (720, 300),
        map_style: str = "tactical",
    ):
        if not isinstance(map_style, str) or map_style not in MAP_STYLES:
            raise ValueError("地图样式必须为 tactical、valley 或 river")
        self.width = width
        self.height = height
        self.obstacles = list(obstacles or [])
        self.terrain = terrain
        self.map_style = map_style
        from core.units import BaseUnit  # 延迟导入避免循环依赖
        self.red_base_obj = BaseUnit(id="red_base", name="红基地", team="red",
                                      x=red_base[0], y=red_base[1])
        self.blue_base_obj = BaseUnit(id="blue_base", name="蓝基地", team="blue",
                                       x=blue_base[0], y=blue_base[1])

    @property
    def red_base(self) -> tuple[float, float]:
        return (self.red_base_obj.x, self.red_base_obj.y)

    @red_base.setter
    def red_base(self, value: tuple[float, float]) -> None:
        self.red_base_obj.x, self.red_base_obj.y = value

    @property
    def blue_base(self) -> tuple[float, float]:
        return (self.blue_base_obj.x, self.blue_base_obj.y)

    @blue_base.setter
    def blue_base(self, value: tuple[float, float]) -> None:
        self.blue_base_obj.x, self.blue_base_obj.y = value

    def in_bounds(self, x: float, y: float) -> bool:
        return 0 <= x <= self.width and 0 <= y <= self.height

    def is_blocked(self, x: float, y: float) -> bool:
        return any(o.contains(x, y) for o in self.obstacles)

    def obstacles_at(self, x: float, y: float) -> tuple[Obstacle, ...]:
        """返回覆盖指定坐标的全部障碍物。"""
        return tuple(o for o in self.obstacles if o.contains(x, y))

    def clamp_position(self, x: float, y: float) -> tuple[float, float]:
        return max(0, min(self.width, x)), max(0, min(self.height, y))

    def is_position_valid(self, x: float, y: float,
                          unit_or_domain: object = "ground", *,
                          terrain_effects: dict | None = None) -> bool:
        """判断单位能否位于指定坐标。

        - 空中平台只受地图边界限制。
        - 地面平台可进入 unit_config.json 的 ``terrain_effects`` 中列出的地形
          （山地/建筑），未列出的障碍物仍然阻挡。
        - 只传平台名称（字符串）时沿用旧规则：任何障碍物都阻挡。
        """
        if not self.in_bounds(x, y):
            return False
        domain = getattr(unit_or_domain, "domain", unit_or_domain)
        if domain == "air":
            return True
        if terrain_effects is None:
            terrain_effects = getattr(unit_or_domain, "terrain_effects", None)
        overlapping = self.obstacles_at(x, y)
        if not overlapping:
            return True
        if terrain_effects is None:
            return False
        return all(obstacle.type in terrain_effects for obstacle in overlapping)

    def can_move_to(self, x: float, y: float,
                    unit_or_domain: object = "ground") -> bool:
        return self.is_position_valid(x, y, unit_or_domain)

    def base_for_team(self, team: str) -> tuple[float, float]:
        return self.red_base if team == "red" else self.blue_base

    def base_obj(self, team: str) -> "BaseUnit":
        return self.red_base_obj if team == "red" else self.blue_base_obj
