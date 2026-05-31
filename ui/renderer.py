"""Pygame 可视化渲染器。

所有战场逻辑坐标通过 to_screen() 转换为屏幕像素坐标后绘制。
"""

from __future__ import annotations

import pygame

from config import (
    ATTACK_EFFECT_COLOR,
    BACKGROUND_COLOR,
    BLUE_COLOR,
    COMMAND_SIZE,
    DETECT_BLUE,
    DETECT_RED,
    GRID_COLOR,
    HP_GREEN,
    HP_RED,
    MAP_RATIO,
    OBSTACLE_COLOR,
    RED_COLOR,
    RESIZE_HANDLE,
    STATUS_DESTROYED,
    STATUS_LABELS,
    TEXT_COLOR,
    UNIT_RADIUS,
)
from core.units import CommandNode, Unit
from ui.panel import InfoPanel


class Renderer:
    """负责地图、单位、血条、探测圈和攻击特效绘制。"""

    def __init__(self, screen: pygame.Surface,
                 bf_logical_w: int = 800, bf_logical_h: int = 600):
        self.screen = screen
        sw, sh = screen.get_size()
        self.map_w = int(sw * MAP_RATIO)
        self.map_h = sh
        self.panel_w = sw - self.map_w
        self.bf_w = bf_logical_w
        self.bf_h = bf_logical_h
        self.scale_x = self.map_w / bf_logical_w
        self.scale_y = self.map_h / bf_logical_h
        self.panel = InfoPanel(self.panel_w, self.map_w)

        base_fs = max(10, int(13 * min(self.scale_x, self.scale_y)))
        self.font = pygame.font.SysFont("Microsoft YaHei", base_fs)
        self.small_font = pygame.font.SysFont("Microsoft YaHei", max(9, base_fs - 2))

    # ── 坐标转换 ──────────────────────────────────────────────

    def to_screen(self, bx: float, by: float) -> tuple[int, int]:
        return int(bx * self.scale_x), int(by * self.scale_y)

    def to_battlefield(self, sx: float, sy: float) -> tuple[float, float]:
        return sx / self.scale_x, sy / self.scale_y

    def _ss(self, bw: float, bh: float | None = None):
        """战场逻辑尺寸 → 屏幕像素尺寸。"""
        if bh is None:
            return int(bw * self.scale_x)
        return int(bw * self.scale_x), int(bh * self.scale_y)

    # ── 运行阶段渲染 ──────────────────────────────────────────

    def render(self, simulator, game_state: str) -> None:
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_grid()
        self._draw_bases(simulator.battlefield)
        self._draw_obstacles(simulator.battlefield)
        self._draw_detection_ranges(simulator.units)
        self._draw_attack_events(simulator.attack_events)
        visible = simulator.units if simulator.show_wrecks else [
            u for u in simulator.units if not u.is_destroyed]
        self._draw_units(visible, simulator.show_wrecks)
        self.panel.draw_runtime(self.screen, simulator, game_state)

    # ── 部署阶段渲染 ──────────────────────────────────────────

    def render_deployment(self, battlefield, units: list[Unit],
                          deployment) -> None:
        """绘制部署阶段（集成障碍物编辑预览）。"""
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_grid()
        self._draw_bases(battlefield)
        self._draw_obstacles(battlefield)
        self._draw_units(units)

        editor = deployment.editor
        self._draw_selected_highlight(battlefield, editor)
        self._draw_resize_handle(battlefield, editor)
        self._draw_obstacle_preview(editor)

        self.panel.draw_deployment(self.screen, deployment, battlefield)

    # ── 内部绘制 ──────────────────────────────────────────────

    def _draw_grid(self) -> None:
        step = max(20, self._ss(40))
        for x in range(0, self.map_w + 1, step):
            pygame.draw.line(self.screen, GRID_COLOR, (x, 0), (x, self.map_h), 1)
        for y in range(0, self.map_h + 1, step):
            pygame.draw.line(self.screen, GRID_COLOR, (0, y), (self.map_w, y), 1)
        pygame.draw.rect(self.screen, (75, 83, 96), (0, 0, self.map_w, self.map_h), 2)

    def _draw_obstacles(self, battlefield) -> None:
        for obstacle in battlefield.obstacles:
            sx, sy = self.to_screen(obstacle.x, obstacle.y)
            sw, sh = self._ss(obstacle.width, obstacle.height)
            rect = pygame.Rect(sx, sy, sw, sh)
            color = self._obstacle_color(obstacle.type)
            pygame.draw.rect(self.screen, color, rect)
            pygame.draw.rect(self.screen, (125, 130, 140), rect, 2)
            label = self.small_font.render(obstacle.name, True, TEXT_COLOR)
            self.screen.blit(label, (sx + 4, sy + 2))

    def _draw_bases(self, battlefield) -> None:
        for label, pos, color in (
            ("红基地", battlefield.red_base, RED_COLOR),
            ("蓝基地", battlefield.blue_base, BLUE_COLOR),
        ):
            sx, sy = self.to_screen(*pos)
            r = self._ss(18)
            pygame.draw.circle(self.screen, color, (sx, sy), r, 2)
            r2 = self._ss(12)
            pygame.draw.line(self.screen, color, (sx - r2, sy), (sx + r2, sy), 2)
            pygame.draw.line(self.screen, color, (sx, sy - r2), (sx, sy + r2), 2)
            text = self.small_font.render(label, True, TEXT_COLOR)
            self.screen.blit(text, (sx - text.get_width() // 2, sy + r + 4))

    @staticmethod
    def _obstacle_color(obstacle_type: str) -> tuple[int, int, int]:
        if obstacle_type == "mountain":
            return (92, 105, 92)
        if obstacle_type == "building":
            return (96, 98, 112)
        if obstacle_type == "restricted":
            return (116, 82, 82)
        return OBSTACLE_COLOR

    def _draw_detection_ranges(self, units: list[Unit]) -> None:
        overlay = pygame.Surface((self.map_w, self.map_h), pygame.SRCALPHA)
        for unit in units:
            if unit.is_destroyed:
                continue
            sx, sy = self.to_screen(unit.x, unit.y)
            color = DETECT_RED if unit.team == "red" else DETECT_BLUE
            pygame.draw.circle(overlay, color, (sx, sy),
                               self._ss(unit.detect_range), 1)
        self.screen.blit(overlay, (0, 0))

    def _draw_attack_events(self, events) -> None:
        for event in events:
            alpha = max(60, min(255, event.life * 32))
            color = (*ATTACK_EFFECT_COLOR[:3], alpha)
            overlay = pygame.Surface((self.map_w, self.map_h), pygame.SRCALPHA)
            sx1, sy1 = self.to_screen(*event.start)
            sx2, sy2 = self.to_screen(*event.end)
            pygame.draw.line(overlay, color, (sx1, sy1), (sx2, sy2), self._ss(3))
            marker_r = max(self._ss(8), self._ss(18 - event.life))
            pygame.draw.circle(overlay, color, (sx2, sy2), marker_r, 2)
            r2 = self._ss(7)
            pygame.draw.line(overlay, color, (sx2 - r2, sy2), (sx2 + r2, sy2), 2)
            pygame.draw.line(overlay, color, (sx2, sy2 - r2), (sx2, sy2 + r2), 2)
            self.screen.blit(overlay, (0, 0))

    def _draw_units(self, units: list[Unit], show_wrecks: bool = True) -> None:
        for unit in units:
            sx, sy = self.to_screen(unit.x, unit.y)
            is_wreck = unit.status == STATUS_DESTROYED
            color = RED_COLOR if unit.team == "red" else BLUE_COLOR
            if is_wreck:
                color = (95, 95, 95)

            if isinstance(unit, CommandNode):
                cs = self._ss(COMMAND_SIZE)
                rect = pygame.Rect(0, 0, cs, cs)
                rect.center = (sx, sy)
                if is_wreck:
                    wreck_surf = pygame.Surface((cs, cs), pygame.SRCALPHA)
                    wreck_surf.fill((*color, 140))
                    self.screen.blit(wreck_surf, rect.topleft)
                else:
                    pygame.draw.rect(self.screen, color, rect)
                pygame.draw.rect(self.screen, TEXT_COLOR, rect, 2)
            else:
                ur = self._ss(UNIT_RADIUS)
                if is_wreck:
                    d = ur * 2
                    wreck_surf = pygame.Surface((d, d), pygame.SRCALPHA)
                    pygame.draw.circle(wreck_surf, (*color, 140), (ur, ur), ur)
                    self.screen.blit(wreck_surf, (sx - ur, sy - ur))
                else:
                    pygame.draw.circle(self.screen, color, (sx, sy), ur)
                pygame.draw.circle(self.screen, TEXT_COLOR, (sx, sy), ur, 1)

            self._draw_hp_bar(unit, sx, sy)
            self._draw_unit_label(unit, sx, sy)

    def _draw_hp_bar(self, unit: Unit, sx: int, sy: int) -> None:
        w = self._ss(34)
        h = max(3, self._ss(5))
        x = sx - w // 2
        y = sy - self._ss(24)
        pygame.draw.rect(self.screen, HP_RED, (x, y, w, h))
        hp_w = int(w * max(0, unit.hp_ratio))
        pygame.draw.rect(self.screen, HP_GREEN, (x, y, hp_w, h))
        pygame.draw.rect(self.screen, (18, 18, 18), (x, y, w, h), 1)

    def _draw_unit_label(self, unit: Unit, sx: int, sy: int) -> None:
        name_text = self.small_font.render(unit.name, True, TEXT_COLOR)
        status_label = STATUS_LABELS.get(unit.status, unit.status)
        status_text = self.small_font.render(status_label, True, TEXT_COLOR)
        self.screen.blit(name_text, (sx - name_text.get_width() // 2, sy + self._ss(13)))
        self.screen.blit(status_text, (sx - status_text.get_width() // 2, sy + self._ss(27)))

    # ── 编辑预览绘制 ──────────────────────────────────────────

    def _draw_obstacle_preview(self, editor) -> None:
        rect = editor.preview_rect
        if rect is None:
            return
        rx, ry, rw, rh = rect
        sx, sy = self.to_screen(rx, ry)
        sw, sh = self._ss(rw, rh)
        preview = pygame.Surface((self.map_w, self.map_h), pygame.SRCALPHA)
        pygame.draw.rect(preview, (255, 215, 95, 100), (sx, sy, sw, sh))
        pygame.draw.rect(preview, (255, 215, 95, 200), (sx, sy, sw, sh), 2)
        self.screen.blit(preview, (0, 0))

    def _draw_selected_highlight(self, battlefield, editor) -> None:
        idx = editor.state.selected_obs_idx
        if idx is None or idx >= len(battlefield.obstacles):
            return
        obs = battlefield.obstacles[idx]
        sx, sy = self.to_screen(obs.x, obs.y)
        sw, sh = self._ss(obs.width, obs.height)
        pygame.draw.rect(self.screen, (255, 215, 95),
                         pygame.Rect(sx, sy, sw, sh), self._ss(3))

    def _draw_resize_handle(self, battlefield, editor) -> None:
        idx = editor.state.selected_obs_idx
        if idx is None or idx >= len(battlefield.obstacles):
            return
        obs = battlefield.obstacles[idx]
        hs = self._ss(RESIZE_HANDLE)
        hx, hy = self.to_screen(obs.x + obs.width, obs.y + obs.height)
        handle_rect = pygame.Rect(hx - hs, hy - hs, hs, hs)
        pygame.draw.rect(self.screen, (255, 215, 95), handle_rect)
        pygame.draw.rect(self.screen, (200, 160, 60), handle_rect, 1)
