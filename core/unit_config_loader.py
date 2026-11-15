"""兵种配置加载器。

从 data/unit_config.json 读取各兵种的战斗属性，支持 // 行尾注释。
"""

from __future__ import annotations

import copy
import json
import math
import re
import warnings
from pathlib import Path
from typing import Any

from config import COOPERATIVE_ASSIGNMENT_DEFAULTS


_CONFIG: dict[str, Any] | None = None
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "unit_config.json"
_COOPERATIVE_WARNINGS: set[str] = set()


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


def clear_config_cache() -> None:
    """清空配置缓存（测试或运行时重载配置时使用）。"""
    global _CONFIG
    _CONFIG = None
    _COOPERATIVE_WARNINGS.clear()


def _warn_once(key: str, message: str) -> None:
    if key in _COOPERATIVE_WARNINGS:
        return
    _COOPERATIVE_WARNINGS.add(key)
    warnings.warn(f"协同分配配置无效，已使用缺省值：{message}",
                  RuntimeWarning, stacklevel=3)


def _deep_merge(defaults: dict[str, Any], override: Any) -> dict[str, Any]:
    """递归合并配置，不修改缺省字典。"""
    merged = copy.deepcopy(defaults)
    if not isinstance(override, dict):
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value)))


def _positive_int(config: dict[str, Any], key: str, default: int) -> None:
    value = config.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _warn_once(f"{key}", f"{key}={value!r} 必须是正整数")
        config[key] = default
    else:
        config[key] = value


def _number(config: dict[str, Any], key: str, default: float,
            minimum: float = 0.0) -> None:
    value = config.get(key, default)
    if not _is_number(value) or float(value) < minimum:
        _warn_once(f"{key}", f"{key}={value!r} 必须是 >= {minimum} 的有限数值")
        config[key] = float(default)
    else:
        config[key] = float(value)


def _weights(config: dict[str, Any], key: str,
             defaults: dict[str, float]) -> None:
    provided = config.get(key)
    if not isinstance(provided, dict):
        _warn_once(key, f"{key} 必须是字典")
        config[key] = copy.deepcopy(defaults)
        return
    merged = copy.deepcopy(defaults)
    for name, default in defaults.items():
        value = provided.get(name, default)
        if not _is_number(value) or float(value) < 0.0:
            _warn_once(f"{key}.{name}",
                       f"{key}.{name}={value!r} 必须是 >= 0 的有限数值")
            merged[name] = float(default)
        else:
            merged[name] = float(value)
    config[key] = merged


def _role_fit(config: dict[str, Any],
              defaults: dict[str, dict[str, float]]) -> None:
    provided = config.get("role_fit")
    if not isinstance(provided, dict):
        _warn_once("role_fit", "role_fit 必须是字典")
        config["role_fit"] = copy.deepcopy(defaults)
        return
    merged: dict[str, dict[str, float]] = {}
    for attacker, default_row in defaults.items():
        row = provided.get(attacker)
        if not isinstance(row, dict):
            _warn_once(f"role_fit.{attacker}", f"role_fit.{attacker} 必须是字典")
            row = {}
        merged_row = copy.deepcopy(default_row)
        for target, default in default_row.items():
            value = row.get(target, default)
            if not _is_number(value) or not 0.0 <= float(value) <= 1.0:
                _warn_once(f"role_fit.{attacker}.{target}",
                           f"role_fit.{attacker}.{target}={value!r} 必须在 [0, 1]")
                merged_row[target] = float(default)
            else:
                merged_row[target] = float(value)
        merged[attacker] = merged_row
    config["role_fit"] = merged


def get_cooperative_assignment_config() -> dict[str, Any]:
    """读取并校验 cooperative_assignment 配置。

    配置缺失、类型错误或数值越界时输出一次明确警告并回退到 config.py
    中的缺省值；返回值是深拷贝，调用方可以安全修改。
    """
    raw = load_config().get("cooperative_assignment")
    if not isinstance(raw, dict):
        if raw is not None:
            _warn_once("cooperative_assignment",
                       "cooperative_assignment 必须是字典")
        raw = {}
    config = _deep_merge(COOPERATIVE_ASSIGNMENT_DEFAULTS, raw)

    enabled = config.get("enabled", True)
    if not isinstance(enabled, bool):
        _warn_once("enabled", f"enabled={enabled!r} 必须是布尔值")
        config["enabled"] = True

    _positive_int(config, "replan_interval_steps",
                  COOPERATIVE_ASSIGNMENT_DEFAULTS["replan_interval_steps"])
    _positive_int(config, "max_assignments_per_target",
                  COOPERATIVE_ASSIGNMENT_DEFAULTS["max_assignments_per_target"])
    _positive_int(config, "demand_horizon_steps",
                  COOPERATIVE_ASSIGNMENT_DEFAULTS["demand_horizon_steps"])
    _number(config, "min_assignment_bid",
            COOPERATIVE_ASSIGNMENT_DEFAULTS["min_assignment_bid"])
    _number(config, "switch_penalty",
            COOPERATIVE_ASSIGNMENT_DEFAULTS["switch_penalty"])
    _number(config, "reassign_margin",
            COOPERATIVE_ASSIGNMENT_DEFAULTS["reassign_margin"])
    _number(config, "overload_penalty",
            COOPERATIVE_ASSIGNMENT_DEFAULTS["overload_penalty"])
    _weights(config, "target_priority_weights",
             COOPERATIVE_ASSIGNMENT_DEFAULTS["target_priority_weights"])
    _weights(config, "unit_readiness_weights",
             COOPERATIVE_ASSIGNMENT_DEFAULTS["unit_readiness_weights"])
    _weights(config, "bid_weights",
             COOPERATIVE_ASSIGNMENT_DEFAULTS["bid_weights"])
    _role_fit(config, COOPERATIVE_ASSIGNMENT_DEFAULTS["role_fit"])
    return config
