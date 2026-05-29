"""战场地图模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True)
class Obstacle:
    """矩形障碍物，包含名称和类型便于界面展示与答辩讲解。"""

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


class Battlefield:
    """二维战场，负责边界、障碍物、基地和地形信息管理。"""

    def __init__(
        self,
        width: int,
        height: int,
        obstacles: Iterable[Obstacle] | None = None,
        terrain: str = "plain",
        red_base: tuple[float, float] = (80, 300),
        blue_base: tuple[float, float] = (720, 300),
    ):
        self.width = width
        self.height = height
        self.obstacles = list(obstacles or [])
        self.terrain = terrain
        self.red_base = red_base
        self.blue_base = blue_base

    def in_bounds(self, x: float, y: float) -> bool:
        """判断坐标是否位于地图范围内。"""
        return 0 <= x <= self.width and 0 <= y <= self.height

    def is_blocked(self, x: float, y: float) -> bool:
        """判断坐标是否落入障碍物。"""
        return any(obstacle.contains(x, y) for obstacle in self.obstacles)

    def clamp_position(self, x: float, y: float) -> tuple[float, float]:
        """将坐标限制在地图范围内。"""
        return max(0, min(self.width, x)), max(0, min(self.height, y))

    def is_position_valid(self, x: float, y: float, domain: str = "ground") -> bool:
        """按平台类型判断坐标是否合法。

        空中单位只受地图边界限制；地面单位和指挥节点不能进入障碍物。
        """
        if not self.in_bounds(x, y):
            return False
        if domain == "air":
            return True
        return not self.is_blocked(x, y)

    def can_move_to(self, x: float, y: float, domain: str = "ground") -> bool:
        """判断单位是否可以移动到指定坐标。"""
        return self.is_position_valid(x, y, domain)

    def base_for_team(self, team: str) -> tuple[float, float]:
        """返回指定阵营的基地坐标。"""
        return self.red_base if team == "red" else self.blue_base
