"""部署阶段管理器。

DeploymentManager 负责预设开局和手动部署的规则判断，避免 main.py
堆积部署细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import DEPLOY_MANUAL, DEPLOY_PRESET, STATUS_MOVE, TEAM_BLUE, TEAM_RED
from core.battlefield import Battlefield
from core.unit_factory import UnitFactory
from core.units import Unit


UNIT_LABELS = {
    "scout_drone": "侦察无人机",
    "strike_drone": "打击无人机",
    "ground_vehicle": "无人战车",
    "missile_vehicle": "导弹发射车",
    "command_node": "指挥节点",
}

UNIT_KEYS = {
    "1": "scout_drone",
    "2": "strike_drone",
    "3": "ground_vehicle",
    "4": "missile_vehicle",
    "5": "command_node",
}

EVENT_KEYDOWN = 768
EVENT_MOUSEBUTTONDOWN = 1025
KEY_ESCAPE = 27
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_1 = 49
KEY_2 = 50
KEY_3 = 51
KEY_4 = 52
KEY_5 = 53
KEY_C = 99
KEY_M = 109
KEY_R = 114
KEY_T = 116

UNIT_KEY_CODES = {
    KEY_1: "scout_drone",
    KEY_2: "strike_drone",
    KEY_3: "ground_vehicle",
    KEY_4: "missile_vehicle",
    KEY_5: "command_node",
}


@dataclass
class DeploymentResult:
    """部署开始校验结果。"""

    ok: bool
    units: list[Unit]
    message: str = ""


class DeploymentManager:
    """管理部署模式、当前选择、手动部署单位和错误提示。"""

    def __init__(self, battlefield: Battlefield, preset_units: list[Unit]):
        self.battlefield = battlefield
        self.preset_units = preset_units
        self.mode = DEPLOY_PRESET
        self.selected_team = TEAM_RED
        self.selected_unit_type = "scout_drone"
        self.manual_units: list[Unit] = []
        self.last_message = "部署阶段：按 Enter 使用预设开局开始仿真"
        self._sequence = 1

    def toggle_mode(self) -> None:
        """切换预设/手动部署模式。"""
        self.mode = DEPLOY_MANUAL if self.mode == DEPLOY_PRESET else DEPLOY_PRESET
        self.last_message = f"已切换到 {'Manual' if self.mode == DEPLOY_MANUAL else 'Preset'} 模式"

    def toggle_team(self) -> None:
        """切换当前部署阵营。"""
        self.selected_team = TEAM_BLUE if self.selected_team == TEAM_RED else TEAM_RED
        self.last_message = f"当前部署阵营：{self.selected_team}"

    def select_unit_type(self, unit_type: str) -> None:
        """选择当前部署兵种。"""
        if unit_type not in UNIT_LABELS:
            self.last_message = f"未知兵种：{unit_type}"
            return
        self.selected_unit_type = unit_type
        self.last_message = f"当前选择兵种：{self.selected_label}"

    def handle_key(self, key: int, key_text: str = "") -> str | None:
        """处理部署阶段键盘输入。"""
        normalized_text = key_text.lower()
        if key == KEY_ESCAPE:
            return "quit"
        if key == KEY_RETURN:
            result = self.finalize()
            return "start" if result.ok else None
        if key == KEY_M or normalized_text == "m":
            self.toggle_mode()
        elif key == KEY_T or normalized_text == "t":
            self.toggle_team()
        elif key == KEY_BACKSPACE:
            self.undo()
        elif key == KEY_C or normalized_text == "c":
            self.clear_manual()
        elif key == KEY_R or normalized_text == "r":
            self.reset_to_preset()
            return "reset"
        elif key in UNIT_KEY_CODES:
            self.select_unit_type(UNIT_KEY_CODES[key])
        elif normalized_text in UNIT_KEYS:
            self.select_unit_type(UNIT_KEYS[normalized_text])
        else:
            self.last_message = f"未识别的部署按键：{key_text or key}"
        return None

    def handle_mouse_button(self, button: int, pos: tuple[float, float], battlefield: Battlefield | None = None) -> str | None:
        """处理部署阶段鼠标输入，并保证左侧地图点击总有面板反馈。"""
        if button != 1:
            return None

        active_battlefield = battlefield or self.battlefield
        x, y = pos
        if x >= active_battlefield.width:
            self.last_message = "点击被忽略：右侧信息面板不是部署区域"
            return None

        if self.mode != DEPLOY_MANUAL:
            self.last_message = f"地图点击 ({int(x)}, {int(y)})：当前为 Preset 模式，按 M 切换到 Manual 后部署"
            return None

        placed = self.place_unit(x, y)
        if not placed and not self.last_message.startswith("地图点击"):
            self.last_message = f"地图点击 ({int(x)}, {int(y)})：{self.last_message}"
        return None

    def handle_event(self, event: Any, battlefield: Battlefield | None = None) -> str | None:
        """处理部署阶段输入事件。

        返回 "start"、"reset"、"quit" 或 None，供主循环执行状态切换。
        """
        if event.type == EVENT_KEYDOWN:
            return self.handle_key(event.key, getattr(event, "unicode", ""))

        if event.type == EVENT_MOUSEBUTTONDOWN:
            return self.handle_mouse_button(event.button, event.pos, battlefield)

        return None

    def place_unit(self, x: float, y: float) -> bool:
        """在地图上放置当前兵种。"""
        if self.mode != DEPLOY_MANUAL:
            self.last_message = "当前为 Preset 模式，按 M 切换到 Manual 后部署"
            return False
        if not self.battlefield.in_bounds(x, y):
            self.last_message = "部署失败：不能部署在地图外"
            return False

        unit = self._build_unit(x, y)
        if not self.is_valid_position(unit, x, y):
            self.last_message = "部署失败：该兵种不能部署在障碍物中"
            return False

        self.manual_units.append(unit)
        self._sequence += 1
        self.last_message = f"已部署 {unit.name}"
        return True

    def undo(self) -> bool:
        """撤销最近一次手动部署。"""
        if not self.manual_units:
            self.last_message = "没有可撤销的部署"
            return False
        removed = self.manual_units.pop()
        self.last_message = f"已撤销 {removed.name}"
        return True

    def clear_manual(self) -> None:
        """清空所有手动部署单位。"""
        self.manual_units.clear()
        self.last_message = "已清空手动部署"

    def reset_to_preset(self, preset_units: list[Unit] | None = None) -> None:
        """恢复预设开局。"""
        if preset_units is not None:
            self.preset_units = preset_units
        self.mode = DEPLOY_PRESET
        self.manual_units.clear()
        self._sequence = 1
        self.last_message = "已恢复预设开局"

    def display_units(self) -> list[Unit]:
        """返回部署阶段地图上需要显示的单位。"""
        return self.preset_units if self.mode == DEPLOY_PRESET else self.manual_units

    def finalize(self) -> DeploymentResult:
        """完成部署并返回用于创建 Simulator 的单位列表。"""
        units = self.display_units()
        if not units:
            self.last_message = "无法开始：请至少部署红蓝双方单位"
            return DeploymentResult(False, [], self.last_message)

        teams = {unit.team for unit in units if unit.is_alive()}
        if TEAM_RED not in teams or TEAM_BLUE not in teams:
            self.last_message = "无法开始：红蓝双方都需要至少一个单位"
            return DeploymentResult(False, [], self.last_message)

        self.last_message = "部署完成，开始仿真"
        return DeploymentResult(True, [self._clone_unit(unit) for unit in units], self.last_message)

    def is_valid_position(self, unit: Unit, x: float, y: float) -> bool:
        """检查部署位置合法性。"""
        if not self.battlefield.in_bounds(x, y):
            return False
        return self.battlefield.is_position_valid(x, y, unit.domain)

    @property
    def selected_label(self) -> str:
        return UNIT_LABELS[self.selected_unit_type]

    @property
    def mode_label(self) -> str:
        return "Manual" if self.mode == DEPLOY_MANUAL else "Preset"

    def _build_unit(self, x: float, y: float) -> Unit:
        prefix = "R" if self.selected_team == TEAM_RED else "B"
        unit_id = f"{prefix}-MAN-{self._sequence:03d}"
        unit_name = f"{'红' if self.selected_team == TEAM_RED else '蓝'}-{self.selected_label}{self._sequence}"
        return UnitFactory.create(
            {
                "id": unit_id,
                "name": unit_name,
                "team": self.selected_team,
                "unit_type": self.selected_unit_type,
                "x": x,
                "y": y,
            }
        )

    def _clone_unit(self, unit: Unit) -> Unit:
        return UnitFactory.create(
            {
                "id": unit.id,
                "name": unit.name,
                "team": unit.team,
                "unit_type": unit.unit_type,
                "x": unit.x,
                "y": unit.y,
                "hp": unit.hp,
                "max_hp": unit.max_hp,
                "speed": unit.speed,
                "detect_range": unit.detect_range,
                "attack_range": unit.attack_range,
                "attack_power": unit.attack_power,
                "ammo": unit.ammo,
                "status": STATUS_MOVE,
                "target_id": None,
                "can_attack_air": unit.can_attack_air,
                "can_attack_ground": unit.can_attack_ground,
            }
        )
