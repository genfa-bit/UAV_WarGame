"""地图持久化测试（单位部署保存恢复）与归档 JSON 的读写形态。"""

import gzip
import json
import tempfile
from pathlib import Path

import pytest

from core.battlefield import Battlefield, Obstacle
from core.deployment import DeploymentManager
from core.map_persistence import (GZIP_MAGIC, load_scenario_file, read_json_document,
                                  save_scenario, write_json_atomic)
from core.units import CommandNode, GroundVehicle, MissileVehicle, ScoutDrone, StrikeDrone


def _journal_like_payload(records=400):
    """键名重复的事件流，和运行记录的形状一致。"""
    return {
        "schema_version": 3,
        "run_id": "20260101T000000000000Z-abcdef12",
        "records": [
            {"seq": index, "step": index // 3, "elapsed_seconds": round(index * 0.22, 6),
             "category": "tactical", "event": "unit_state", "unit_id": f"R-SD-{index % 4}",
             "unit_name": "红-侦察无人机", "team": "red", "status": "Move",
             "engagement": "SEARCH", "engagement_label": "搜索", "message": "红-侦察无人机 战术状态：Move / 搜索"}
            for index in range(records)
        ],
    }


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


def test_compressed_journal_round_trips_and_shrinks_the_file():
    payload = _journal_like_payload()
    with tempfile.TemporaryDirectory() as tmpdir:
        directory = Path(tmpdir)
        plain = directory / "plain.json"
        packed = directory / "packed.json"
        write_json_atomic(plain, payload)
        write_json_atomic(packed, payload, compress=True)

        assert packed.read_bytes()[:2] == GZIP_MAGIC
        assert plain.read_bytes()[:2] != GZIP_MAGIC
        # 压缩只改字节：读回来必须是同一份内容，回放与导出都不受影响。
        assert read_json_document(packed) == payload
        assert read_json_document(plain) == payload
        assert packed.stat().st_size < plain.stat().st_size // 4


def test_compressed_write_is_byte_deterministic():
    payload = _journal_like_payload(records=20)
    with tempfile.TemporaryDirectory() as tmpdir:
        first = Path(tmpdir) / "first.json"
        second = Path(tmpdir) / "second.json"
        write_json_atomic(first, payload, compress=True)
        write_json_atomic(second, payload, compress=True)
        # 同样的内容必须产出同样的字节，否则“回放不改写记录”的逐字节比较失去意义。
        assert first.read_bytes() == second.read_bytes()


def test_read_json_document_reports_damaged_and_truncated_files(tmp_path):
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        read_json_document(damaged)

    # 断电可能留下半个 gzip 流；这里必须以调用方已在处理的 ValueError 报出，
    # 否则历史列表会因为一条坏记录整体读不出来。
    truncated = tmp_path / "truncated.json"
    truncated.write_bytes(gzip.compress(b'{"a": 1}', mtime=0)[:10])
    with pytest.raises(ValueError, match="损坏"):
        read_json_document(truncated)


def test_scenario_save_stays_plain_readable_json():
    bf = Battlefield(800, 600, red_base=(80, 300), blue_base=(720, 300))
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "scenario.json"
        save_scenario(bf, _full_scenario_units(), filepath)
        text = filepath.read_text(encoding="utf-8")
        # 场景是交付给用户看的文件，仍要保持缩进明文，不能跟着运行记录一起压缩。
        assert text.startswith("{\n")
        assert json.loads(text)["units"][0]["name"] == "红-侦察无人机"


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
