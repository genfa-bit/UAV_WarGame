"""JSON 场景加载器。"""

from __future__ import annotations

import json
import math
from pathlib import Path

from core.battlefield import Battlefield, Obstacle
from core.terrain_catalog import MAP_STYLES
from core.unit_factory import UNIT_REGISTRY, UnitFactory
from core.units import Unit


def _number(value, label: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是数字")
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{label} 必须是大于等于 {minimum} 的有限数字")
    return value


def validate_scenario(data: dict) -> None:
    """Validate a complete input before creating or replacing application state."""
    if not isinstance(data, dict):
        raise ValueError("场景内容必须是 JSON 对象")
    map_data = data.get("map", {})
    if not isinstance(map_data, dict):
        raise ValueError("map 必须是对象")
    width = _number(map_data.get("width", 800), "地图宽度", minimum=1)
    height = _number(map_data.get("height", 600), "地图高度", minimum=1)
    style = map_data.get("style", "tactical")
    if not isinstance(style, str) or style not in MAP_STYLES:
        raise ValueError("map.style 必须为 tactical、valley 或 river")
    if not isinstance(data.get("terrain", "plain"), str):
        raise ValueError("terrain 必须是文字")

    def position(x, y, label):
        if _number(x, f"{label} x") > width or _number(y, f"{label} y") > height:
            raise ValueError(f"{label} 超出地图边界")

    for key in ("red_base", "blue_base"):
        if key not in data:
            continue
        base = data[key]
        if not isinstance(base, (list, tuple)) or len(base) != 2:
            raise ValueError(f"{key} 必须包含两个坐标")
        position(base[0], base[1], key)

    obstacles = data.get("obstacles", [])
    units = data.get("units", [])
    if not isinstance(obstacles, list) or not isinstance(units, list):
        raise ValueError("obstacles 和 units 必须是列表")
    for index, item in enumerate(obstacles):
        label = f"障碍物 {index + 1}"
        if not isinstance(item, dict):
            raise ValueError(f"{label} 必须是对象")
        for key in ("x", "y", "width", "height"):
            if key not in item:
                raise ValueError(f"{label} 缺少 {key}")
        position(item["x"], item["y"], label)
        obstacle_width = _number(item["width"], f"{label} 宽度", minimum=1)
        obstacle_height = _number(item["height"], f"{label} 高度", minimum=1)
        if item["x"] + obstacle_width > width or item["y"] + obstacle_height > height:
            raise ValueError(f"{label} 超出地图边界")
        if not isinstance(item.get("name", "障碍物"), str):
            raise ValueError(f"{label} 名称必须是文字")
        if item.get("type", "obstacle") not in ("obstacle", "mountain", "building", "restricted"):
            raise ValueError(f"{label} 类型无效")

    ids = set()
    for index, item in enumerate(units):
        label = f"单位 {index + 1}"
        if not isinstance(item, dict):
            raise ValueError(f"{label} 必须是对象")
        for key in ("id", "team", "x", "y"):
            if key not in item:
                raise ValueError(f"{label} 缺少 {key}")
        unit_id = item["id"]
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise ValueError(f"{label} ID 必须是非空文字")
        if unit_id in ids or unit_id in ("red_base", "blue_base"):
            raise ValueError(f"单位 ID 重复或保留：{unit_id}")
        ids.add(unit_id)
        if item["team"] not in ("red", "blue"):
            raise ValueError(f"{label} 阵营必须是 red 或 blue")
        if item.get("unit_type", item.get("type")) not in UNIT_REGISTRY:
            raise ValueError(f"{label} 兵种无效")
        if "name" in item and not isinstance(item["name"], str):
            raise ValueError(f"{label} 名称必须是文字")
        position(item["x"], item["y"], label)
        for key in ("hp", "max_hp", "speed", "detect_range", "attack_range", "attack_power", "ammo",
                    "reaction_delay", "attack_cooldown", "base_hit_prob", "threat_value"):
            if key in item:
                _number(item[key], f"{label} {key}")
        for key in ("can_attack_air", "can_attack_ground"):
            if key in item and not isinstance(item[key], bool):
                raise ValueError(f"{label} {key} 必须是布尔值")
        if "base_hit_prob" in item and item["base_hit_prob"] > 1:
            raise ValueError(f"{label} 命中概率必须在 0 到 1 之间")


def scenario_from_data(data: dict) -> tuple[Battlefield, list[Unit]]:
    """Construct a validated battlefield without mutating an existing scene."""
    validate_scenario(data)

    map_data = data.get("map", {})
    obstacles = [
        Obstacle(
            x=item["x"],
            y=item["y"],
            width=item["width"],
            height=item["height"],
            name=item.get("name", "障碍物"),
            type=item.get("type", "obstacle"),
        )
        for item in data.get("obstacles", [])
    ]
    battlefield = Battlefield(
        width=map_data.get("width", 800),
        height=map_data.get("height", 600),
        obstacles=obstacles,
        terrain=data.get("terrain", "plain"),
        map_style=map_data.get("style", "tactical"),
        red_base=tuple(data.get("red_base", [map_data.get("width", 800) * 0.1, map_data.get("height", 600) * 0.5])),
        blue_base=tuple(data.get("blue_base", [map_data.get("width", 800) * 0.9, map_data.get("height", 600) * 0.5])),
    )

    units: list[Unit] = []
    for item in data.get("units", []):
        unit_data = dict(item)
        unit_data.setdefault("name", unit_data["id"])
        units.append(UnitFactory.create(unit_data))
    return battlefield, units


def load_scenario(path: str | Path) -> tuple[Battlefield, list[Unit]]:
    """从 JSON 文件加载并校验战场、障碍物和作战单位。"""
    with Path(path).open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    return scenario_from_data(data)
