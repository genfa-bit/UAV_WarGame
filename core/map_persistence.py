"""地图保存与加载。

兼容现有 JSON 场景格式，支持保存/加载障碍物、基地、地形和单位部署。
"""

from __future__ import annotations

import gzip
import json
import os
import sys
import tempfile
import zlib
from pathlib import Path

from core.battlefield import Battlefield
from core.scenario_loader import load_scenario, validate_scenario
from core.units import Unit


# 运行记录归档用 gzip 落盘。JSON 的键名与字段名高度重复，实测 2000 步、16 单位的
# 对局可从 11.1 MB 降到 0.35 MB，而回放与记录的内容一字不变。
GZIP_MAGIC = b"\x1f\x8b"
JOURNAL_COMPRESS_LEVEL = 6

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


def write_json_atomic(filepath: str | Path, data: dict, *, compress: bool = False) -> None:
    """Replace a file only after a complete JSON write in the same directory.

    compress=True 供运行记录归档使用：紧凑分隔符加 gzip，靠体积压住自动保存的整文件
    重写开销。场景另存与用户导出仍写缩进明文，那是要给人看的交付物；两者都由
    read_json_document 读回，所以同一个 .json 文件名可以混放两种形态。
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    if compress:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        # mtime=0 让同样内容产出同样的字节，便于比对与回归测试。
        payload = gzip.compress(text.encode("utf-8"), compresslevel=JOURNAL_COMPRESS_LEVEL, mtime=0)
    else:
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".tmp",
                                         prefix=f".{path.name}.", dir=path.parent, delete=False) as file:
            temporary_path = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def read_json_document(filepath: str | Path) -> dict:
    """读取 JSON 文档，自动识别压缩落盘的运行记录。

    压缩只改字节，不改内容，因此版本 2 的旧明文记录与手写的测试文件照常读取。
    内容损坏统一报 ValueError：断电可能留下半个 gzip 流，而 gzip.decompress 对
    截断输入抛的是 EOFError，不归并的话会绕过调用方已有的 (OSError, ValueError)
    处理，把一条坏记录升级成整个历史列表读不出来。
    """
    raw = Path(filepath).read_bytes()
    if raw[:len(GZIP_MAGIC)] == GZIP_MAGIC:
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError(f"运行记录已损坏：{exc}") from exc
    return json.loads(raw.decode("utf-8"))


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
