"""右侧信息面板绘制。"""

from __future__ import annotations

import pygame

from config import (
    MAP_WIDTH,
    PANEL_BG,
    PANEL_WIDTH,
    SCREEN_HEIGHT,
    STATE_LABELS,
    TEXT_COLOR,
)


class InfoPanel:
    """显示部署提示或运行期统计信息。"""

    def __init__(self):
        self.font = pygame.font.SysFont("Microsoft YaHei", 15)
        self.small_font = pygame.font.SysFont("Microsoft YaHei", 13)
        self.title_font = pygame.font.SysFont("Microsoft YaHei", 20, bold=True)

    # ── 运行阶段 ──────────────────────────────────────────────

    def draw_runtime(self, surface: pygame.Surface, simulator, game_state: str) -> None:
        self._draw_background(surface)
        snapshot = simulator.status_snapshot()
        wreck_status = "开启" if simulator.show_wrecks else "关闭"
        lines = [
            ("无人装备战争游戏", self.title_font),
            (f"时间步: {snapshot['time_step']}", self.font),
            (f"系统状态: {self._state_text(game_state)}", self.font),
            (f"残骸显示: {wreck_status}", self.small_font),
            ("", self.font),
            ("── 战场态势 ──", self.small_font),
            (f"红方战力: {snapshot['red_strength']}  基地: {snapshot['red_base_hp']}/{snapshot['red_base_max']}", self.font),
            (f"蓝方战力: {snapshot['blue_strength']}  基地: {snapshot['blue_base_hp']}/{snapshot['blue_base_max']}", self.font),
            (f"红方态势: {snapshot['red_situation']} ({snapshot['red_tactics']})", self.small_font),
            (f"蓝方态势: {snapshot['blue_situation']} ({snapshot['blue_tactics']})", self.small_font),
            (f"红方行为: {snapshot['red_behavior']}", self.small_font),
            (f"蓝方行为: {snapshot['blue_behavior']}", self.small_font),
            ("", self.font),
            (f"剩余 红/蓝: {snapshot['red_remaining']} / {snapshot['blue_remaining']}", self.font),
            (f"摧毁 红/蓝: {snapshot['red_kills']} / {snapshot['blue_kills']}", self.font),
            (f"攻击 红/蓝: {snapshot['red_attacks']} / {snapshot['blue_attacks']}", self.font),
            (f"伤害 红/蓝: {snapshot['red_damage']} / {snapshot['blue_damage']}", self.font),
            (f"发现 红/蓝: {snapshot['red_detected']} / {snapshot['blue_detected']}", self.font),
            (f"红方集火: {snapshot['red_focus']}", self.small_font),
            (f"蓝方集火: {snapshot['blue_focus']}", self.small_font),
            (f"规避 红/蓝: {snapshot['red_evading']} / {snapshot['blue_evading']}", self.small_font),
            (f"规避单位: {snapshot['evading_units'] or '无'}", self.small_font),
            (self._winner_text(snapshot["winner"]), self.title_font),
            ("", self.font),
            ("Space  暂停/继续", self.small_font),
            ("S      单步推进", self.small_font),
            ("K      切换残骸显示", self.small_font),
            ("R      返回部署", self.small_font),
            ("ESC    退出", self.small_font),
        ]
        self._draw_lines(surface, lines, start_y=8, line_height=19)

    # ── 部署阶段 ──────────────────────────────────────────────

    def draw_deployment(self, surface: pygame.Surface, deployment,
                        battlefield) -> None:
        self._draw_background(surface)
        selected = deployment.selected_label

        lines = [
            ("部署阶段", self.title_font),
            ("", self.font),
            (f"系统状态: {self._state_text('deployment')}", self.font),
            (f"当前阵营: {'红方' if deployment.selected_team == 'red' else '蓝方'}", self.font),
            (f"当前选择: {selected}", self.small_font),
            (f"单位数量: {len(deployment.display_units())}", self.font),
            (f"障碍物数量: {len(battlefield.obstacles)}", self.small_font),
            ("", self.font),
            ("── 作战单位 ──", self.small_font),
            ("1  侦察无人机", self.small_font),
            ("2  打击无人机", self.small_font),
            ("3  无人战车", self.small_font),
            ("4  导弹发射车", self.small_font),
            ("5  指挥节点", self.small_font),
            ("", self.font),
            ("── 障碍物 ──", self.small_font),
            ("6  山地", self.small_font),
            ("7  建筑", self.small_font),
            ("8  禁行区", self.small_font),
            ("", self.font),
            ("── 操作 ──", self.small_font),
            ("左键点击  放置对象", self.small_font),
            ("左键拖拽  移动对象", self.small_font),
            ("左键拖拽把手  调整障碍物大小", self.small_font),
            ("右键点击  删除对象", self.small_font),
            ("T   切换红/蓝方", self.small_font),
            ("Delete  删除选中障碍物", self.small_font),
            ("Backspace  撤销部署", self.small_font),
            ("C   清空地图", self.small_font),
            ("R   恢复预设开局", self.small_font),
            ("Enter  开始仿真", self.small_font),
            ("Ctrl+S  保存地图", self.small_font),
            ("L   加载地图", self.small_font),
            ("ESC  退出", self.small_font),
            ("提示: 请切换英文输入法", self.small_font),
            ("", self.font),
            (deployment.last_message, self.small_font),
        ]
        self._draw_lines(surface, lines, start_y=10, line_height=19)

    # ── 内部方法 ──────────────────────────────────────────────

    def _draw_background(self, surface: pygame.Surface) -> None:
        panel_rect = pygame.Rect(MAP_WIDTH, 0, PANEL_WIDTH, SCREEN_HEIGHT)
        pygame.draw.rect(surface, PANEL_BG, panel_rect)

    def _draw_lines(self, surface: pygame.Surface, lines, start_y: int = 22,
                    line_height: int = 27) -> None:
        y = start_y
        for text, font in lines:
            if text:
                rendered = font.render(text, True, TEXT_COLOR)
                surface.blit(rendered, (MAP_WIDTH + 10, y))
            y += line_height

    def _state_text(self, game_state: str) -> str:
        return STATE_LABELS.get(game_state, game_state)

    def _winner_text(self, winner: str | None) -> str:
        if winner == "red":
            return "结果: 红方获胜"
        if winner == "blue":
            return "结果: 蓝方获胜"
        if winner == "draw":
            return "结果: 平局"
        return "结果: 交战中"
