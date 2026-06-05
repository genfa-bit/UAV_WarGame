"""中文界面翻译测试。"""

from config import (
    OBSTACLE_TYPE_LABELS,
    STATE_LABELS,
    STATUS_LABELS,
    UNIT_TYPE_LABELS,
)


def test_status_labels_chinese():
    assert STATUS_LABELS["Scout"] == "侦察"
    assert STATUS_LABELS["Move"] == "机动"
    assert STATUS_LABELS["Attack"] == "攻击"
    assert STATUS_LABELS["Evade"] == "规避"
    assert STATUS_LABELS["Destroyed"] == "已摧毁"


def test_state_labels_chinese():
    assert STATE_LABELS["deployment"] == "部署阶段"
    assert STATE_LABELS["running"] == "运行中"
    assert STATE_LABELS["paused"] == "已暂停"
    assert STATE_LABELS["finished"] == "已结束"


def test_unit_type_labels_chinese():
    assert UNIT_TYPE_LABELS["scout_drone"] == "侦察无人机"
    assert UNIT_TYPE_LABELS["strike_drone"] == "打击无人机"
    assert UNIT_TYPE_LABELS["ground_vehicle"] == "无人战车"
    assert UNIT_TYPE_LABELS["missile_vehicle"] == "导弹发射车"
    assert UNIT_TYPE_LABELS["command_node"] == "指挥节点"


def test_obstacle_type_labels_chinese():
    assert OBSTACLE_TYPE_LABELS["mountain"] == "山地"
    assert OBSTACLE_TYPE_LABELS["building"] == "建筑"
    assert OBSTACLE_TYPE_LABELS["restricted"] == "禁行区"


def test_status_labels_covers_all():
    for status in ["Scout", "Move", "Attack", "Evade", "Destroyed"]:
        assert status in STATUS_LABELS


def test_state_labels_covers_all():
    for state in ["deployment", "running", "paused", "finished"]:
        assert state in STATE_LABELS
