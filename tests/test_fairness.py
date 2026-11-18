"""红蓝公平性回归：走位与决策不能偏向某一方。

此前有四个系统性偏差：
1. 环绕站位角由单位 ID 决定，点对称战场上双方走位并不镜像；
2. 移动阶段按列表顺序逐个落位，后处理的阵营能看到先移动单位的新位置；
3. 绕障固定“先左后右”、卡死跳跃按阵营硬编码方向，镜像态势下双方绕到
   障碍的同一侧而不是镜像侧；
4. 标准场景的障碍布局与蓝方初始站位不是严格镜像，地图本身偏向一方。
前三条由下面的引擎测试锁定，第四条由场景点对称性测试锁定。
"""

import json
import math
import random
from pathlib import Path

from core.battlefield import Battlefield, Obstacle
from core.pathfinding import move_to, reset_path
from core.scenario_loader import load_scenario
from core.simulator import Simulator
from core.strategy import _ring_point
from core.units import GroundVehicle, ScoutDrone


def test_ring_points_are_mirror_symmetric():
    """同一目标的环绕站位点只取决于单位所在方位，不取决于单位 ID。"""
    red = ScoutDrone(id="R-SD-1", name="红侦察", team="red", x=100, y=250)
    blue = ScoutDrone(id="B-SD-1", name="蓝侦察", team="blue", x=700, y=250)

    red_point = _ring_point(red, 400, 250, 60)
    blue_point = _ring_point(blue, 400, 250, 60)

    # 两个站位点关于目标所在的竖直轴对称，且都落在半径 60 的圈上。
    assert math.isclose(red_point[0], 800 - blue_point[0], abs_tol=1e-9)
    assert math.isclose(red_point[1], blue_point[1], abs_tol=1e-9)
    assert math.isclose(math.dist(red_point, (400, 250)), 60, abs_tol=1e-9)


def _step_positions(blue_first: bool):
    random.seed(0)
    red = ScoutDrone(id="r1", name="红", team="red", x=100, y=200,
                     reaction_delay=100, attack_cooldown=100)
    blue = ScoutDrone(id="b1", name="蓝", team="blue", x=250, y=260,
                      reaction_delay=100, attack_cooldown=100)
    units = [blue, red] if blue_first else [red, blue]
    simulator = Simulator(Battlefield(400, 400), units)
    simulator.step()
    return (red.x, red.y), (blue.x, blue.y)


def test_movement_phase_is_independent_of_unit_order():
    """交换单位在列表中的顺序，同一时间步的落位结果必须完全一致。"""
    assert _step_positions(blue_first=False) == _step_positions(blue_first=True)


def test_symmetric_setup_stays_mirrored(monkeypatch):
    """确定性条件下，点对称的初始态势应保持镜像，双方伤害与状态一致。"""
    monkeypatch.setattr(random, "random", lambda: 0.5)
    monkeypatch.setattr(random, "uniform", lambda a, b: (a + b) / 2)
    monkeypatch.setattr(random, "randint", lambda a, b: (a + b) // 2)

    battlefield = Battlefield(400, 400, red_base=(40, 40), blue_base=(360, 40))
    red = ScoutDrone(id="R-SD-1", name="红", team="red", x=100, y=300,
                     reaction_delay=20, attack_cooldown=30)
    blue = ScoutDrone(id="B-SD-1", name="蓝", team="blue", x=300, y=300,
                      reaction_delay=20, attack_cooldown=30)
    simulator = Simulator(battlefield, [red, blue])

    for _ in range(100):
        simulator.step()

    assert math.isclose(red.x, 400 - blue.x, abs_tol=1e-6)
    assert math.isclose(red.y, blue.y, abs_tol=1e-6)
    assert (red.hp, red.ammo) == (blue.hp, blue.ammo)
    assert simulator.attack_count["red"] == simulator.attack_count["blue"]
    assert simulator.total_damage["red"] == simulator.total_damage["blue"]


STANDARD_SCENARIO = Path(__file__).resolve().parents[1] / "data" / "scenario_1.json"


def test_standard_scenario_is_point_symmetric():
    """标准场景整体关于地图中线镜像：基地、单位和障碍都不能偏向一方。"""
    data = json.loads(STANDARD_SCENARIO.read_text(encoding="utf-8-sig"))
    width = data["map"]["width"]

    red_base = data["red_base"]
    blue_base = data["blue_base"]
    assert blue_base[0] == width - red_base[0]
    assert blue_base[1] == red_base[1]

    red_units = [u for u in data["units"] if u["team"] == "red"]
    blue_units = [u for u in data["units"] if u["team"] == "blue"]
    assert len(red_units) == len(blue_units)
    for red in red_units:
        blue = next(u for u in blue_units if u["unit_type"] == red["unit_type"])
        assert blue["x"] == width - red["x"]
        assert blue["y"] == red["y"]

    # 障碍集合在水平镜像下不变，即每个障碍都有同类型、同尺寸的镜像对应物。
    rects = {(o["type"], o["x"], o["y"], o["width"], o["height"])
             for o in data["obstacles"]}
    mirrored = {(t, width - (x + w), y, w, h) for t, x, y, w, h in rects}
    assert mirrored == rects


def test_obstacle_avoidance_is_mirror_symmetric():
    """镜像态势下绕障方向必须互为镜像，不能固定“先往左绕”。"""
    battlefield = Battlefield(800, 600, obstacles=[
        Obstacle(380, 250, 40, 100, name="中央障碍", type="building"),
    ])
    red = GroundVehicle(id="fair-red-gv", name="红", team="red",
                        x=300, y=300)
    blue = GroundVehicle(id="fair-blue-gv", name="蓝", team="blue",
                         x=500, y=300)
    reset_path(red.id)
    reset_path(blue.id)

    for _ in range(20):
        move_to(red, 700, 300, battlefield)
        move_to(blue, 100, 300, battlefield)
        assert math.isclose(red.x, 800 - blue.x, abs_tol=1e-9)
        assert math.isclose(red.y, blue.y, abs_tol=1e-9)

    reset_path(red.id)
    reset_path(blue.id)


def test_standard_scenario_stays_mirrored_through_obstacles(monkeypatch):
    """标准场景（含对称障碍）在确定性条件下保持镜像。

    旧的绕障逻辑固定先向左，会让红蓝在障碍两侧选择非镜像路线；标准场景
    第 96 步导弹车位置即分叉。这里用真实场景跑 120 步锁住该回归。
    """
    monkeypatch.setattr(random, "random", lambda: 0.5)
    monkeypatch.setattr(random, "uniform", lambda a, b: (a + b) / 2)
    monkeypatch.setattr(random, "randint", lambda a, b: (a + b) // 2)

    battlefield, units = load_scenario(STANDARD_SCENARIO)
    width = battlefield.width
    simulator = Simulator(battlefield, units, max_steps=120)
    for _ in range(120):
        simulator.step()

    reds = [u for u in units if u.team == "red"]
    blues = [u for u in units if u.team == "blue"]
    for red in reds:
        blue = next(u for u in blues if u.unit_type == red.unit_type)
        assert math.isclose(red.x, width - blue.x, abs_tol=1e-5)
        assert math.isclose(red.y, blue.y, abs_tol=1e-5)
        assert (red.hp, red.ammo) == (blue.hp, blue.ammo)

    assert simulator.attack_count["red"] == simulator.attack_count["blue"]
    assert simulator.total_damage["red"] == simulator.total_damage["blue"]
