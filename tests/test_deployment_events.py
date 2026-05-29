from types import SimpleNamespace

from config import DEPLOY_MANUAL, DEPLOY_PRESET, TEAM_BLUE, TEAM_RED
from core.battlefield import Battlefield, Obstacle
from core.deployment import (
    EVENT_KEYDOWN,
    EVENT_MOUSEBUTTONDOWN,
    KEY_3,
    KEY_5,
    KEY_M,
    KEY_R,
    KEY_RETURN,
    KEY_T,
    DeploymentManager,
)


def _manager() -> DeploymentManager:
    battlefield = Battlefield(200, 200, [Obstacle(x=50, y=50, width=40, height=40)])
    return DeploymentManager(battlefield, [])


def _key(key: int):
    return SimpleNamespace(type=EVENT_KEYDOWN, key=key)


def test_m_toggles_deployment_mode():
    manager = _manager()

    manager.handle_key(KEY_M, "m")

    assert manager.mode == DEPLOY_MANUAL


def test_number_keys_select_unit_type():
    manager = _manager()

    manager.handle_key(KEY_3, "3")
    assert manager.selected_unit_type == "ground_vehicle"

    manager.handle_key(KEY_5, "5")
    assert manager.selected_unit_type == "command_node"


def test_t_toggles_team():
    manager = _manager()

    manager.handle_key(KEY_T, "t")

    assert manager.selected_team == TEAM_BLUE


def test_mouse_click_places_manual_unit():
    manager = _manager()
    manager.mode = DEPLOY_MANUAL

    manager.handle_mouse_button(1, (20, 20))

    assert len(manager.manual_units) == 1


def test_manual_illegal_position_sets_error_message():
    manager = _manager()
    manager.mode = DEPLOY_MANUAL
    manager.selected_unit_type = "ground_vehicle"

    manager.handle_mouse_button(1, (60, 60))

    assert manager.manual_units == []
    assert "失败" in manager.last_message


def test_panel_click_does_not_place_unit():
    manager = _manager()
    manager.mode = DEPLOY_MANUAL

    manager.handle_mouse_button(1, (210, 20))

    assert manager.manual_units == []


def test_can_start_when_manual_red_and_blue_exist():
    manager = _manager()
    manager.mode = DEPLOY_MANUAL
    manager.selected_team = TEAM_RED
    manager.place_unit(20, 20)
    manager.selected_team = TEAM_BLUE
    manager.place_unit(150, 150)

    action = manager.handle_key(KEY_RETURN)

    assert action == "start"


def test_r_restores_preset_mode():
    manager = _manager()
    manager.mode = DEPLOY_MANUAL

    action = manager.handle_key(KEY_R, "r")

    assert action == "reset"
    assert manager.mode == DEPLOY_PRESET


def test_preset_map_click_gives_feedback_without_placing():
    manager = _manager()

    manager.handle_mouse_button(1, (20, 20))

    assert manager.manual_units == []
    assert "Preset" in manager.last_message
    assert "20" in manager.last_message
