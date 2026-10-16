"""地图编辑器：障碍物创建/删除/移动/缩放 + 基地拖动 + 单位拖拽。

所有坐标均为战场逻辑坐标（800×600）。"""

from __future__ import annotations

from dataclasses import dataclass

from config import (
    _BASE_HIT_RADIUS,
    DRAG_THRESHOLD,
    MIN_BASE_DISTANCE,
    MIN_OBSTACLE_SIZE,
    MIN_UNIT_DISTANCE,
    RESIZE_HANDLE,
)
from core.battlefield import (
    Battlefield,
    OBSTACLE_DISPLAY_NAMES,
    Obstacle,
    obstacle_display_name,
)
from core.units import Unit, UnitDomain


@dataclass
class EditorState:
    """编辑交互状态（全部为战场逻辑坐标）。"""
    # 障碍物拖拽创建
    creating: bool = False
    create_start_x: float = 0.0
    create_start_y: float = 0.0
    create_current_x: float = 0.0
    create_current_y: float = 0.0

    # 选中 + 拖拽 + resize
    selected_obs_idx: int | None = None
    dragging_obs: bool = False
    drag_offset_x: float = 0.0
    drag_offset_y: float = 0.0
    resizing: bool = False

    # 拖拽单位
    dragging_unit_idx: int | None = None
    drag_unit_start_x: float = 0.0
    drag_unit_start_y: float = 0.0

    # 拖拽基地
    dragging_base: str | None = None  # "red" / "blue"

    # 消息
    last_message: str = ""

    @property
    def is_active(self) -> bool:
        return self.creating or self.dragging_obs or self.resizing or self.dragging_unit_idx is not None or self.dragging_base is not None


