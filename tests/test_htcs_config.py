"""HTCS 配置开关与校验单元测试。

配置读取路径：``data/unit_config.json`` 的 ``cooperative_assignment`` 段。
这里通过 monkeypatch ``load_config`` 注入最小配置，只验证
``get_cooperative_assignment_config()`` 的模式选择、深合并与容错回退。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

import core.unit_config_loader as loader
from config import COOPERATIVE_ASSIGNMENT_DEFAULTS, HTCS_DEFAULTS


def _load(monkeypatch, cooperative):
    """注入 cooperative_assignment 配置并返回校验后的副本。"""
    monkeypatch.setattr(
        loader, "load_config",
        lambda: {"cooperative_assignment": deepcopy(cooperative)})
    loader._COOPERATIVE_WARNINGS.clear()
    return loader.get_cooperative_assignment_config()


def test_default_mode_is_rdma_v2_and_keeps_legacy_behavior():
    config = deepcopy(COOPERATIVE_ASSIGNMENT_DEFAULTS)
    assert config["mode"] == "rdma_v2"
    assert config["enabled"] is True


def test_htcs_defaults_cover_every_documented_knob():
    expected = {
        "wave_length_steps", "bundle_size", "tot_tolerance_steps",
        "tot_late_steps", "staging_standoff_ratio", "ammo_reserve_ratio",
        "fire_discipline", "overkill_fire_ratio", "opportunity_fire",
        "bda_enabled", "bda_delivery_ratio", "reattack_delay_steps",
        "reattack_bonus", "sead_enabled", "sead_effect_ratio",
        "sead_suppression_steps", "sead_defense_radius", "doctrine",
        "doctrine_advantage_ratio", "doctrine_disadvantage_ratio",
        "distributed_fallback", "max_tasks_per_wave",
        "planning_horizon_waves",
    }
    assert set(HTCS_DEFAULTS) == expected


def test_mode_htcs_is_accepted(monkeypatch):
    config = _load(monkeypatch, {"mode": "htcs"})
    assert config["mode"] == "htcs"


def test_unknown_mode_falls_back_to_rdma_v2_with_warning(monkeypatch):
    with pytest.warns(RuntimeWarning, match="mode"):
        config = _load(monkeypatch, {"mode": "swarm_v9"})
    assert config["mode"] == "rdma_v2"


def test_missing_htcs_block_is_filled_with_defaults(monkeypatch):
    config = _load(monkeypatch, {"mode": "htcs"})
    assert config["htcs"] == HTCS_DEFAULTS
    assert config["htcs"]["wave_length_steps"] == 6
    assert config["htcs"]["doctrine"] == "adaptive"


def test_partial_htcs_block_deep_merges_with_defaults(monkeypatch):
    config = _load(monkeypatch, {
        "mode": "htcs",
        "htcs": {"wave_length_steps": 9, "doctrine": "attrition"},
    })
    assert config["htcs"]["wave_length_steps"] == 9
    assert config["htcs"]["doctrine"] == "attrition"
    # 未提供的键保持缺省值
    assert config["htcs"]["bundle_size"] == HTCS_DEFAULTS["bundle_size"]
    assert config["htcs"]["sead_enabled"] is True


@pytest.mark.parametrize("key", ["wave_length_steps", "bundle_size",
                                 "max_tasks_per_wave",
                                 "planning_horizon_waves"])
@pytest.mark.parametrize("bad", [0, -3, 2.5, True, "6"])
def test_positive_int_knobs_fall_back(monkeypatch, key, bad):
    with pytest.warns(RuntimeWarning):
        config = _load(monkeypatch, {"htcs": {key: bad}})
    assert config["htcs"][key] == HTCS_DEFAULTS[key]


@pytest.mark.parametrize("key", ["tot_tolerance_steps", "tot_late_steps",
                                 "reattack_delay_steps",
                                 "sead_suppression_steps"])
def test_nonnegative_int_knobs_fall_back(monkeypatch, key):
    with pytest.warns(RuntimeWarning):
        config = _load(monkeypatch, {"htcs": {key: -1}})
    assert config["htcs"][key] == HTCS_DEFAULTS[key]


@pytest.mark.parametrize("key,value", [
    ("ammo_reserve_ratio", 1.5),
    ("sead_effect_ratio", -0.1),
    ("bda_delivery_ratio", 2.0),
    ("overkill_fire_ratio", 0.5),
    ("tot_tolerance_steps", 1.5),
])
def test_bounded_numbers_fall_back(monkeypatch, key, value):
    with pytest.warns(RuntimeWarning):
        config = _load(monkeypatch, {"htcs": {key: value}})
    assert config["htcs"][key] == HTCS_DEFAULTS[key]


@pytest.mark.parametrize("key", ["fire_discipline", "opportunity_fire",
                                 "bda_enabled", "sead_enabled",
                                 "distributed_fallback"])
def test_boolean_knobs_reject_non_bool(monkeypatch, key):
    with pytest.warns(RuntimeWarning):
        config = _load(monkeypatch, {"htcs": {key: "yes"}})
    assert config["htcs"][key] is HTCS_DEFAULTS[key]


def test_doctrine_enum_rejects_unknown_value(monkeypatch):
    with pytest.warns(RuntimeWarning, match="doctrine"):
        config = _load(monkeypatch, {"htcs": {"doctrine": "berserk"}})
    assert config["htcs"]["doctrine"] == "adaptive"


def test_returned_config_is_a_safe_copy(monkeypatch):
    first = _load(monkeypatch, {"mode": "htcs"})
    first["htcs"]["wave_length_steps"] = 999
    second = _load(monkeypatch, {"mode": "htcs"})
    assert second["htcs"]["wave_length_steps"] == 6
