"""实体基础类。"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot


@dataclass
class Entity:
    """所有战场对象的基础信息。"""

    id: str
    name: str
    team: str
    x: float
    y: float

    def distance_to(self, other: "Entity") -> float:
        """计算到另一个实体的欧氏距离。"""
        return hypot(self.x - other.x, self.y - other.y)
