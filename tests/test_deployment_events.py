from config import TEAM_BLUE, TEAM_RED
from core.battlefield import Battlefield, Obstacle
from core.deployment import (
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


def test_m_key_is_noop():
    manager = _manager()
    manager.handle_key(KEY_M, "m")
    # M key no longer toggles mode; just ignored
    assert manager.last_message and "未识别" in manager.last_message


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


def test_manual_illegal_position_sets_error_message():
    manager = _manager()
    manager.selected_unit_type = "ground_vehicle"

    manager._place_unit_at(60, 60)

    assert "失败" in manager.last_message


def test_can_start_when_red_and_blue_exist():
    manager = _manager()
    manager.selected_team = TEAM_RED
    manager._place_unit_at(20, 20)
    manager.selected_team = TEAM_BLUE
    manager._place_unit_at(150, 150)

    action = manager.handle_key(KEY_RETURN)

    assert action == "start"


def test_r_restores_preset():
    manager = _manager()

    action = manager.handle_key(KEY_R, "r")

    assert action == "reset"


def test_clear_map_removes_all():
    manager = _manager()
    manager.selected_team = TEAM_RED
    manager._place_unit_at(20, 20)

    manager.clear_map()

    assert manager.deploy_units == []
    assert manager.battlefield.obstacles == []


def test_mouse_cancel_discards_in_progress_obstacle_and_message():
    manager = _manager()
    manager._select_obstacle_type("building")

    manager.handle_mouse_down(1, 120, 120)
    manager.handle_mouse_motion(180, 180)
    assert manager._editor.state.creating
    assert manager.last_message

    manager.handle_mouse_cancel()
    manager.handle_mouse_up(1, 180, 180)

    obstacles = manager.battlefield.obstacles
    assert [(o.x, o.y) for o in obstacles] == [(50, 50)]
    assert not manager._editor.state.creating
    assert manager.last_message == ""


def test_mouse_cancel_blocks_placement_when_released_on_same_spot():
    manager = _manager()
    manager.selected_unit_type = "ground_vehicle"

    manager.handle_mouse_down(1, 100, 100)
    manager.handle_mouse_cancel()
    manager.handle_mouse_up(1, 100, 100)

    assert manager.deploy_units == []
