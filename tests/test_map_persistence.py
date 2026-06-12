"""地图持久化测试（单位部署保存恢复）。"""

import tempfile
from pathlib import Path

from core.battlefield import Battlefield, Obstacle
from core.deployment import DeploymentManager
from core.map_persistence import load_scenario_file, save_scenario
from core.units import CommandNode, GroundVehicle, MissileVehicle, ScoutDrone, StrikeDrone


def _full_scenario_units():
    return [
        ScoutDrone(id="R-SD-1", name="红-侦察无人机", team="red", x=85, y=110),
        StrikeDrone(id="R-AD-1", name="红-打击无人机", team="red", x=105, y=225),
        GroundVehicle(id="R-GV-1", name="红-无人战车", team="red", x=145, y=335),
        MissileVehicle(id="R-MV-1", name="红-导弹发射车", team="red", x=135, y=460),
        CommandNode(id="R-CMD-1", name="红-指挥节点", team="red", x=55, y=520),
        ScoutDrone(id="B-SD-1", name="蓝-侦察无人机", team="blue", x=710, y=115),
        StrikeDrone(id="B-AD-1", name="蓝-打击无人机", team="blue", x=695, y=245),
        GroundVehicle(id="B-GV-1", name="蓝-无人战车", team="blue", x=650, y=355),
        MissileVehicle(id="B-MV-1", name="蓝-导弹发射车", team="blue", x=655, y=480),
        CommandNode(id="B-CMD-1", name="蓝-指挥节点", team="blue", x=745, y=525),
    ]


def test_save_load_full_scenario_roundtrip():
    bf = Battlefield(
        800, 600,
        obstacles=[
            Obstacle(330, 120, 70, 150, name="中央山地", type="mountain"),
            Obstacle(430, 335, 85, 120, name="东侧建筑群", type="building"),
        ],
        red_base=(80, 300),
        blue_base=(720, 300),
    )
    units = _full_scenario_units()

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "full_scene.json"
        save_scenario(bf, units, filepath)

        loaded_bf, loaded_units = load_scenario_file(filepath)

        assert len(loaded_bf.obstacles) == 2
        assert len(loaded_units) == 10
        assert loaded_bf.red_base == (80, 300)
        assert loaded_bf.blue_base == (720, 300)

        teams = {u.team for u in loaded_units}
        assert "red" in teams
        assert "blue" in teams


def test_deployment_manager_loads_saved_scenario():
    bf = Battlefield(800, 600, red_base=(80, 300), blue_base=(720, 300))
    units = _full_scenario_units()

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "deploy_test.json"
        save_scenario(bf, units, filepath)

        loaded_bf, loaded_units = load_scenario_file(filepath)
        dm = DeploymentManager(loaded_bf, loaded_units)

        assert len(dm.display_units()) == 10


def test_save_preserves_unit_positions():
    bf = Battlefield(800, 600)
    units = [
        ScoutDrone(id="R-1", name="红-侦察无人机", team="red", x=123, y=456),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "pos_test.json"
        save_scenario(bf, units, filepath)

        _, loaded_units = load_scenario_file(filepath)
        assert len(loaded_units) == 1
        assert loaded_units[0].x == 123
        assert loaded_units[0].y == 456


def test_save_preserves_obstacle_order():
    bf = Battlefield(800, 600, obstacles=[
        Obstacle(100, 100, 50, 50, name="障碍1", type="building"),
        Obstacle(200, 200, 50, 50, name="障碍2", type="mountain"),
        Obstacle(300, 300, 50, 50, name="障碍3", type="restricted"),
    ])
    units = []

    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "order_test.json"
        save_scenario(bf, units, filepath)

        loaded_bf, _ = load_scenario_file(filepath)
        assert len(loaded_bf.obstacles) == 3
        assert loaded_bf.obstacles[0].name == "障碍1"
        assert loaded_bf.obstacles[1].name == "障碍2"
        assert loaded_bf.obstacles[2].name == "障碍3"
