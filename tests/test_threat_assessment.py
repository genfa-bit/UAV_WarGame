"""威胁评估系统测试。"""

from core.threat import (priority_targets, situation_label,
                         tactics_label, team_strength, threat_score)
from core.units import (CommandNode, GroundVehicle, MissileVehicle,
                        ScoutDrone, StrikeDrone)


def _enemies():
    return [
        MissileVehicle(id="B-MV-1", name="蓝-导弹发射车", team="blue", x=400, y=300),
        StrikeDrone(id="B-AD-1", name="蓝-打击无人机", team="blue", x=420, y=310),
        GroundVehicle(id="B-GV-1", name="蓝-无人战车", team="blue", x=380, y=320),
        ScoutDrone(id="B-SD-1", name="蓝-侦察无人机", team="blue", x=500, y=200),
        CommandNode(id="B-CMD-1", name="蓝-指挥节点", team="blue", x=700, y=500),
    ]


def _friendlies():
    return [ScoutDrone(id="R-SD-1", name="红-侦察无人机", team="red", x=100, y=100)]


def test_missile_vehicle_highest_threat():
    enemies = _enemies()
    ref = _friendlies()[0]
    scores = [(e.name, threat_score(e, ref)) for e in enemies]
    scores.sort(key=lambda x: x[1], reverse=True)
    assert "导弹发射车" in scores[0][0]


def test_command_node_lowest_threat():
    enemies = _enemies()
    ref = _friendlies()[0]
    scores = [(e.name, threat_score(e, ref)) for e in enemies]
    scores.sort(key=lambda x: x[1])
    assert "指挥节点" in scores[0][0]


def test_threat_score_positive():
    for e in _enemies():
        assert threat_score(e) > 0


def test_priority_targets_sorted():
    result = priority_targets(_enemies(), _friendlies())
    assert len(result) == 5
    assert result[0].unit_type == "missile_vehicle"


def test_priority_targets_empty():
    assert priority_targets([], []) == []


def test_priority_targets_excludes_destroyed():
    enemies = _enemies()
    enemies[0].hp = 0
    result = priority_targets(enemies, _friendlies())
    assert len(result) == 4


def test_team_strength():
    units = [
        ScoutDrone(id="R-1", name="红-侦察", team="red", x=100, y=100),
        StrikeDrone(id="R-2", name="红-打击", team="red", x=120, y=120),
    ]
    assert team_strength(units) > 0


def test_team_strength_empty():
    assert team_strength([]) == 0.0


def test_situation_advantage():
    assert situation_label(200, 100, "red") == "优势"


def test_situation_disadvantage():
    assert situation_label(80, 100, "red") == "劣势"


def test_situation_equal():
    assert situation_label(100, 100, "red") == "均势"


def test_tactics_labels():
    assert tactics_label("优势") == "进攻"
    assert tactics_label("均势") == "协同推进"
    assert tactics_label("劣势") == "保守推进"
