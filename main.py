"""无人装备战争游戏仿真系统入口。"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ['SDL_VIDEO_WINDOW_POS'] = 'center'

try:
    import pygame
except ModuleNotFoundError:
    class _FallbackEvent:
        @staticmethod
        def Event(event_type, **attrs):
            return SimpleNamespace(type=event_type, **attrs)

    class _PygameFallback:
        KEYDOWN = 768
        MOUSEBUTTONDOWN = 1025
        MOUSEBUTTONUP = 1026
        MOUSEMOTION = 1024
        QUIT = 256
        K_ESCAPE = 27
        K_RETURN = 13
        K_BACKSPACE = 8
        K_SPACE = 32
        K_F11 = 292
        K_DELETE = 127
        K_1 = 49; K_2 = 50; K_3 = 51; K_4 = 52; K_5 = 53
        K_6 = 54; K_7 = 55; K_8 = 56
        K_c = 99; K_m = 109; K_r = 114; K_s = 115; K_t = 116
        K_e = 101; K_k = 107; K_l = 108
        KMOD_CTRL = 64
        FULLSCREEN = 0x80000000
        SCALED = 512
        SRCALPHA = 0x00010000

        @staticmethod
        def key_get_mods():
            return 0

        event = _FallbackEvent()

        @staticmethod
        def init():
            raise ModuleNotFoundError("pygame is required to run the graphical simulator")

    pygame = _PygameFallback()

from config import (
    BATTLEFIELD_H,
    BATTLEFIELD_W,
    DEFAULT_SCREEN_HEIGHT,
    DEFAULT_SCREEN_WIDTH,
    FPS,
    FULLSCREEN,
    GAME_DEPLOYMENT,
    GAME_FINISHED,
    GAME_PAUSED,
    GAME_RUNNING,
    SIMULATION_INTERVAL_MS,
)
from core.deployment import DeploymentManager
from core.map_persistence import list_scenarios, load_scenario_file, save_scenario
from core.scenario_loader import load_scenario
from core.simulator import Simulator


BASE_DIR = Path(__file__).resolve().parent
SCENARIO_PATH = BASE_DIR / "data" / "scenario_1.json"


def _window_on_top() -> None:
    """将窗口置于最前端（临时置顶后取消，使窗口保持在最上）。"""
    try:
        import ctypes
        hwnd = pygame.display.get_wm_info()['window']
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        # 临时置顶，强制窗口跳到 Z 序最前
        ctypes.windll.user32.SetWindowPos(
            hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        # 取消置顶，窗口保持当前位置（仍在其他窗口之上）
        ctypes.windll.user32.SetWindowPos(
            hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    except Exception:
        pass


def create_deployment() -> tuple[DeploymentManager, object]:
    battlefield, preset_units = load_scenario(SCENARIO_PATH)
    return DeploymentManager(battlefield, preset_units), battlefield


def main() -> None:
    from ui.renderer import Renderer

    pygame.init()
    pygame.display.set_caption("无人装备战争游戏仿真系统")
    flags = 0
    screen = pygame.display.set_mode((DEFAULT_SCREEN_WIDTH, DEFAULT_SCREEN_HEIGHT), flags)
    pygame.display.flip()
    pygame.event.pump()
    _window_on_top()
    fullscreen = FULLSCREEN
    clock = pygame.time.Clock()

    deployment, battlefield = create_deployment()
    simulator: Simulator | None = None
    renderer = Renderer(screen, BATTLEFIELD_W, BATTLEFIELD_H)

    game_state = GAME_DEPLOYMENT
    running = True
    last_step_time = pygame.time.get_ticks()

    while running:
        ctrl_held = pygame.key.get_mods() & pygame.KMOD_CTRL

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                fullscreen = not fullscreen
                if fullscreen:
                    screen = pygame.display.set_mode(
                        (DEFAULT_SCREEN_WIDTH, DEFAULT_SCREEN_HEIGHT),
                        pygame.FULLSCREEN | pygame.SCALED)
                else:
                    screen = pygame.display.set_mode(
                        (DEFAULT_SCREEN_WIDTH, DEFAULT_SCREEN_HEIGHT))
                renderer = Renderer(screen, BATTLEFIELD_W, BATTLEFIELD_H)
                _window_on_top()

            elif game_state == GAME_DEPLOYMENT:
                if event.type == pygame.KEYDOWN:
                    # Ctrl+S 保存
                    if event.key == pygame.K_s and ctrl_held:
                        filepath = BASE_DIR / "data" / "saved_map.json"
                        try:
                            save_scenario(battlefield, deployment.display_units(), filepath)
                            deployment.last_message = f"地图保存成功: {filepath.name}"
                        except Exception as e:
                            deployment.last_message = f"保存失败: {e}"
                    # L 加载
                    elif event.key == pygame.K_l and not ctrl_held:
                        data_dir = BASE_DIR / "data"
                        files = list_scenarios(data_dir)
                        if files:
                            filepath = data_dir / files[0]
                            try:
                                loaded_bf, loaded_units = load_scenario_file(filepath)
                                deployment.reset_to_preset(loaded_units)
                                deployment.battlefield = loaded_bf
                                deployment.last_message = f"地图加载成功: {files[0]}"
                                battlefield = loaded_bf
                            except Exception as e:
                                deployment.last_message = f"加载失败: {e}"
                    else:
                        simulator, game_state, deployment, battlefield, running = \
                            handle_deployment_event(
                                event, deployment, battlefield, simulator, game_state, running)

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    bf_x, bf_y = renderer.to_battlefield(*event.pos)
                    deployment.handle_mouse_down(event.button, bf_x, bf_y)
                elif event.type == pygame.MOUSEBUTTONUP:
                    bf_x, bf_y = renderer.to_battlefield(*event.pos)
                    deployment.handle_mouse_up(event.button, bf_x, bf_y)
                elif event.type == pygame.MOUSEMOTION:
                    bf_x, bf_y = renderer.to_battlefield(*event.pos)
                    deployment.handle_mouse_motion(bf_x, bf_y)

                last_step_time = pygame.time.get_ticks()

            elif event.type == pygame.KEYDOWN and game_state != GAME_DEPLOYMENT:
                simulator, game_state, deployment, battlefield = handle_runtime_key(
                    event.key, simulator, game_state, deployment, battlefield)
                last_step_time = pygame.time.get_ticks()

        now = pygame.time.get_ticks()
        if game_state == GAME_RUNNING and simulator and \
           now - last_step_time >= SIMULATION_INTERVAL_MS:
            simulator.step()
            if simulator.winner:
                game_state = GAME_FINISHED
            last_step_time = now

        if game_state == GAME_DEPLOYMENT:
            renderer.render_deployment(battlefield, deployment.display_units(), deployment)
        elif simulator:
            renderer.render(simulator, game_state)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


def handle_deployment_event(event, deployment, battlefield, simulator,
                            game_state, running=True):
    action = None
    if event.type == pygame.KEYDOWN:
        action = deployment.handle_key(event.key, getattr(event, "unicode", ""))
    elif event.type == pygame.MOUSEBUTTONDOWN:
        action = deployment.handle_mouse_button(event.button, event.pos, battlefield)

    if action == "quit":
        running = False
    elif action == "reset":
        deployment, battlefield = create_deployment()
        simulator = None
        game_state = GAME_DEPLOYMENT
    elif action == "start":
        result = deployment.finalize()
        if result.ok:
            simulator = Simulator(battlefield, result.units)
            game_state = GAME_RUNNING
    return simulator, game_state, deployment, battlefield, running


def handle_runtime_key(key, simulator, game_state, deployment, battlefield):
    if key == pygame.K_SPACE:
        if game_state == GAME_RUNNING:
            game_state = GAME_PAUSED
        elif game_state == GAME_PAUSED:
            game_state = GAME_RUNNING
    elif key == pygame.K_s and simulator and \
            game_state in (GAME_RUNNING, GAME_PAUSED, GAME_FINISHED):
        simulator.step()
        game_state = GAME_FINISHED if simulator.winner else GAME_PAUSED
    elif key == pygame.K_k and simulator:
        simulator.show_wrecks = not simulator.show_wrecks
    elif key == pygame.K_r:
        deployment, battlefield = create_deployment()
        simulator = None
        game_state = GAME_DEPLOYMENT
    return simulator, game_state, deployment, battlefield


if __name__ == "__main__":
    main()
