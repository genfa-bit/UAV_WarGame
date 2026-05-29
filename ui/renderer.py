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
    STATUS_DESTROYED,
    TEXT_COLOR,
    UNIT_RADIUS,
)
from core.units import CommandNode, Unit
from ui.panel import InfoPanel


class Renderer:
    """负责地图、单位、血条、探测圈和攻击特效绘制。"""

    def __init__(self, screen: pygame.Surface) -> None:
        self.screen = screen
        self.panel = InfoPanel()
        self.font = pygame.font.SysFont("Microsoft YaHei", 13)
        self.small_font = pygame.font.SysFont("Microsoft YaHei", 11)

    def render(self, simulator, game_state: str) -> None:
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_grid()
        self._draw_bases(simulator.battlefield)
        self._draw_obstacles(simulator.battlefield)
        self._draw_detection_ranges(simulator.units)
        self._draw_attack_events(simulator.attack_events)
        self._draw_units(simulator.units)
        self.panel.draw_runtime(self.screen, simulator, game_state)

    def render_deployment(self, battlefield, units: list[Unit], deployment) -> None:
        """绘制部署阶段界面。"""
        self.screen.fill(BACKGROUND_COLOR)
        self._draw_grid()
        self._draw_bases(battlefield)
        self._draw_obstacles(battlefield)
        self._draw_units(units)
        self.panel.draw_deployment(self.screen, deployment)

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
            label = self.small_font.render(obstacle.name, True, TEXT_COLOR)
            self.screen.blit(label, (rect.x + 4, rect.y + 4))

    def _draw_bases(self, battlefield) -> None:
        """绘制红蓝基地位置，便于说明规避撤退方向。"""
        for team, pos, color in (
            ("红基地", battlefield.red_base, RED_COLOR),
            ("蓝基地", battlefield.blue_base, BLUE_COLOR),
        ):
            x, y = int(pos[0]), int(pos[1])
            pygame.draw.circle(self.screen, color, (x, y), 18, 2)
            pygame.draw.line(self.screen, color, (x - 12, y), (x + 12, y), 2)
            pygame.draw.line(self.screen, color, (x, y - 12), (x, y + 12), 2)
            label = self.small_font.render(team, True, TEXT_COLOR)
            self.screen.blit(label, (x - label.get_width() // 2, y + 20))

    def _obstacle_color(self, obstacle_type: str) -> tuple[int, int, int]:
        """按障碍物类型设置颜色。"""
        if obstacle_type == "mountain":
            return (92, 105, 92)
        if obstacle_type == "building":
            return (96, 98, 112)
        if obstacle_type == "restricted":
            return (116, 82, 82)
        return OBSTACLE_COLOR

    def _draw_detection_ranges(self, units: list[Unit]) -> None:
        overlay = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
        for unit in units:
            if unit.is_destroyed:
                continue
            color = DETECT_RED if unit.team == "red" else DETECT_BLUE
            pygame.draw.circle(overlay, color, (int(unit.x), int(unit.y)), int(unit.detect_range), 1)
        self.screen.blit(overlay, (0, 0))

    def _draw_attack_events(self, events) -> None:
        for event in events:
            alpha = max(60, min(255, event.life * 32))
            color = (*ATTACK_EFFECT_COLOR[:3], alpha)
            overlay = pygame.Surface((MAP_WIDTH, MAP_HEIGHT), pygame.SRCALPHA)
            start = (int(event.start[0]), int(event.start[1]))
            end = (int(event.end[0]), int(event.end[1]))
            pygame.draw.line(overlay, color, start, end, 3)
            marker_radius = max(8, 18 - event.life)
            pygame.draw.circle(overlay, color, end, marker_radius, 2)
            pygame.draw.line(overlay, color, (end[0] - 7, end[1]), (end[0] + 7, end[1]), 2)
            pygame.draw.line(overlay, color, (end[0], end[1] - 7), (end[0], end[1] + 7), 2)
            self.screen.blit(overlay, (0, 0))

    def _draw_units(self, units: list[Unit]) -> None:
        for unit in units:
            color = RED_COLOR if unit.team == "red" else BLUE_COLOR
            if unit.status == STATUS_DESTROYED:
                color = (95, 95, 95)

            if isinstance(unit, CommandNode):
                rect = pygame.Rect(0, 0, COMMAND_SIZE, COMMAND_SIZE)
                rect.center = (int(unit.x), int(unit.y))
                pygame.draw.rect(self.screen, color, rect)
                pygame.draw.rect(self.screen, TEXT_COLOR, rect, 2)
            else:
                pygame.draw.circle(self.screen, color, (int(unit.x), int(unit.y)), UNIT_RADIUS)
                pygame.draw.circle(self.screen, TEXT_COLOR, (int(unit.x), int(unit.y)), UNIT_RADIUS, 1)

            self._draw_hp_bar(unit)
            self._draw_unit_label(unit)

    def _draw_hp_bar(self, unit: Unit) -> None:
        width = 34
        height = 5
        x = int(unit.x - width / 2)
        y = int(unit.y - 24)
        pygame.draw.rect(self.screen, HP_RED, (x, y, width, height))
        hp_width = int(width * max(0, unit.hp_ratio))
        pygame.draw.rect(self.screen, HP_GREEN, (x, y, hp_width, height))
        pygame.draw.rect(self.screen, (18, 18, 18), (x, y, width, height), 1)

    def _draw_unit_label(self, unit: Unit) -> None:
        name_text = self.small_font.render(unit.name, True, TEXT_COLOR)
        status_text = self.small_font.render(unit.status, True, TEXT_COLOR)
        self.screen.blit(name_text, (int(unit.x) - name_text.get_width() // 2, int(unit.y) + 13))
        self.screen.blit(status_text, (int(unit.x) - status_text.get_width() // 2, int(unit.y) + 27))
