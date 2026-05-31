"""部署阶段管理器。

DeploymentManager 负责预设/手动部署，在手动模式下统一管理
单位放置、障碍物创建/移动/缩放、基地拖动和删除。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import (
    DEPLOY_MANUAL,
    DEPLOY_PRESET,
    DRAG_THRESHOLD,
    OBSTACLE_TYPE_LABELS,
    STATUS_MOVE,
    TEAM_BLUE,
    TEAM_RED,
    UNIT_TYPE_LABELS,
)
from core.battlefield import Battlefield, Obstacle
from core.obstacle_editor import MapEditor
from core.unit_factory import UnitFactory
from core.units import Unit, UnitDomain


UNIT_LABELS = UNIT_TYPE_LABELS

UNIT_KEYS = {
    "1": "scout_drone",
    "2": "strike_drone",
    "3": "ground_vehicle",
    "4": "missile_vehicle",
    "5": "command_node",
}

OBSTACLE_KEYS = {
    "6": "mountain",
    "7": "building",
    "8": "restricted",
}

# 键盘码常量
KEY_ESCAPE = 27
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_DELETE = 127
KEY_1 = 49
KEY_2 = 50
KEY_3 = 51
KEY_4 = 52
KEY_5 = 53
KEY_6 = 54
KEY_7 = 55
KEY_8 = 56
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

OBSTACLE_KEY_CODES = {
    KEY_6: "mountain",
    KEY_7: "building",
    KEY_8: "restricted",
}


@dataclass
class DeploymentResult:
    ok: bool
    units: list[Unit]
    message: str = ""


class DeploymentManager:
    """管理部署模式、当前选择、手动部署单位和地图编辑。"""

    def __init__(self, battlefield: Battlefield, preset_units: list[Unit]):
        self.battlefield = battlefield
        self.preset_units = preset_units
        self._preset_obstacles = list(battlefield.obstacles)
        self._preset_red_base = battlefield.red_base
        self._preset_blue_base = battlefield.blue_base
        self.mode = DEPLOY_PRESET
        self.selected_team = TEAM_RED
        self.selected_unit_type: str | None = "scout_drone"
        self.selected_obstacle_type: str | None = None
        self.manual_units: list[Unit] = []
        self.last_message = "部署阶段：按 Enter 使用预设开局开始仿真"
        self._sequence = 1
        self._editor = MapEditor(battlefield)

        # 鼠标交互状态
        self._mouse_down = False
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0
        self._hit_type: str = ""          # "empty" / "unit" / "obstacle" / "base" / "resize"
        self._hit_index: int | None = None

    # ═══════════════════════════════════════════════════════════
    #  键盘处理
    # ═══════════════════════════════════════════════════════════

    def toggle_mode(self) -> None:
        self.mode = DEPLOY_MANUAL if self.mode == DEPLOY_PRESET else DEPLOY_PRESET
        self.selected_unit_type = "scout_drone"
        self.selected_obstacle_type = None
        self._editor.clear_selection()
        if self.mode == DEPLOY_MANUAL:
            self.battlefield.obstacles.clear()
            self.manual_units.clear()
            self._sequence = 1
        else:
            self.battlefield.obstacles[:] = [Obstacle(
                x=o.x, y=o.y, width=o.width, height=o.height,
                name=o.name, type=o.type,
            ) for o in self._preset_obstacles]
            self.battlefield.red_base = self._preset_red_base
            self.battlefield.blue_base = self._preset_blue_base
        self.last_message = f"已切换到{'手动部署' if self.mode == DEPLOY_MANUAL else '预设部署'} 模式"

    def toggle_team(self) -> None:
        self.selected_team = TEAM_BLUE if self.selected_team == TEAM_RED else TEAM_RED
        team_label = "红方" if self.selected_team == TEAM_RED else "蓝方"
        self.last_message = f"当前部署阵营：{team_label}"

    def _select_unit_type(self, unit_type: str) -> None:
        if unit_type not in UNIT_LABELS:
            return
        self.selected_unit_type = unit_type
        self.selected_obstacle_type = None
        self._editor.clear_selection()
        self.last_message = f"当前选择：{UNIT_LABELS[unit_type]}（左键点击放置）"

    def _select_obstacle_type(self, obs_type: str) -> None:
        if obs_type not in OBSTACLE_TYPE_LABELS:
            return
        self.selected_obstacle_type = obs_type
        self.selected_unit_type = None
        self._editor.clear_selection()
        label = OBSTACLE_TYPE_LABELS[obs_type]
        self.last_message = f"当前选择：{label}（左键拖拽创建）"

    def handle_key(self, key: int, normalized_text: str = "") -> str | None:
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
            if self._editor.state.selected_obs_idx is not None:
                self._editor.delete_selected()
            else:
                self.undo()
        elif key == KEY_DELETE:
            if self._editor.state.selected_obs_idx is not None:
                self._editor.delete_selected()
        elif key == KEY_C or normalized_text == "c":
            self.clear_manual()
            self._editor.clear_selection()
        elif key == KEY_R or normalized_text == "r":
            self.reset_to_preset()
            return "reset"
        elif key in UNIT_KEY_CODES:
            self._select_unit_type(UNIT_KEY_CODES[key])
        elif key in OBSTACLE_KEY_CODES:
            self._select_obstacle_type(OBSTACLE_KEY_CODES[key])
        elif normalized_text in UNIT_KEYS:
            self._select_unit_type(UNIT_KEYS[normalized_text])
        elif normalized_text in OBSTACLE_KEYS:
            self._select_obstacle_type(OBSTACLE_KEYS[normalized_text])
        else:
            self.last_message = f"未识别的按键：{normalized_text or key}"
        return None

    # ═══════════════════════════════════════════════════════════
    #  鼠标处理（在渲染器中完成坐标转换后传入战场逻辑坐标）
    # ═══════════════════════════════════════════════════════════

    def handle_mouse_down(self, button: int, bf_x: float, bf_y: float) -> None:
        """处理鼠标按下事件（战场逻辑坐标）。"""
        if button == 3:  # 右键：删除
            self._handle_right_click(bf_x, bf_y)
            return

        if button != 1:
            return

        if self.mode != DEPLOY_MANUAL:
            self.last_message = "当前为预设部署模式，按 M 切换到手动部署后编辑"
            return

        if not self.battlefield.in_bounds(bf_x, bf_y):
            return

        self._mouse_down = True
        self._drag_start_x = bf_x
        self._drag_start_y = bf_y

        # 优先级: resize 把手 > 障碍物 > 单位 > 基地 > 空位
        # 1. resize 把手（已选中的障碍物右下角）
        obs_idx = self._editor.hit_obstacle(bf_x, bf_y)
        if obs_idx is not None and self._editor.state.selected_obs_idx == obs_idx:
            if self._editor.hit_resize_handle(bf_x, bf_y):
                self._hit_type = "resize"
                self._hit_index = obs_idx
                self._editor.start_resize()
                return

        # 2. 障碍物主体
        if obs_idx is not None:
            self._hit_type = "obstacle"
            self._hit_index = obs_idx
            self._editor.start_drag_obstacle(obs_idx, bf_x, bf_y)
            return

        # 3. 单位
        units = self.display_units()
        unit_idx = self._editor.hit_unit(bf_x, bf_y, units)
        if unit_idx is not None:
            self._hit_type = "unit"
            self._hit_index = unit_idx
            self._editor.start_drag_unit(unit_idx, units)
            return

        # 4. 基地
        base = self._editor.hit_base(bf_x, bf_y)
        if base is not None:
            self._hit_type = "base"
            self._editor.start_drag_base(base)
            return

        # 5. 空位
        self._hit_type = "empty"
        self._editor.clear_selection()
        if self.selected_obstacle_type:
            self._editor.start_create_obstacle(bf_x, bf_y)

    def handle_mouse_motion(self, bf_x: float, bf_y: float) -> None:
        """处理鼠标移动事件（战场逻辑坐标）。"""
        if not self._mouse_down:
            return

        if self._hit_type == "resize":
            self._editor.update_resize(bf_x, bf_y)
        elif self._hit_type == "obstacle":
            self._editor.update_drag_obstacle(bf_x, bf_y)
            self.last_message = "正在移动障碍物..."
        elif self._hit_type == "unit":
            units = self.display_units()
            self._editor.update_drag_unit(bf_x, bf_y, units)
        elif self._hit_type == "base":
            self._editor.update_drag_base(bf_x, bf_y)
        elif self._hit_type == "empty" and self.selected_obstacle_type:
            self._editor.update_create_obstacle(bf_x, bf_y)

    def handle_mouse_up(self, button: int, bf_x: float, bf_y: float) -> None:
        """处理鼠标释放事件（战场逻辑坐标）。"""
        if button != 1 or not self._mouse_down:
            return

        self._mouse_down = False
        self._editor._deploy_units = self.display_units()
        dist = ((bf_x - self._drag_start_x) ** 2 + (bf_y - self._drag_start_y) ** 2) ** 0.5

        if self._hit_type == "resize":
            self._editor.finish_resize()
        elif self._hit_type == "obstacle":
            self._editor.finish_drag_obstacle()
        elif self._hit_type == "unit":
            unit_idx = self._hit_index
            unit = self.display_units()[unit_idx] if unit_idx is not None and unit_idx < len(self.display_units()) else None
            domain = unit.domain if unit else "ground"
            self._editor.finish_drag_unit(domain, self.display_units(), unit_idx)
        elif self._hit_type == "base":
            self._editor.finish_drag_base()
        elif self._hit_type == "empty":
            if self.selected_obstacle_type and self._editor.state.creating:
                self._editor.finish_create_obstacle(bf_x, bf_y, self.selected_obstacle_type)
            elif self.selected_unit_type and dist < DRAG_THRESHOLD:
                self._place_unit_at(bf_x, bf_y)

        self._hit_type = ""
        self._hit_index = None

    def _handle_right_click(self, bf_x: float, bf_y: float) -> None:
        """右键点击：删除命中的单位/障碍物。"""
        if self.mode != DEPLOY_MANUAL:
            return
        if not self.battlefield.in_bounds(bf_x, bf_y):
            return

        obs_idx = self._editor.hit_obstacle(bf_x, bf_y)
        if obs_idx is not None:
            self._editor.delete_obstacle(obs_idx)
            return

        units = self.display_units()
        unit_idx = self._editor.hit_unit(bf_x, bf_y, units)
        if unit_idx is not None:
            unit = units[unit_idx]
            if unit in self.manual_units:
                self.manual_units.remove(unit)
            self.last_message = f"已删除 {unit.name}"
            return

    # ═══════════════════════════════════════════════════════════
    #  单位放置
    # ═══════════════════════════════════════════════════════════

    def _place_unit_at(self, x: float, y: float) -> bool:
        """在指定位置放置单位（含重叠+障碍物+基地检测）。"""
        if not self.selected_unit_type:
            return False
        domain = UnitFactory.get_domain(self.selected_unit_type)
        units = self.display_units()

        if not self.battlefield.in_bounds(x, y):
            self.last_message = "放置失败：不能部署在地图外"
            return False
        if self._editor.check_unit_in_obstacle(x, y, domain):
            self.last_message = "放置失败：该兵种不能放入障碍物"
            return False
        if self._editor.check_unit_overlap(x, y, units):
            self.last_message = "放置失败：与已有单位重叠"
            return False
        if self._editor.check_unit_near_base(x, y):
            self.last_message = "放置失败：与基地过近"
            return False

        unit = self._build_unit(x, y)
        self.manual_units.append(unit)
        self._sequence += 1
        self.last_message = f"已部署 {unit.name}"
        return True

    # ═══════════════════════════════════════════════════════════
    #  原有部署管理方法
    # ═══════════════════════════════════════════════════════════

    def undo(self) -> bool:
        if not self.manual_units:
            self.last_message = "没有可撤销的部署"
            return False
        removed = self.manual_units.pop()
        self.last_message = f"已撤销 {removed.name}"
        return True

    def clear_manual(self) -> None:
        self.manual_units.clear()
        self.last_message = "已清空手动部署"

    def reset_to_preset(self, preset_units: list[Unit] | None = None) -> None:
        if preset_units is not None:
            self.preset_units = preset_units
        self.mode = DEPLOY_PRESET
        self.selected_unit_type = "scout_drone"
        self.selected_obstacle_type = None
        self.manual_units.clear()
        self._sequence = 1
        self._editor.clear_selection()
        self._mouse_down = False
        self._hit_type = ""
        self._hit_index = None
        self.last_message = "已恢复预设开局"

    def display_units(self) -> list[Unit]:
        return self.preset_units if self.mode == DEPLOY_PRESET else self.manual_units

    def finalize(self) -> DeploymentResult:
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
        return self.battlefield.is_position_valid(x, y, unit.domain)

    @property
    def selected_label(self) -> str:
        if self.selected_unit_type:
            return UNIT_LABELS[self.selected_unit_type]
        if self.selected_obstacle_type:
            return OBSTACLE_TYPE_LABELS[self.selected_obstacle_type]
        return "无"

    @property
    def mode_label(self) -> str:
        return "手动部署" if self.mode == DEPLOY_MANUAL else "预设部署"

    # ── 向后兼容（测试用）───────────────────────────────────

    def select_unit_type(self, unit_type: str) -> None:
        self._select_unit_type(unit_type)

    def place_unit(self, x: float, y: float) -> bool:
        """测试用：手动部署时直接放置单位。"""
        if self.mode != DEPLOY_MANUAL:
            self.last_message = "当前为预设部署模式，按 M 切换到手动部署后部署"
            return False
        return self._place_unit_at(x, y)

    def handle_mouse_button(self, button: int, pos: tuple[float, float],
                            battlefield: Battlefield | None = None) -> str | None:
        """兼容旧调用：左键放置单位。"""
        if button != 1:
            return None
        bf = battlefield or self.battlefield
        x, y = pos
        if x >= bf.width:
            self.last_message = "点击被忽略：右侧信息面板不是部署区域"
            return None
        if self.mode != DEPLOY_MANUAL:
            self.last_message = f"地图点击 ({int(x)}, {int(y)})：当前为预设部署模式，按 M 切换到手动部署后部署"
            return None
        placed = self._place_unit_at(x, y)
        if not placed and not self.last_message.startswith("地图点击"):
            self.last_message = f"地图点击 ({int(x)}, {int(y)})：{self.last_message}"
        return None

    @property
    def editor(self) -> MapEditor:
        return self._editor

    def _build_unit(self, x: float, y: float) -> Unit:
        prefix = "R" if self.selected_team == TEAM_RED else "B"
        unit_id = f"{prefix}-MAN-{self._sequence:03d}"
        unit_name = f"{'红' if self.selected_team == TEAM_RED else '蓝'}-{self.selected_label}{self._sequence}"
        return UnitFactory.create({
            "id": unit_id, "name": unit_name, "team": self.selected_team,
            "unit_type": self.selected_unit_type, "x": x, "y": y,
        })

    def _clone_unit(self, unit: Unit) -> Unit:
        return UnitFactory.create({
            "id": unit.id, "name": unit.name, "team": unit.team,
            "unit_type": unit.unit_type, "x": unit.x, "y": unit.y,
            "hp": unit.hp, "max_hp": unit.max_hp, "speed": unit.speed,
            "detect_range": unit.detect_range, "attack_range": unit.attack_range,
            "attack_power": unit.attack_power, "ammo": unit.ammo,
            "status": STATUS_MOVE, "target_id": None,
            "can_attack_air": unit.can_attack_air, "can_attack_ground": unit.can_attack_ground,
        })
