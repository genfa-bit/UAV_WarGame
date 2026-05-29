from config import GAME_DEPLOYMENT, GAME_FINISHED, GAME_PAUSED, GAME_RUNNING
from main import create_deployment, handle_deployment_event, handle_runtime_key, pygame


def _key(key: int):
    return pygame.event.Event(pygame.KEYDOWN, key=key)


def test_initial_state_is_deployment():
    assert GAME_DEPLOYMENT == "deployment"


def test_preset_enter_starts_running():
    deployment, battlefield = create_deployment()

    simulator, state, deployment, battlefield, running = handle_deployment_event(
        _key(pygame.K_RETURN),
        deployment,
        battlefield,
        None,
        GAME_DEPLOYMENT,
    )

    assert running
    assert state == GAME_RUNNING
    assert simulator is not None
    assert simulator.time_step == 0


def test_deployment_event_m_switches_manual_mode():
    deployment, battlefield = create_deployment()

    simulator, state, deployment, battlefield, running = handle_deployment_event(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_m, unicode="m"),
        deployment,
        battlefield,
        None,
        GAME_DEPLOYMENT,
    )

    assert running
    assert state == GAME_DEPLOYMENT
    assert deployment.mode_label == "Manual"


def test_running_space_pauses():
    deployment, battlefield = create_deployment()

    simulator, state, deployment, battlefield = handle_runtime_key(
        pygame.K_SPACE,
        None,
        GAME_RUNNING,
        deployment,
        battlefield,
    )

    assert state == GAME_PAUSED


def test_paused_space_resumes():
    deployment, battlefield = create_deployment()

    simulator, state, deployment, battlefield = handle_runtime_key(
        pygame.K_SPACE,
        None,
        GAME_PAUSED,
        deployment,
        battlefield,
    )

    assert state == GAME_RUNNING


def test_r_returns_to_deployment_from_running():
    deployment, battlefield = create_deployment()

    simulator, state, deployment, battlefield = handle_runtime_key(
        pygame.K_r,
        None,
        GAME_RUNNING,
        deployment,
        battlefield,
    )

    assert state == GAME_DEPLOYMENT
    assert simulator is None


def test_finished_r_returns_to_deployment():
    deployment, battlefield = create_deployment()

    simulator, state, deployment, battlefield = handle_runtime_key(
        pygame.K_r,
        None,
        GAME_FINISHED,
        deployment,
        battlefield,
    )

    assert state == GAME_DEPLOYMENT
    assert simulator is None
