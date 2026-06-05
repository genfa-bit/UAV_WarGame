"""战场地图模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from config import BASE_MAX_HP, BASE_REPAIR_PER_STEP


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


class Base:
    """己方基地：可受伤、可为周围友军补给。"""

    def __init__(self, team: str, x: float, y: float):
        self.team = team
        self.x = x
        self.y = y
        self.hp = BASE_MAX_HP
        self.max_hp = BASE_MAX_HP

    @property
    def is_destroyed(self) -> bool:
        return self.hp <= 0

    @property
    def hp_ratio(self) -> float:
        return max(0, self.hp / self.max_hp)

    def take_damage(self, amount: int) -> int:
        before = self.hp
        self.hp = max(0, self.hp - amount)
        return before - self.hp

    def pos(self) -> tuple[float, float]:
        return (self.x, self.y)


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
    ):
        self.width = width
        self.height = height
        self.obstacles = list(obstacles or [])
        self.terrain = terrain
        self.red_base_obj = Base("red", *red_base)
        self.blue_base_obj = Base("blue", *blue_base)

    @property
    def red_base(self) -> tuple[float, float]:
        return self.red_base_obj.pos()

    @red_base.setter
    def red_base(self, value: tuple[float, float]) -> None:
        self.red_base_obj.x, self.red_base_obj.y = value

    @property
    def blue_base(self) -> tuple[float, float]:
        return self.blue_base_obj.pos()

    @blue_base.setter
    def blue_base(self, value: tuple[float, float]) -> None:
        self.blue_base_obj.x, self.blue_base_obj.y = value

    def in_bounds(self, x: float, y: float) -> bool:
        return 0 <= x <= self.width and 0 <= y <= self.height

    def is_blocked(self, x: float, y: float) -> bool:
        return any(o.contains(x, y) for o in self.obstacles)

    def clamp_position(self, x: float, y: float) -> tuple[float, float]:
        return max(0, min(self.width, x)), max(0, min(self.height, y))

    def is_position_valid(self, x: float, y: float, domain: str = "ground") -> bool:
        if not self.in_bounds(x, y):
            return False
        if domain == "air":
            return True
        return not self.is_blocked(x, y)

    def can_move_to(self, x: float, y: float, domain: str = "ground") -> bool:
        return self.is_position_valid(x, y, domain)

    def base_for_team(self, team: str) -> tuple[float, float]:
        return self.red_base if team == "red" else self.blue_base

    def base_obj(self, team: str) -> Base:
        return self.red_base_obj if team == "red" else self.blue_base_obj
