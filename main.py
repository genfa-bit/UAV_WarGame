"""无人装备战争游戏仿真系统入口。"""

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
        MOUSEBUTTONUP = 1026
        MOUSEMOTION = 1024
        QUIT = 256
        K_ESCAPE = 27
        K_RETURN = 13
        K_BACKSPACE = 8
        K_SPACE = 32
        K_DELETE = 127
        K_1 = 49; K_2 = 50; K_3 = 51; K_4 = 52; K_5 = 53
        K_6 = 54; K_7 = 55; K_8 = 56
        K_c = 99; K_f = 102; K_m = 109; K_r = 114; K_s = 115; K_t = 116
        K_e = 101; K_k = 107; K_l = 108
        KMOD_CTRL = 64
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
    FPS,
    GAME_DEPLOYMENT,
    GAME_FINISHED,
    GAME_PAUSED,
    GAME_RUNNING,
    SCREEN_HEIGHT,
    SCREEN_WIDTH,
    SIM_SPEED_LEVELS,
    SIMULATION_INTERVAL_MS,
)
from core.deployment import DeploymentManager
from core.map_persistence import list_scenarios, load_scenario_file, save_scenario
from core.scenario_loader import load_scenario
from core.simulator import Simulator


BASE_DIR = Path(__file__).resolve().parent
SCENARIO_PATH = BASE_DIR / "data" / "scenario_1.json"


def create_deployment() -> tuple[DeploymentManager, object]:
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
    sim_speed_index = 0
    sim_interval_ms = SIM_SPEED_LEVELS[0][1]

    while running:
        ctrl_held = pygame.key.get_mods() & pygame.KMOD_CTRL

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

            elif game_state == GAME_DEPLOYMENT:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_s and ctrl_held:
                        filepath = BASE_DIR / "data" / "saved_map.json"
                        try:
                            save_scenario(battlefield, deployment.display_units(), filepath)
                            deployment.last_message = f"地图保存成功: {filepath.name}"
                        except Exception as e:
                            deployment.last_message = f"保存失败: {e}"
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
                    deployment.handle_mouse_down(event.button, event.pos[0], event.pos[1])
                elif event.type == pygame.MOUSEBUTTONUP:
                    deployment.handle_mouse_up(event.button, event.pos[0], event.pos[1])
                elif event.type == pygame.MOUSEMOTION:
                    deployment.handle_mouse_motion(event.pos[0], event.pos[1])

                last_step_time = pygame.time.get_ticks()

            elif event.type == pygame.KEYDOWN and game_state != GAME_DEPLOYMENT:
                simulator, game_state, deployment, battlefield, sim_speed_index = handle_runtime_key(
                    event.key, simulator, game_state, deployment, battlefield, sim_speed_index)
                sim_interval_ms = SIM_SPEED_LEVELS[sim_speed_index][1]
                last_step_time = pygame.time.get_ticks()

        now = pygame.time.get_ticks()
        if game_state == GAME_RUNNING and simulator and \
           now - last_step_time >= sim_interval_ms:
            simulator.step()
            if simulator.winner:
                game_state = GAME_FINISHED
            last_step_time = now

        if game_state == GAME_DEPLOYMENT:
            renderer.render_deployment(battlefield, deployment.display_units(), deployment)
        elif simulator:
            renderer.render(simulator, game_state, sim_speed_index)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


def handle_deployment_event(event, deployment, battlefield, simulator,
                            game_state, running=True):
    action = None
    if event.type == pygame.KEYDOWN:
        action = deployment.handle_key(event.key, getattr(event, "unicode", ""))

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


def handle_runtime_key(key, simulator, game_state, deployment, battlefield,
                       sim_speed_index):
    if key == pygame.K_SPACE:
        if game_state == GAME_RUNNING:
            game_state = GAME_PAUSED
        elif game_state == GAME_PAUSED:
            game_state = GAME_RUNNING
    elif key == pygame.K_s and simulator and \
            game_state in (GAME_RUNNING, GAME_PAUSED, GAME_FINISHED):
        simulator.step()
        game_state = GAME_FINISHED if simulator.winner else GAME_PAUSED
    elif key == pygame.K_f:
        sim_speed_index = (sim_speed_index + 1) % len(SIM_SPEED_LEVELS)
    elif key == pygame.K_k and simulator:
        simulator.show_wrecks = not simulator.show_wrecks
    elif key == pygame.K_r:
        deployment, battlefield = create_deployment()
        simulator = None
        game_state = GAME_DEPLOYMENT
    return simulator, game_state, deployment, battlefield, sim_speed_index


if __name__ == "__main__":
    main()
