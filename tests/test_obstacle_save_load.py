"""地图保存与加载功能测试。"""

import json
import os
import tempfile
from pathlib import Path

from core.battlefield import Battlefield, Obstacle
from core.map_persistence import list_scenarios, load_scenario_file, save_scenario
from core.units import ScoutDrone, StrikeDrone


def _battlefield():
    return Battlefield(
        800, 600,
        obstacles=[
            Obstacle(100, 100, 80, 60, name="测试山", type="mountain"),
        ],
        red_base=(100, 300),
        blue_base=(700, 300),
    )


def _units():
    return [
        ScoutDrone(id="R-SD-1", name="红-侦察无人机", team="red", x=50, y=50),
        StrikeDrone(id="B-AD-1", name="蓝-打击无人机", team="blue", x=700, y=100),
    ]


def test_save_and_load_preserves_obstacles():
    bf = _battlefield()
    units = _units()

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_scene.json"
        save_scenario(bf, units, filepath)

        assert filepath.exists()
        loaded_bf, loaded_units = load_scenario_file(filepath)

        assert len(loaded_bf.obstacles) == 1
        obs = loaded_bf.obstacles[0]
        assert obs.name == "测试山"
        assert obs.type == "mountain"
        assert obs.x == 100
        assert obs.y == 100


def test_save_and_load_preserves_bases():
    bf = _battlefield()
    units = _units()

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_bases.json"
        save_scenario(bf, units, filepath)

        loaded_bf, _ = load_scenario_file(filepath)

        assert loaded_bf.red_base == (100, 300)
        assert loaded_bf.blue_base == (700, 300)


def test_save_and_load_preserves_units():
    bf = _battlefield()
    units = _units()

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_units.json"
        save_scenario(bf, units, filepath)

        _, loaded_units = load_scenario_file(filepath)

        assert len(loaded_units) == 2
        assert loaded_units[0].name == "红-侦察无人机"
        assert loaded_units[0].unit_type == "scout_drone"
        assert loaded_units[1].name == "蓝-打击无人机"


def test_save_creates_valid_json():
    bf = _battlefield()
    units = _units()

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "test_valid.json"
        save_scenario(bf, units, filepath)

        with filepath.open("r", encoding="utf-8") as f:
            data = json.load(f)

        assert "map" in data
        assert "obstacles" in data
        assert "units" in data
        assert "red_base" in data
        assert "blue_base" in data


def test_list_scenarios():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "a.json").touch()
        Path(tmpdir, "b.json").touch()
        Path(tmpdir, "readme.txt").touch()

        files = list_scenarios(tmpdir)
        assert len(files) == 2
        assert "a.json" in files
        assert "b.json" in files


def test_list_scenarios_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        files = list_scenarios(tmpdir)
        assert files == []


def test_list_scenarios_nonexistent_dir():
    files = list_scenarios("/nonexistent/path/12345")
    assert files == []
