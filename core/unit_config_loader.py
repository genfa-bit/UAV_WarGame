"""兵种配置加载器。

从 data/unit_config.json 读取各兵种的战斗属性，支持 // 行尾注释。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_CONFIG: dict[str, Any] | None = None
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "unit_config.json"


def _strip_comments(json_text: str) -> str:
    """移除 JSON 中的 // 行注释。"""
    lines = []
    for line in json_text.split("\n"):
        # 移除 // 到行尾的内容，保留前面的 JSON
        match = re.match(r'^(.*?)\s*//', line)
        if match:
            line = match.group(1)
        lines.append(line)
    return "\n".join(lines)


def load_config() -> dict[str, Any]:
    """加载兵种配置（缓存后重复调用直接返回）。"""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = f.read()
    cleaned = _strip_comments(raw)
    _CONFIG = json.loads(cleaned)
    return _CONFIG


def get_unit_stats(unit_type: str) -> dict[str, Any]:
    """获取指定兵种的配置字典。"""
    cfg = load_config()
    if unit_type not in cfg:
        raise KeyError(f"未知兵种类型: {unit_type}，请检查 data/unit_config.json")
    return cfg[unit_type]
