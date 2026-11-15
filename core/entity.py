"""实体基础类。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from math import hypot


def stable_unit_angle(unit_id: str) -> float:
    """由单位 ID 生成稳定角度（弧度），用于分散同点单位的站位方向。

    不使用内置 ``hash()``：字符串哈希在每个进程中随机化，会破坏确定性回放。
    """
    seed = 0
    for char in unit_id:
        seed = (seed * 131 + ord(char)) & 0xFFFFFFFF
    return (seed % 360) * math.pi / 180.0


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
