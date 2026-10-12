"""地图保存与加载。

兼容现有 JSON 场景格式，支持保存/加载障碍物、基地、地形和单位部署。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from core.battlefield import Battlefield
from core.scenario_loader import load_scenario, validate_scenario
from core.units import Unit


BUILTIN_SCENARIO_DIR = Path(__file__).resolve().parent.parent / "data"
BUILTIN_SCENARIOS = (
    ("standard", "标准对抗", "scenario_1.json"),
    ("obstacles", "障碍环境", "scenario_obstacles.json"),
    ("custom", "自定义场景", "scenario_custom.json"),
    ("valley", "山区河谷", "scenario_valley.json"),
    ("river_city", "河谷城镇", "scenario_river_city.json"),
)


def user_scenario_dir() -> Path:
    """User files must survive PyInstaller's temporary resource directory."""
    override = os.environ.get("UAV_WARGAME_DATA_DIR")
    if override:
        return Path(override).expanduser() / "scenarios"
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "UAV_WarGame" / "scenarios"


def is_builtin_scenario(filepath: str | Path) -> bool:
    path = Path(filepath).resolve()
    return any(path == (BUILTIN_SCENARIO_DIR / filename).resolve()
               for _, _, filename in BUILTIN_SCENARIOS)


def write_json_atomic(filepath: str | Path, data: dict) -> None:
    """Replace a file only after a complete JSON write in the same directory."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp",
                                         prefix=f".{path.name}.", dir=path.parent, delete=False) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def scenario_data(battlefield: Battlefield, units: list[Unit], terrain: str | None = None) -> dict:
    """Serialize deployment data, keeping the loaded scene's terrain."""
    return {
        "map": {"width": battlefield.width, "height": battlefield.height,
                "style": battlefield.map_style},
        "terrain": battlefield.terrain if terrain is None else terrain,
        "red_base": list(battlefield.red_base),
        "blue_base": list(battlefield.blue_base),
        "obstacles": [
            {"name": obs.name, "type": obs.type, "x": obs.x, "y": obs.y,
             "width": obs.width, "height": obs.height}
            for obs in battlefield.obstacles
        ],
        "units": [
            {"id": unit.id, "name": unit.name, "team": unit.team,
             "unit_type": unit.unit_type, "x": unit.x, "y": unit.y}
            for unit in units
        ],
    }


def save_scenario(
    battlefield: Battlefield,
    units: list[Unit],
    filepath: str | Path,
    terrain: str | None = None,
) -> bool:
    """将当前战场和部署单位保存到 JSON 文件。"""
    if is_builtin_scenario(filepath):
        raise ValueError("内置预设为只读，请另存为用户场景")
    scenario = scenario_data(battlefield, units, terrain)
    validate_scenario(scenario)
    write_json_atomic(filepath, scenario)
    return True


def load_scenario_file(filepath: str | Path) -> tuple[Battlefield, list[Unit]]:
    """加载已保存的场景文件，返回战场和单位列表。"""
    return load_scenario(filepath)


def list_scenarios(data_dir: str | Path | None = None) -> list[str]:
    """列出 data 目录下的所有 JSON 场景文件。"""
    data_path = Path(data_dir) if data_dir is not None else user_scenario_dir()
    if not data_path.exists():
        return []
    return sorted(
        [f.name for f in data_path.glob("*.json") if f.is_file()]
    )
