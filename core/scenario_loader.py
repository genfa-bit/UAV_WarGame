"""JSON 场景加载器。"""

from __future__ import annotations

import json
from pathlib import Path

from core.battlefield import Battlefield, Obstacle
from core.unit_factory import UnitFactory
from core.units import Unit


def load_scenario(path: str | Path) -> tuple[Battlefield, list[Unit]]:
    """从 JSON 文件加载战场、障碍物和作战单位。"""
    scenario_path = Path(path)
    with scenario_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

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
        red_base=tuple(data.get("red_base", [80, 300])),
        blue_base=tuple(data.get("blue_base", [720, 300])),
    )

    units: list[Unit] = []
    for item in data.get("units", []):
        units.append(UnitFactory.create(item))
    return battlefield, units
