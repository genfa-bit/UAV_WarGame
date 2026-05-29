"""右侧信息面板绘制。"""

from __future__ import annotations

import pygame

from config import (
    GAME_DEPLOYMENT,
    GAME_FINISHED,
    GAME_PAUSED,
    GAME_RUNNING,
    MAP_WIDTH,
    PANEL_BG,
    PANEL_WIDTH,
    SCREEN_HEIGHT,
    TEXT_COLOR,
)


class InfoPanel:
    """显示部署提示或运行期统计信息。"""

    def __init__(self) -> None:
        self.font = pygame.font.SysFont("Microsoft YaHei", 15)
        self.small_font = pygame.font.SysFont("Microsoft YaHei", 13)
        self.title_font = pygame.font.SysFont("Microsoft YaHei", 20, bold=True)

    def draw_runtime(self, surface: pygame.Surface, simulator, game_state: str) -> None:
        """绘制运行阶段信息。"""
        self._draw_background(surface)
        snapshot = simulator.status_snapshot()
        lines = [
            ("无人装备战争游戏", self.title_font),
            (f"时间步: {snapshot['time_step']}", self.font),
            (f"系统状态: {self._state_text(game_state)}", self.font),
            ("", self.font),
            (f"剩余 红/蓝: {snapshot['red_remaining']} / {snapshot['blue_remaining']}", self.font),
            (f"摧毁 红/蓝: {snapshot['red_kills']} / {snapshot['blue_kills']}", self.font),
            (f"攻击 红/蓝: {snapshot['red_attacks']} / {snapshot['blue_attacks']}", self.font),
            (f"伤害 红/蓝: {snapshot['red_damage']} / {snapshot['blue_damage']}", self.font),
            (f"发现 红/蓝: {snapshot['red_detected']} / {snapshot['blue_detected']}", self.font),
            (f"红方集火: {snapshot['red_focus']}", self.small_font),
            (f"蓝方集火: {snapshot['blue_focus']}", self.small_font),
            (f"规避 红/蓝: {snapshot['red_evading']} / {snapshot['blue_evading']}", self.small_font),
            (f"规避单位: {snapshot['evading_units'] or 'None'}", self.small_font),
            (self._winner_text(snapshot["winner"]), self.title_font),
            ("", self.font),
            ("最近日志", self.font),
            *[(self._fit_log(line), self.small_font) for line in simulator.combat_logs[-6:]],
            ("", self.font),
            ("Space  暂停/继续", self.small_font),
            ("S      单步推进", self.small_font),
            ("R      返回部署预设", self.small_font),
            ("ESC    退出", self.small_font),
        ]
        self._draw_lines(surface, lines, start_y=16, line_height=22)

    def draw_deployment(self, surface: pygame.Surface, deployment) -> None:
        """绘制部署阶段信息。"""
        self._draw_background(surface)
        lines = [
            ("部署阶段", self.title_font),
            ("", self.font),
            (f"系统状态: {self._state_text(GAME_DEPLOYMENT)}", self.font),
            (f"部署模式: {deployment.mode_label}", self.font),
            (f"当前阵营: {deployment.selected_team}", self.font),
            (f"当前兵种: {deployment.selected_label}", self.small_font),
            (f"当前显示单位: {len(deployment.display_units())}", self.font),
            (f"手动部署数量: {len(deployment.manual_units)}", self.font),
            ("", self.font),
            ("Enter  开始仿真", self.small_font),
            ("M      切换模式", self.small_font),
            ("1      ScoutDrone", self.small_font),
            ("2      StrikeDrone", self.small_font),
            ("3      GroundVehicle", self.small_font),
            ("4      MissileVehicle", self.small_font),
            ("5      CommandNode", self.small_font),
            ("T      切换 red/blue", self.small_font),
            ("鼠标左键 放置单位", self.small_font),
            ("Backspace 撤销", self.small_font),
            ("C      清空手动部署", self.small_font),
            ("R      恢复预设开局", self.small_font),
            ("ESC    退出", self.small_font),
            ("提示: 请切换英文输入法", self.small_font),
            ("", self.font),
            (deployment.last_message, self.small_font),
        ]
        self._draw_lines(surface, lines, start_y=18, line_height=22)

    def _draw_background(self, surface: pygame.Surface) -> None:
        panel_rect = pygame.Rect(MAP_WIDTH, 0, PANEL_WIDTH, SCREEN_HEIGHT)
        pygame.draw.rect(surface, PANEL_BG, panel_rect)

    def _draw_lines(self, surface: pygame.Surface, lines, start_y: int = 22, line_height: int = 27) -> None:
        y = start_y
        for text, font in lines:
            if text:
                rendered = font.render(text, True, TEXT_COLOR)
                surface.blit(rendered, (MAP_WIDTH + 14, y))
            y += line_height

    def _state_text(self, game_state: str) -> str:
        mapping = {
            GAME_DEPLOYMENT: "Deployment",
            GAME_RUNNING: "Running",
            GAME_PAUSED: "Paused",
            GAME_FINISHED: "Finished",
        }
        return mapping.get(game_state, game_state)

    def _winner_text(self, winner: str | None) -> str:
        if winner == "red":
            return "结果: 红方获胜"
        if winner == "blue":
            return "结果: 蓝方获胜"
        if winner == "draw":
            return "结果: 平局"
        return "结果: 交战中"

    def _fit_log(self, text: str) -> str:
        max_chars = 24
        return text if len(text) <= max_chars else text[: max_chars - 1] + "…"