class MapEditor:
    """封装障碍物编辑、基地拖动和单位拖拽的核心逻辑。"""

    def __init__(self, battlefield: Battlefield):
        self.battlefield = battlefield
        self.state = EditorState()
        self._base_start_x: float = 0.0
        self._base_start_y: float = 0.0
        self._deploy_units: list[Unit] = []
        self._obs_snapshot: Obstacle | None = None  # 拖拽/缩放前保存原始状态

    # ═══════════════════════════════════════════════════════════
    #  命中检测
    # ═══════════════════════════════════════════════════════════

    def hit_obstacle(self, x: float, y: float) -> int | None:
        """返回命中的障碍物索引（最上层优先），未命中返回 None。"""
        for i in range(len(self.battlefield.obstacles) - 1, -1, -1):
            if self.battlefield.obstacles[i].contains(x, y):
                return i
        return None

    def hit_unit(self, x: float, y: float, units: list[Unit]) -> int | None:
        """返回命中的非摧毁单位索引，未命中返回 None。"""
        for i, unit in enumerate(units):
            if unit.is_destroyed:
                continue
            dist = ((x - unit.x) ** 2 + (y - unit.y) ** 2) ** 0.5
            if dist <= MIN_UNIT_DISTANCE:
                return i
        return None

    def hit_base(self, x: float, y: float) -> str | None:
        """返回命中的基地 team，未命中返回 None。"""
        rx, ry = self.battlefield.red_base
        if (x - rx) ** 2 + (y - ry) ** 2 < _BASE_HIT_RADIUS ** 2:
            return "red"
        bx, by = self.battlefield.blue_base
        if (x - bx) ** 2 + (y - by) ** 2 < _BASE_HIT_RADIUS ** 2:
            return "blue"
        return None

    def hit_resize_handle(self, x: float, y: float) -> bool:
        """检测是否命中当前选中障碍物的右下角缩放把手。"""
        idx = self.state.selected_obs_idx
        if idx is None or idx >= len(self.battlefield.obstacles):
            return False
        obs = self.battlefield.obstacles[idx]
        hx, hy = obs.x + obs.width, obs.y + obs.height
        return (hx - RESIZE_HANDLE <= x <= hx) and (hy - RESIZE_HANDLE <= y <= hy)

    # ═══════════════════════════════════════════════════════════
    #  重叠检测
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _rects_overlap(r1: tuple[float, float, float, float],
                       r2: tuple[float, float, float, float]) -> bool:
        x1, y1, w1, h1 = r1
        x2, y2, w2, h2 = r2
        return not (x1 + w1 <= x2 or x2 + w2 <= x1 or y1 + h1 <= y2 or y2 + h2 <= y1)

    def check_obstacle_overlap(self, rect: tuple[float, float, float, float],
                                exclude_idx: int | None = None) -> bool:
        """新障碍物矩形是否与已有障碍物重叠（可排除自身）。"""
        for i, obs in enumerate(self.battlefield.obstacles):
            if i == exclude_idx:
                continue
            if self._rects_overlap(rect, (obs.x, obs.y, obs.width, obs.height)):
                return True
        return False

    def check_unit_overlap(self, x: float, y: float, units: list[Unit],
                           exclude_idx: int | None = None) -> bool:
        """新单位位置是否与已有单位重叠（可排除自身）。"""
        for i, unit in enumerate(units):
            if i == exclude_idx:
                continue
            if unit.is_destroyed:
                continue
            dist = ((x - unit.x) ** 2 + (y - unit.y) ** 2) ** 0.5
            if dist < MIN_UNIT_DISTANCE:
                return True
        return False

    def check_unit_in_obstacle(self, x: float, y: float, domain: str) -> bool:
        """地面/指挥单位是否落入障碍物范围内。"""
        if domain == UnitDomain.AIR:
            return False
        return self.battlefield.is_blocked(x, y)

    def check_in_any_obstacle(self, x: float, y: float) -> bool:
        """任意坐标是否落入障碍物内（用于基地/单位通用检测）。"""
        return self.battlefield.is_blocked(x, y)

    def check_unit_near_base(self, x: float, y: float) -> bool:
        """单位位置是否与红/蓝基地过近。"""
        for bx, by in (self.battlefield.red_base, self.battlefield.blue_base):
            if ((x - bx) ** 2 + (y - by) ** 2) ** 0.5 < MIN_BASE_DISTANCE:
                return True
        return False

    def check_base_overlap(self, x: float, y: float, moving_team: str) -> bool:
        """移动中的基地是否与另一基地过近。"""
        other = self.battlefield.blue_base if moving_team == "red" else self.battlefield.red_base
        return ((x - other[0]) ** 2 + (y - other[1]) ** 2) ** 0.5 < MIN_BASE_DISTANCE

    def check_obstacle_covers_base(self, rect: tuple[float, float, float, float]) -> bool:
        """障碍物矩形是否覆盖了红/蓝基地坐标。"""
        rx, ry, rw, rh = rect
        for bx, by in (self.battlefield.red_base, self.battlefield.blue_base):
            if rx <= bx <= rx + rw and ry <= by <= ry + rh:
                return True
        return False

    def check_units_in_rect(self, rect: tuple[float, float, float, float],
                            units: list[Unit]) -> bool:
        """是否有地面/指挥单位落在障碍物矩形区域内（空中单位不受影响）。"""
        rx, ry, rw, rh = rect
        for unit in units:
            if unit.is_destroyed:
                continue
            if unit.domain == UnitDomain.AIR:
                continue
            if rx <= unit.x <= rx + rw and ry <= unit.y <= ry + rh:
                return True
        return False

    def check_position_valid(self, x: float, y: float, domain: str) -> bool:
        """检查位置是否合法（边界 + 平台规则）。"""
        return self.battlefield.is_position_valid(x, y, domain)

    # ═══════════════════════════════════════════════════════════
    #  障碍物创建
    # ═══════════════════════════════════════════════════════════

    def start_create_obstacle(self, x: float, y: float) -> bool:
        if not self.battlefield.in_bounds(x, y):
            self.state.last_message = "不能在地图外创建障碍物"
            return False
        self.state.creating = True
        self.state.create_start_x = x
        self.state.create_start_y = y
        self.state.create_current_x = x
        self.state.create_current_y = y
        self.state.selected_obs_idx = None
        self.state.last_message = "正在创建障碍物..."
        return True

    def update_create_obstacle(self, x: float, y: float) -> None:
        self.state.create_current_x = x
        self.state.create_current_y = y

    def finish_create_obstacle(self, x: float, y: float, obs_type: str = "building") -> int | None:
        """完成障碍物创建，返回新障碍物的索引（失败返回 None）。"""
        if not self.state.creating:
            return None
        self.state.creating = False
        x1, y1 = self.state.create_start_x, self.state.create_start_y
        x2 = max(0, min(self.battlefield.width, x))
        y2 = max(0, min(self.battlefield.height, y))
        rx, ry = min(x1, x2), min(y1, y2)
        rw, rh = abs(x2 - x1), abs(y2 - y1)
        if rw < MIN_OBSTACLE_SIZE or rh < MIN_OBSTACLE_SIZE:
            self.state.last_message = "障碍物尺寸过小，已忽略"
            return None
        if self.check_obstacle_overlap((rx, ry, rw, rh)):
            self.state.last_message = "放置失败：障碍物重叠"
            return None
        if self.check_obstacle_covers_base((rx, ry, rw, rh)):
            self.state.last_message = "放置失败：障碍物不能覆盖基地"
            return None
        if self.check_units_in_rect((rx, ry, rw, rh), self._deploy_units):
            self.state.last_message = "放置失败：障碍物区域内有单位"
            return None
        idx = len(self.battlefield.obstacles)
        name = OBSTACLE_DISPLAY_NAMES.get(obs_type, "障碍物")
        obs = Obstacle(x=rx, y=ry, width=rw, height=rh, name=name, type=obs_type)
        self.battlefield.obstacles.append(obs)
        self.state.selected_obs_idx = idx
        self.state.last_message = f"已创建 {obs.name}"
        return idx

    @property
    def preview_rect(self) -> tuple[float, float, float, float] | None:
        if not self.state.creating:
            return None
        x1, y1 = self.state.create_start_x, self.state.create_start_y
        x2, y2 = self.state.create_current_x, self.state.create_current_y
        rx, ry = min(x1, x2), min(y1, y2)
        return rx, ry, abs(x2 - x1), abs(y2 - y1)

    # ═══════════════════════════════════════════════════════════
    #  障碍物拖拽移动
    # ═══════════════════════════════════════════════════════════

    def start_drag_obstacle(self, idx: int, x: float, y: float) -> None:
        obs = self.battlefield.obstacles[idx]
        self._obs_snapshot = Obstacle(
            x=obs.x, y=obs.y, width=obs.width, height=obs.height,
            name=obs.name, type=obs.type,
        )
        self.state.selected_obs_idx = idx
        self.state.dragging_obs = True
        self.state.drag_offset_x = x - obs.x
        self.state.drag_offset_y = y - obs.y
        self.state.last_message = f"已选中 {obstacle_display_name(obs)}"

    def update_drag_obstacle(self, x: float, y: float) -> None:
        idx = self.state.selected_obs_idx
        if idx is None or not self.state.dragging_obs:
            return
        obs = self.battlefield.obstacles[idx]
        nx = x - self.state.drag_offset_x
        ny = y - self.state.drag_offset_y
        nx = max(0, min(self.battlefield.width - obs.width, nx))
        ny = max(0, min(self.battlefield.height - obs.height, ny))
        self.battlefield.obstacles[idx] = Obstacle(
            x=nx, y=ny, width=obs.width, height=obs.height,
            name=obs.name, type=obs.type,
        )

    def finish_drag_obstacle(self) -> bool:
        """确认移动，检查重叠。失败时回退到原始位置。"""
        idx = self.state.selected_obs_idx
        was_dragging = self.state.dragging_obs
        self.state.dragging_obs = False
        if idx is None:
            return True
        obs = self.battlefield.obstacles[idx]
        fail_msg = ""
        if self.check_obstacle_overlap((obs.x, obs.y, obs.width, obs.height), idx):
            fail_msg = "移动失败：障碍物重叠"
        elif self.check_obstacle_covers_base((obs.x, obs.y, obs.width, obs.height)):
            fail_msg = "移动失败：障碍物不能覆盖基地"
        elif self.check_units_in_rect((obs.x, obs.y, obs.width, obs.height), self._deploy_units):
            fail_msg = "移动失败：障碍物区域内有地面/指挥单位"
        if fail_msg:
            if self._obs_snapshot:
                self.battlefield.obstacles[idx] = self._obs_snapshot
                self._obs_snapshot = None
            self.state.last_message = fail_msg
            return False
        self._obs_snapshot = None
        if was_dragging:
            self.state.last_message = f"{obstacle_display_name(obs)} 已移动"
        return True

    # ═══════════════════════════════════════════════════════════
    #  障碍物 resize
    # ═══════════════════════════════════════════════════════════

    def start_resize(self) -> None:
        idx = self.state.selected_obs_idx
        if idx is None:
            return
        obs = self.battlefield.obstacles[idx]
        self._obs_snapshot = Obstacle(
            x=obs.x, y=obs.y, width=obs.width, height=obs.height,
            name=obs.name, type=obs.type,
        )
        self.state.resizing = True
        self.state.dragging_obs = False

    def update_resize(self, x: float, y: float) -> None:
        idx = self.state.selected_obs_idx
        if idx is None or not self.state.resizing:
            return
        obs = self.battlefield.obstacles[idx]
        nw = max(MIN_OBSTACLE_SIZE, x - obs.x)
        nh = max(MIN_OBSTACLE_SIZE, y - obs.y)
        nw = min(nw, self.battlefield.width - obs.x)
        nh = min(nh, self.battlefield.height - obs.y)
        self.battlefield.obstacles[idx] = Obstacle(
            x=obs.x, y=obs.y, width=nw, height=nh,
            name=obs.name, type=obs.type,
        )

    def finish_resize(self) -> bool:
        self.state.resizing = False
        idx = self.state.selected_obs_idx
        if idx is None:
            return True
        obs = self.battlefield.obstacles[idx]
        fail_msg = ""
        if self.check_obstacle_overlap((obs.x, obs.y, obs.width, obs.height), idx):
            fail_msg = "调整失败：障碍物重叠"
        elif self.check_obstacle_covers_base((obs.x, obs.y, obs.width, obs.height)):
            fail_msg = "调整失败：障碍物不能覆盖基地"
        elif self.check_units_in_rect((obs.x, obs.y, obs.width, obs.height), self._deploy_units):
            fail_msg = "调整失败：障碍物区域内有地面/指挥单位"
        if fail_msg:
            if self._obs_snapshot:
                self.battlefield.obstacles[idx] = self._obs_snapshot
                self._obs_snapshot = None
            self.state.last_message = fail_msg
            return False
        self._obs_snapshot = None
        self.state.last_message = f"{obstacle_display_name(obs)} 大小已调整"
        return True

    # ═══════════════════════════════════════════════════════════
    #  障碍物删除
    # ═══════════════════════════════════════════════════════════

    def delete_obstacle(self, idx: int) -> bool:
        if idx < 0 or idx >= len(self.battlefield.obstacles):
            return False
        obs = self.battlefield.obstacles.pop(idx)
        if self.state.selected_obs_idx == idx:
            self.state.selected_obs_idx = None
        elif self.state.selected_obs_idx is not None and self.state.selected_obs_idx > idx:
            self.state.selected_obs_idx -= 1
        self.state.last_message = f"已删除 {obstacle_display_name(obs)}"
        return True

    def delete_selected(self) -> bool:
        if self.state.selected_obs_idx is None:
            self.state.last_message = "没有选中的障碍物"
            return False
        return self.delete_obstacle(self.state.selected_obs_idx)

    # ═══════════════════════════════════════════════════════════
    #  单位拖拽
    # ═══════════════════════════════════════════════════════════

    def start_drag_unit(self, idx: int, units: list[Unit]) -> None:
        unit = units[idx]
        self.state.dragging_unit_idx = idx
        self.state.drag_unit_start_x = unit.x
        self.state.drag_unit_start_y = unit.y
        self.state.last_message = f"正在移动 {unit.name}"

    def update_drag_unit(self, x: float, y: float, units: list[Unit]) -> None:
        idx = self.state.dragging_unit_idx
        if idx is None:
            return
        unit = units[idx]
        unit.x = max(0, min(self.battlefield.width, x))
        unit.y = max(0, min(self.battlefield.height, y))

    def finish_drag_unit(self, domain: str, units: list[Unit],
                         exclude_idx: int | None = None) -> bool:
        """确认拖拽，检查位置合法性。返回 True 表示成功。"""
        idx = self.state.dragging_unit_idx
        self.state.dragging_unit_idx = None
        if idx is None:
            return True
        unit = units[idx]
        actual_idx = idx if exclude_idx is None else exclude_idx
        if not self.battlefield.in_bounds(unit.x, unit.y):
            unit.x = self.state.drag_unit_start_x
            unit.y = self.state.drag_unit_start_y
            self.state.last_message = "移动失败：不能移出地图"
            return False
        if self.check_unit_in_obstacle(unit.x, unit.y, domain):
            unit.x = self.state.drag_unit_start_x
            unit.y = self.state.drag_unit_start_y
            self.state.last_message = "移动失败：该兵种不能进入障碍物"
            return False
        if self.check_unit_overlap(unit.x, unit.y, units, actual_idx):
            unit.x = self.state.drag_unit_start_x
            unit.y = self.state.drag_unit_start_y
            self.state.last_message = "移动失败：与已有单位重叠"
            return False
        if self.check_unit_near_base(unit.x, unit.y):
            unit.x = self.state.drag_unit_start_x
            unit.y = self.state.drag_unit_start_y
            self.state.last_message = "移动失败：与基地过近"
            return False
        self.state.last_message = f"{unit.name} 已移动"
        return True

    # ═══════════════════════════════════════════════════════════
    #  基地拖拽
    # ═══════════════════════════════════════════════════════════

    def start_drag_base(self, team: str) -> None:
        self.state.dragging_base = team
        self._base_start_x, self._base_start_y = (
            self.battlefield.red_base if team == "red" else self.battlefield.blue_base)
        label = "红方" if team == "red" else "蓝方"
        self.state.last_message = f"正在移动{label}基地..."

    def update_drag_base(self, x: float, y: float) -> None:
        if not self.state.dragging_base:
            return
        cx = max(0, min(self.battlefield.width, x))
        cy = max(0, min(self.battlefield.height, y))
        if self.state.dragging_base == "red":
            self.battlefield.red_base = (cx, cy)
        else:
            self.battlefield.blue_base = (cx, cy)

    def finish_drag_base(self) -> bool:
        """确认基地位置，检查合法性。返回 True 表示成功。"""
        team = self.state.dragging_base
        if not team:
            return True
        self.state.dragging_base = None
        bx, by = self.battlefield.red_base if team == "red" else self.battlefield.blue_base
        if self.check_in_any_obstacle(bx, by):
            self._restore_base(team)
            self.state.last_message = "移动失败：基地不能放在障碍物上"
            return False
        if self.check_base_overlap(bx, by, team):
            self._restore_base(team)
            self.state.last_message = "移动失败：基地间距过近"
            return False
        label = "红方" if team == "red" else "蓝方"
        self.state.last_message = f"{label}基地已移动"
        return True

    def _restore_base(self, team: str) -> None:
        if team == "red":
            self.battlefield.red_base = (self._base_start_x, self._base_start_y)
        else:
            self.battlefield.blue_base = (self._base_start_x, self._base_start_y)

    # 需要在 EditorState 或 MapEditor 中新增 _base_start_x, _base_start_y

    # ═══════════════════════════════════════════════════════════
    #  杂项
    # ═══════════════════════════════════════════════════════════

    def clear_selection(self) -> None:
        self.state.selected_obs_idx = None

    def cancel(self) -> None:
        self.state = EditorState()

    def cancel_interaction(self) -> None:
        """放弃进行中的创建/拖拽/缩放，不提交任何修改。

        用于左键拖动平移等需要中断编辑手势的场景：障碍物按 _obs_snapshot
        回退，单位/基地回到拖拽起点，同时清空全局提示以免留下过期文案。
        """
        state = self.state
        if state.dragging_obs or state.resizing:
            idx = state.selected_obs_idx
            if (self._obs_snapshot is not None and idx is not None
                    and 0 <= idx < len(self.battlefield.obstacles)):
                self.battlefield.obstacles[idx] = self._obs_snapshot
            self._obs_snapshot = None
        if state.dragging_unit_idx is not None:
            idx = state.dragging_unit_idx
            if 0 <= idx < len(self._deploy_units):
                unit = self._deploy_units[idx]
                unit.x = state.drag_unit_start_x
                unit.y = state.drag_unit_start_y
        if state.dragging_base:
            self._restore_base(state.dragging_base)

        state.creating = False
        state.dragging_obs = False
        state.resizing = False
        state.dragging_unit_idx = None
        state.dragging_base = None
        state.last_message = ""

    @property
    def message(self) -> str:
        return self.state.last_message
