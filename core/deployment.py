"""部署阶段管理器。

统一部署阶段：加载预设地图后可直接编辑（增删单位、创建/移动障碍物、
拖动基地），C 清空地图，R 恢复预设，Ctrl+S 保存，L 加载。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import (
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
    "1": "scout_drone", "2": "strike_drone", "3": "ground_vehicle",
    "4": "missile_vehicle", "5": "command_node",
}

OBSTACLE_KEYS = {
    "6": "mountain", "7": "building", "8": "restricted",
}

KEY_ESCAPE = 27
KEY_RETURN = 13
KEY_BACKSPACE = 8
KEY_DELETE = 127
KEY_1 = 49; KEY_2 = 50; KEY_3 = 51; KEY_4 = 52; KEY_5 = 53
KEY_6 = 54; KEY_7 = 55; KEY_8 = 56
KEY_C = 99; KEY_M = 109; KEY_R = 114; KEY_T = 116

UNIT_KEY_CODES = {
    KEY_1: "scout_drone", KEY_2: "strike_drone", KEY_3: "ground_vehicle",
    KEY_4: "missile_vehicle", KEY_5: "command_node",
}

OBSTACLE_KEY_CODES = {
    KEY_6: "mountain", KEY_7: "building", KEY_8: "restricted",
}


@dataclass
class DeploymentResult:
    ok: bool
    units: list[Unit]
    message: str = ""


class DeploymentManager:
    """统一的部署阶段管理（预设即初始状态，可直接编辑）。"""

    def __init__(self, battlefield: Battlefield, preset_units: list[Unit]):
        self.battlefield = battlefield
        self._original_units = [self._clone_unit(u) for u in preset_units]
        self._original_obstacles = [
            Obstacle(o.x, o.y, o.width, o.height, o.name, o.type)
            for o in battlefield.obstacles
        ]
        self._original_red_base = battlefield.red_base
        self._original_blue_base = battlefield.blue_base
        self.deploy_units: list[Unit] = [self._clone_unit(u) for u in preset_units]
        self.selected_team = TEAM_RED
        self.selected_unit_type: str | None = "scout_drone"
        self.selected_obstacle_type: str | None = None
        self.last_message = "部署阶段：按 Enter 开始仿真，可直接编辑单位和障碍物"
        self._sequence = len(preset_units) + 1
        self._editor = MapEditor(battlefield)

        self._mouse_down = False
        self._drag_start_x: float = 0.0
        self._drag_start_y: float = 0.0
        self._hit_type: str = ""
        self._hit_index: int | None = None

    # ═══════════════════════════════════════════════════════════
    #  键盘
    # ═══════════════════════════════════════════════════════════

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
        if key == KEY_T or normalized_text == "t":
            self.toggle_team()
        elif key == KEY_BACKSPACE:
            self.undo_last_unit()
        elif key == KEY_DELETE:
            if self._editor.state.selected_obs_idx is not None:
                self._editor.delete_selected()
        elif key == KEY_C or normalized_text == "c":
            self.clear_map()
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
    #  地图操作
    # ═══════════════════════════════════════════════════════════

    def clear_map(self) -> None:
        """清空所有单位和障碍物（保留基地）。"""
        self.deploy_units.clear()
        self.battlefield.obstacles.clear()
        self._sequence = 1
        self._editor.clear_selection()
        self.last_message = "地图已清空，可以开始手动部署"

    def reset_to_preset(self, new_units: list[Unit] | None = None) -> None:
        """恢复为原始预设状态。"""
        if new_units is not None:
            self._original_units = [self._clone_unit(u) for u in new_units]
            self._original_obstacles = [
                Obstacle(o.x, o.y, o.width, o.height, o.name, o.type)
                for o in self.battlefield.obstacles
            ]
            self._original_red_base = self.battlefield.red_base
            self._original_blue_base = self.battlefield.blue_base
        self.deploy_units = [self._clone_unit(u) for u in self._original_units]
        self.battlefield.obstacles[:] = [
            Obstacle(o.x, o.y, o.width, o.height, o.name, o.type)
            for o in self._original_obstacles
        ]
        self.battlefield.red_base = self._original_red_base
        self.battlefield.blue_base = self._original_blue_base
        self.selected_unit_type = "scout_drone"
        self.selected_obstacle_type = None
        self._sequence = len(self._original_units) + 1
        self._editor.clear_selection()
        self._mouse_down = False
        self._hit_type = ""
        self._hit_index = None
        self.last_message = "已恢复预设开局"

    def undo_last_unit(self) -> None:
        """撤销最近部署的单位。"""
        if not self.deploy_units:
            self.last_message = "没有可撤销的单位"
            return
        removed = self.deploy_units.pop()
        if self._sequence > 1:
            self._sequence -= 1
        self.last_message = f"已撤销 {removed.name}"

    # ═══════════════════════════════════════════════════════════
    #  鼠标
    # ═══════════════════════════════════════════════════════════

    def handle_mouse_down(self, button: int, bf_x: float, bf_y: float) -> None:
        if button == 3:
            self._handle_right_click(bf_x, bf_y)
            return
        if button != 1:
            return
        if not self.battlefield.in_bounds(bf_x, bf_y):
            return

        self._mouse_down = True
        self._drag_start_x = bf_x
        self._drag_start_y = bf_y

        obs_idx = self._editor.hit_obstacle(bf_x, bf_y)
        # resize 把手
        if obs_idx is not None and self._editor.state.selected_obs_idx == obs_idx:
            if self._editor.hit_resize_handle(bf_x, bf_y):
                self._hit_type = "resize"
                self._hit_index = obs_idx
                self._editor.start_resize()
                return
        # 障碍物
        if obs_idx is not None:
            self._hit_type = "obstacle"
            self._hit_index = obs_idx
            self._editor.start_drag_obstacle(obs_idx, bf_x, bf_y)
            return
        # 单位
        unit_idx = self._editor.hit_unit(bf_x, bf_y, self.deploy_units)
        if unit_idx is not None:
            self._hit_type = "unit"
            self._hit_index = unit_idx
            self._editor.start_drag_unit(unit_idx, self.deploy_units)
            return
        # 基地
        base = self._editor.hit_base(bf_x, bf_y)
        if base is not None:
            self._hit_type = "base"
            self._editor.start_drag_base(base)
            return
        # 空位
        self._hit_type = "empty"
        self._editor.clear_selection()
        if self.selected_obstacle_type:
            self._editor.start_create_obstacle(bf_x, bf_y)

    def handle_mouse_motion(self, bf_x: float, bf_y: float) -> None:
        if not self._mouse_down:
            return
        if self._hit_type == "resize":
            self._editor.update_resize(bf_x, bf_y)
        elif self._hit_type == "obstacle":
            self._editor.update_drag_obstacle(bf_x, bf_y)
            self.last_message = "正在移动障碍物..."
        elif self._hit_type == "unit":
            self._editor.update_drag_unit(bf_x, bf_y, self.deploy_units)
        elif self._hit_type == "base":
            self._editor.update_drag_base(bf_x, bf_y)
        elif self._hit_type == "empty" and self.selected_obstacle_type:
            self._editor.update_create_obstacle(bf_x, bf_y)

    def handle_mouse_up(self, button: int, bf_x: float, bf_y: float) -> None:
        if button != 1 or not self._mouse_down:
            return
        self._mouse_down = False
        self._editor._deploy_units = self.deploy_units
        dist = ((bf_x - self._drag_start_x) ** 2 + (bf_y - self._drag_start_y) ** 2) ** 0.5

        if self._hit_type == "resize":
            self._editor.finish_resize()
        elif self._hit_type == "obstacle":
            self._editor.finish_drag_obstacle()
        elif self._hit_type == "unit":
            unit_idx = self._hit_index
            unit = self.deploy_units[unit_idx] if unit_idx is not None and unit_idx < len(self.deploy_units) else None
            domain = unit.domain if unit else "ground"
            self._editor.finish_drag_unit(domain, self.deploy_units, unit_idx)
        elif self._hit_type == "base":
            self._editor.finish_drag_base()
        elif self._hit_type == "empty":
            if self.selected_obstacle_type and self._editor.state.creating:
                self._editor.finish_create_obstacle(bf_x, bf_y, self.selected_obstacle_type)
            elif self.selected_unit_type and dist < DRAG_THRESHOLD:
                self._place_unit_at(bf_x, bf_y)

        self._hit_type = ""
        self._hit_index = None

    @property
    def editor_active(self) -> bool:
        """是否有进行中的编辑手势（拉框创建、拖拽对象、缩放障碍）。"""
        return self._editor.state.is_active

    def handle_mouse_cancel(self) -> None:
        """放弃本次左键编辑（不放置单位、不创建或移动对象）。"""
        if not self._mouse_down:
            return
        self._mouse_down = False
        self._editor._deploy_units = self.deploy_units
        if self._editor.state.is_active:
            # 编辑手势已中断，“正在创建/移动...”之类的提示不再成立
            self.last_message = ""
        self._editor.cancel_interaction()
        self._hit_type = ""
        self._hit_index = None

    def _handle_right_click(self, bf_x: float, bf_y: float) -> None:
        if not self.battlefield.in_bounds(bf_x, bf_y):
            return
        obs_idx = self._editor.hit_obstacle(bf_x, bf_y)
        if obs_idx is not None:
            self._editor.delete_obstacle(obs_idx)
            return
        unit_idx = self._editor.hit_unit(bf_x, bf_y, self.deploy_units)
        if unit_idx is not None:
            unit = self.deploy_units[unit_idx]
            self.deploy_units.remove(unit)
            if self._sequence > 1:
                self._sequence -= 1
            self.last_message = f"已删除 {unit.name}"

    # ═══════════════════════════════════════════════════════════
    #  单位放置
    # ═══════════════════════════════════════════════════════════

    def _place_unit_at(self, x: float, y: float) -> bool:
        if not self.selected_unit_type:
            return False
        domain = UnitFactory.get_domain(self.selected_unit_type)
        if not self.battlefield.in_bounds(x, y):
            self.last_message = "放置失败：不能部署在地图外"
            return False
        if self._editor.check_in_any_obstacle(x, y):
            self.last_message = "放置失败：不能放在障碍物上"
            return False
        if self._editor.check_unit_overlap(x, y, self.deploy_units):
            self.last_message = "放置失败：与已有单位重叠"
            return False
        if self._editor.check_unit_near_base(x, y):
            self.last_message = "放置失败：与基地过近"
            return False
        unit = self._build_unit(x, y)
        self.deploy_units.append(unit)
        self._sequence += 1
        self.last_message = f"已部署 {unit.name}"
        return True

    # ═══════════════════════════════════════════════════════════

    def display_units(self) -> list[Unit]:
        return self.deploy_units

    def finalize(self) -> DeploymentResult:
        if not self.deploy_units:
            self.last_message = "无法开始：请至少部署红蓝双方单位"
            return DeploymentResult(False, [], self.last_message)
        teams = {u.team for u in self.deploy_units if u.is_alive()}
        if TEAM_RED not in teams or TEAM_BLUE not in teams:
            self.last_message = "无法开始：红蓝双方都需要至少一个单位"
            return DeploymentResult(False, [], self.last_message)
        self.last_message = "部署完成，开始仿真"
        return DeploymentResult(True, [self._clone_unit(u) for u in self.deploy_units], self.last_message)

    @property
    def selected_label(self) -> str:
        if self.selected_unit_type:
            return UNIT_LABELS[self.selected_unit_type]
        if self.selected_obstacle_type:
            return OBSTACLE_TYPE_LABELS[self.selected_obstacle_type]
        return "无"

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

    @staticmethod
    def _clone_unit(unit: Unit) -> Unit:
        return UnitFactory.create({
            "id": unit.id, "name": unit.name, "team": unit.team,
            "unit_type": unit.unit_type, "x": unit.x, "y": unit.y,
            "hp": unit.hp, "max_hp": unit.max_hp, "speed": unit.speed,
            "detect_range": unit.detect_range, "attack_range": unit.attack_range,
            "attack_power": unit.attack_power, "ammo": unit.ammo,
            "status": STATUS_MOVE, "target_id": None,
            "can_attack_air": unit.can_attack_air,
            "can_attack_ground": unit.can_attack_ground,
        })
