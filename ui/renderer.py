"""Pygame 可视化渲染器。"""

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
    MAP_HEIGHT,
    MAP_WIDTH,
    OBSTACLE_COLOR,
    RED_COLOR,
    RESIZE_HANDLE,
    SIM_SPEED_LEVELS,
    STATUS_DESTROYED,
    STATUS_LABELS,
    TEXT_COLOR,
    UNIT_RADIUS,
)
from core.battlefield import obstacle_display_name
from core.units import CommandNode, Unit
from ui.panel import InfoPanel


class Renderer:
    """负责地图、单位、血条、探测圈和攻击特效绘制。"""

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.panel = InfoPanel()
        self.font = pygame.font.SysFont("Microsoft YaHei", 13)
        self.small_font = pygame.font.SysFont("Microsoft YaHei", 11)

    # ── 运行阶段 ──────────────────────────────────────────────

    def render(self, simulator, game_state: str, sim_speed_index: int = 0) -> None:
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_grid()
        self._draw_bases(simulator.battlefield)
        self._draw_obstacles(simulator.battlefield)
        self._draw_detection_ranges(simulator.units)
        self._draw_attack_events(simulator.attack_events)
        visible = simulator.units if simulator.show_wrecks else [
            u for u in simulator.units if not u.is_destroyed]
        self._draw_units(visible, simulator.show_wrecks)
        speed_label = SIM_SPEED_LEVELS[sim_speed_index][0]
        self.panel.draw_runtime(self.screen, simulator, game_state, speed_label)

    # ── 部署阶段 ──────────────────────────────────────────────

    def render_deployment(self, battlefield, units: list[Unit],
                          deployment) -> None:
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

    # ── 网格 / 障碍物 / 基地 ────────────────────────────────

    def _draw_grid(self) -> None:
        for x in range(0, MAP_WIDTH + 1, 40):
            pygame.draw.line(self.screen, GRID_COLOR, (x, 0), (x, MAP_HEIGHT), 1)
        for y in range(0, MAP_HEIGHT + 1, 40):
            pygame.draw.line(self.screen, GRID_COLOR, (0, y), (MAP_WIDTH, y), 1)
        pygame.draw.rect(self.screen, (75, 83, 96), (0, 0, MAP_WIDTH, MAP_HEIGHT), 2)

    def _draw_obstacles(self, battlefield) -> None:
        for obstacle in battlefield.obstacles:
            rect = pygame.Rect(*obstacle.rect)
            color = self._obstacle_color(obstacle.type)
            pygame.draw.rect(self.screen, color, rect)
            pygame.draw.rect(self.screen, (125, 130, 140), rect, 2)
            label = self.small_font.render(obstacle_display_name(obstacle), True, TEXT_COLOR)
            self.screen.blit(label, (rect.x + 4, rect.y + 2))

    def _draw_bases(self, battlefield) -> None:
        for label, base_obj, color in (
            ("红基地", battlefield.red_base_obj, RED_COLOR),
            ("蓝基地", battlefield.blue_base_obj, BLUE_COLOR),
        ):
            x, y = int(base_obj.x), int(base_obj.y)
            pygame.draw.circle(self.screen, color, (x, y), 18, 2)
            pygame.draw.line(self.screen, color, (x - 12, y), (x + 12, y), 2)
            pygame.draw.line(self.screen, color, (x, y - 12), (x, y + 12), 2)
            text = self.small_font.render(label, True, TEXT_COLOR)
            self.screen.blit(text, (x - text.get_width() // 2, y + 20))
            # 基地血条
            bw, bh = 40, 5
            bar_x = x - bw // 2
            bar_y = y - 30
            pygame.draw.rect(self.screen, HP_RED, (bar_x, bar_y, bw, bh))
            hp_w = int(bw * max(0, base_obj.hp_ratio))
            pygame.draw.rect(self.screen, HP_GREEN, (bar_x, bar_y, hp_w, bh))
            pygame.draw.rect(self.screen, (18, 18, 18), (bar_x, bar_y, bw, bh), 1)

    @staticmethod
    def _obstacle_color(obstacle_type: str) -> tuple[int, int, int]:
        if obstacle_type == "mountain":
            return (92, 105, 92)
        if obstacle_type == "building":
            return (96, 98, 112)
        if obstacle_type == "restricted":
            return (116, 82, 82)
        return OBSTACLE_COLOR

    # ── 探测 / 攻击特效 ─────────────────────────────────────

    def _draw_detection_ranges(self, units: list[Unit]) -> None:
        overlay = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
        for unit in units:
            if unit.is_destroyed:
                continue
            color = DETECT_RED if unit.team == "red" else DETECT_BLUE
            pygame.draw.circle(overlay, color, (int(unit.x), int(unit.y)),
                               int(unit.detect_range), 1)
        self.screen.blit(overlay, (0, 0))

    def _draw_attack_events(self, events) -> None:
        for event in events:
            alpha = max(60, min(255, event.life * 32))
            color = (*ATTACK_EFFECT_COLOR[:3], alpha)
            overlay = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
            sx1, sy1 = int(event.start[0]), int(event.start[1])
            sx2, sy2 = int(event.end[0]), int(event.end[1])
            pygame.draw.line(overlay, color, (sx1, sy1), (sx2, sy2), 3)
            marker_r = max(8, 18 - event.life)
            pygame.draw.circle(overlay, color, (sx2, sy2), marker_r, 2)
            pygame.draw.line(overlay, color, (sx2 - 7, sy2), (sx2 + 7, sy2), 2)
            pygame.draw.line(overlay, color, (sx2, sy2 - 7), (sx2, sy2 + 7), 2)
            self.screen.blit(overlay, (0, 0))

    # ── 单位 ──────────────────────────────────────────────────

    def _draw_units(self, units: list[Unit], show_wrecks: bool = True) -> None:
        for unit in units:
            sx, sy = int(unit.x), int(unit.y)
            is_wreck = unit.status == STATUS_DESTROYED
            color = RED_COLOR if unit.team == "red" else BLUE_COLOR
            if is_wreck:
                color = (95, 95, 95)

            if isinstance(unit, CommandNode):
                rect = pygame.Rect(0, 0, COMMAND_SIZE, COMMAND_SIZE)
                rect.center = (sx, sy)
                if is_wreck:
                    wreck_surf = pygame.Surface((COMMAND_SIZE, COMMAND_SIZE), pygame.SRCALPHA)
                    wreck_surf.fill((*color, 140))
                    self.screen.blit(wreck_surf, rect.topleft)
                else:
                    pygame.draw.rect(self.screen, color, rect)
                pygame.draw.rect(self.screen, TEXT_COLOR, rect, 2)
            else:
                if is_wreck:
                    d = UNIT_RADIUS * 2
                    wreck_surf = pygame.Surface((d, d), pygame.SRCALPHA)
                    pygame.draw.circle(wreck_surf, (*color, 140), (UNIT_RADIUS, UNIT_RADIUS), UNIT_RADIUS)
                    self.screen.blit(wreck_surf, (sx - UNIT_RADIUS, sy - UNIT_RADIUS))
                else:
                    pygame.draw.circle(self.screen, color, (sx, sy), UNIT_RADIUS)
                pygame.draw.circle(self.screen, TEXT_COLOR, (sx, sy), UNIT_RADIUS, 1)

            self._draw_hp_bar(unit, sx, sy)
            self._draw_unit_label(unit, sx, sy)

    def _draw_hp_bar(self, unit: Unit, sx: int, sy: int) -> None:
        w, h = 34, 5
        x = sx - w // 2
        y = sy - 24
        pygame.draw.rect(self.screen, HP_RED, (x, y, w, h))
        hp_w = int(w * max(0, unit.hp_ratio))
        pygame.draw.rect(self.screen, HP_GREEN, (x, y, hp_w, h))
        pygame.draw.rect(self.screen, (18, 18, 18), (x, y, w, h), 1)

    def _draw_unit_label(self, unit: Unit, sx: int, sy: int) -> None:
        name_text = self.small_font.render(unit.name, True, TEXT_COLOR)
        status_label = STATUS_LABELS.get(unit.status, unit.status)
        status_text = self.small_font.render(status_label, True, TEXT_COLOR)
        self.screen.blit(name_text, (sx - name_text.get_width() // 2, sy + 13))
        self.screen.blit(status_text, (sx - status_text.get_width() // 2, sy + 27))

    # ── 编辑预览 ──────────────────────────────────────────────

    def _draw_obstacle_preview(self, editor) -> None:
        rect = editor.preview_rect
        if rect is None:
            return
        rx, ry, rw, rh = rect
        preview = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
        pygame.draw.rect(preview, (255, 215, 95, 100), (rx, ry, rw, rh))
        pygame.draw.rect(preview, (255, 215, 95, 200), (rx, ry, rw, rh), 2)
        self.screen.blit(preview, (0, 0))

    def _draw_selected_highlight(self, battlefield, editor) -> None:
        idx = editor.state.selected_obs_idx
        if idx is None or idx >= len(battlefield.obstacles):
            return
        obs = battlefield.obstacles[idx]
        pygame.draw.rect(self.screen, (255, 215, 95),
                         pygame.Rect(obs.x, obs.y, obs.width, obs.height), 3)

    def _draw_resize_handle(self, battlefield, editor) -> None:
        idx = editor.state.selected_obs_idx
        if idx is None or idx >= len(battlefield.obstacles):
            return
        obs = battlefield.obstacles[idx]
        hx, hy = obs.x + obs.width, obs.y + obs.height
        hs = RESIZE_HANDLE
        handle_rect = pygame.Rect(hx - hs, hy - hs, hs, hs)
        pygame.draw.rect(self.screen, (255, 215, 95), handle_rect)
        pygame.draw.rect(self.screen, (200, 160, 60), handle_rect, 1)
