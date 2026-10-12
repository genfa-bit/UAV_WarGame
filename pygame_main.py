"""无人装备战争游戏仿真系统入口。"""

import sys
from copy import deepcopy
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
from core.map_persistence import save_scenario, user_scenario_dir
from core.scenario_loader import load_scenario
from core.simulator import Simulator


BASE_DIR = Path(__file__).resolve().parent
SCENARIO_PATH = BASE_DIR / "data" / "scenario_1.json"


def create_deployment(filepath=None) -> tuple[DeploymentManager, object]:
    path = Path(filepath) if filepath is not None else SCENARIO_PATH
    battlefield, preset_units = load_scenario(path)
    deployment = DeploymentManager(battlefield, preset_units)
    deployment._workflow_initial = deepcopy((battlefield, preset_units))
    deployment._workflow_save_path = None if filepath is None else path
    return deployment, battlefield


def _load_user_deployment(deployment, battlefield):
    path = getattr(deployment, "_workflow_save_path", None) or user_scenario_dir() / "saved_map.json"
    try:
        loaded_deployment, loaded_battlefield = create_deployment(path)
    except Exception as exc:
        deployment.last_message = f"加载失败：{exc}"
        return deployment, battlefield, False
    loaded_deployment.last_message = f"地图已加载：{path.name}"
    return loaded_deployment, loaded_battlefield, True


def _reset_deployment(deployment, battlefield, *, runtime=False):
    baseline = getattr(deployment, "_workflow_run", None) if runtime else None
    baseline = baseline or getattr(deployment, "_workflow_initial", None)
    if baseline is None:
        return create_deployment()
    restored_battlefield, units = deepcopy(baseline)
    restored = DeploymentManager(restored_battlefield, units)
    restored._workflow_initial = deepcopy(getattr(deployment, "_workflow_initial", baseline))
    restored._workflow_save_path = getattr(deployment, "_workflow_save_path", None)
    restored.last_message = "已返回部署阶段，可修改部署后再次运行"
    return restored, restored_battlefield


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
                        filepath = getattr(deployment, "_workflow_save_path", None) or user_scenario_dir() / "saved_map.json"
                        try:
                            save_scenario(battlefield, deployment.display_units(), filepath)
                            deployment._workflow_save_path = filepath
                            deployment.last_message = f"地图保存成功: {filepath.name}"
                        except Exception as e:
                            deployment.last_message = f"保存失败: {e}"
                    elif event.key == pygame.K_l and not ctrl_held:
                        deployment, battlefield, loaded = _load_user_deployment(deployment, battlefield)
                        if loaded:
                            simulator = None
                            game_state = GAME_DEPLOYMENT
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
        deployment, battlefield = _reset_deployment(deployment, battlefield)
        simulator = None
        game_state = GAME_DEPLOYMENT
    elif action == "start":
        result = deployment.finalize()
        if result.ok:
            deployment._workflow_run = deepcopy((battlefield, result.units))
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
            game_state in (GAME_RUNNING, GAME_PAUSED):
        simulator.step()
        game_state = GAME_FINISHED if simulator.winner else GAME_PAUSED
    elif key == pygame.K_f:
        sim_speed_index = (sim_speed_index + 1) % len(SIM_SPEED_LEVELS)
    elif key == pygame.K_k and simulator:
        simulator.show_wrecks = not simulator.show_wrecks
    elif key == pygame.K_r:
        deployment, battlefield = _reset_deployment(deployment, battlefield, runtime=True)
        simulator = None
        game_state = GAME_DEPLOYMENT
    elif key == pygame.K_l:
        deployment, battlefield, loaded = _load_user_deployment(deployment, battlefield)
        if loaded:
            simulator = None
            game_state = GAME_DEPLOYMENT
    return simulator, game_state, deployment, battlefield, sim_speed_index


if __name__ == "__main__":
    main()
