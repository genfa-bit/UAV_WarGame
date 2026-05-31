"""地图保存与加载。

兼容现有 JSON 场景格式，支持保存/加载障碍物、基地、地形和单位部署。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.battlefield import Battlefield, Obstacle
from core.scenario_loader import load_scenario
from core.unit_factory import UnitFactory
from core.units import Unit


def save_scenario(
    battlefield: Battlefield,
    units: list[Unit],
    filepath: str | Path,
    terrain: str = "mixed_training_area",
) -> bool:
    """将当前战场和部署单位保存到 JSON 文件。"""
    scenario = {
        "map": {"width": battlefield.width, "height": battlefield.height},
        "terrain": terrain,
        "red_base": list(battlefield.red_base),
        "blue_base": list(battlefield.blue_base),
        "obstacles": [
            {
                "name": obs.name,
                "type": obs.type,
                "x": obs.x,
                "y": obs.y,
                "width": obs.width,
                "height": obs.height,
            }
            for obs in battlefield.obstacles
        ],
        "units": [
            {
                "id": unit.id,
                "name": unit.name,
                "team": unit.team,
                "unit_type": unit.unit_type,
                "x": unit.x,
                "y": unit.y,
            }
            for unit in units
        ],
    }
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(scenario, f, ensure_ascii=False, indent=2)
    return True


def load_scenario_file(filepath: str | Path) -> tuple[Battlefield, list[Unit]]:
    """加载已保存的场景文件，返回战场和单位列表。"""
    return load_scenario(filepath)


def list_scenarios(data_dir: str | Path) -> list[str]:
    """列出 data 目录下的所有 JSON 场景文件。"""
    data_path = Path(data_dir)
    if not data_path.exists():
        return []
    return sorted(
        [f.name for f in data_path.glob("*.json")]
    )
