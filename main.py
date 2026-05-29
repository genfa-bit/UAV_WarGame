"""无人装备战争游戏仿真系统入口。

main.py 负责窗口初始化、事件分发和状态流转；部署规则、仿真逻辑和绘制
逻辑分别放在 core/deployment.py、core/simulator.py 和 ui/ 中。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

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
        QUIT = 256
        K_ESCAPE = 27
        K_RETURN = 13
        K_BACKSPACE = 8
        K_SPACE = 32
        K_1 = 49
        K_2 = 50
        K_3 = 51
        K_4 = 52
        K_5 = 53
        K_c = 99
        K_m = 109
        K_r = 114
        K_s = 115
        K_t = 116
        event = _FallbackEvent()

        @staticmethod
        def init():
            raise ModuleNotFoundError("pygame is required to run the graphical simulator")

    pygame = _PygameFallback()

from config import (
    FPS,
    GAME_DEPLOYMENT,
    GAME_FINISHED,
    GAME_PAUSED,
    GAME_RUNNING,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SIMULATION_INTERVAL_MS,
)
from core.deployment import DeploymentManager
from core.scenario_loader import load_scenario
from core.simulator import Simulator


BASE_DIR = Path(__file__).resolve().parent
SCENARIO_PATH = BASE_DIR / "data" / "scenario_1.json"


def create_deployment() -> tuple[DeploymentManager, object]:
    """加载预设场景并创建部署管理器。"""
    battlefield, preset_units = load_scenario(SCENARIO_PATH)
    return DeploymentManager(battlefield, preset_units), battlefield


def main() -> None:
    from ui.renderer import Renderer

    pygame.init()
    pygame.display.set_caption("无人装备战争游戏仿真系统")
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    clock = pygame.time.Clock()

    deployment, battlefield = create_deployment()
    simulator: Simulator | None = None
    renderer = Renderer(screen)

    game_state = GAME_DEPLOYMENT
    running = True
    last_step_time = pygame.time.get_ticks()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif game_state == GAME_DEPLOYMENT:
                simulator, game_state, deployment, battlefield, running = handle_deployment_event(
                    event,
                    deployment,
                    battlefield,
                    simulator,
                    game_state,
                    running,
                )
                last_step_time = pygame.time.get_ticks()
            elif event.type == pygame.KEYDOWN:
                simulator, game_state, deployment, battlefield = handle_runtime_key(
                    event.key,
                    simulator,
                    game_state,
                    deployment,
                    battlefield,
                )
                last_step_time = pygame.time.get_ticks()

        now = pygame.time.get_ticks()
        if game_state == GAME_RUNNING and simulator and now - last_step_time >= SIMULATION_INTERVAL_MS:
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


def handle_deployment_event(event, deployment, battlefield, simulator, game_state, running=True):
    """处理部署阶段事件，并根据 DeploymentManager 的动作切换状态。"""
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


def handle_deployment_key(key, deployment, battlefield, simulator, game_state):
    """兼容旧测试和调用方的部署阶段按键处理。"""
    event = pygame.event.Event(pygame.KEYDOWN, key=key)
    simulator, game_state, deployment, battlefield, _ = handle_deployment_event(
        event,
        deployment,
        battlefield,
        simulator,
        game_state,
    )
    return simulator, game_state, deployment, battlefield


def handle_runtime_key(key, simulator, game_state, deployment, battlefield):
    """处理运行、暂停和结束阶段按键。"""
    if key == pygame.K_SPACE:
        if game_state == GAME_RUNNING:
            game_state = GAME_PAUSED
        elif game_state == GAME_PAUSED:
            game_state = GAME_RUNNING
    elif key == pygame.K_s and simulator and game_state in (GAME_RUNNING, GAME_PAUSED):
        simulator.step()
        game_state = GAME_FINISHED if simulator.winner else GAME_PAUSED
    elif key == pygame.K_r:
        deployment, battlefield = create_deployment()
        simulator = None
        game_state = GAME_DEPLOYMENT
    return simulator, game_state, deployment, battlefield


if __name__ == "__main__":
    main()
