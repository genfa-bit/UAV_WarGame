from config import DEPLOY_MANUAL
from core.battlefield import Battlefield, Obstacle
from core.deployment import DeploymentManager
from core.units import CommandNode, GroundVehicle, ScoutDrone


def _manager() -> DeploymentManager:
    battlefield = Battlefield(200, 200, [Obstacle(x=50, y=50, width=40, height=40)])
    manager = DeploymentManager(battlefield, [])
    manager.mode = DEPLOY_MANUAL
    return manager


def test_can_place_scout_drone_at_valid_position():
    manager = _manager()
    manager.select_unit_type("scout_drone")

    assert manager.place_unit(20, 20)
    assert isinstance(manager.manual_units[0], ScoutDrone)


def test_can_place_ground_vehicle_at_valid_position():
    manager = _manager()
    manager.select_unit_type("ground_vehicle")

    assert manager.place_unit(20, 20)
    assert isinstance(manager.manual_units[0], GroundVehicle)


def test_ground_vehicle_cannot_be_placed_on_obstacle():
    manager = _manager()
    manager.select_unit_type("ground_vehicle")

    assert not manager.place_unit(60, 60)
    assert manager.manual_units == []


def test_air_unit_can_be_placed_above_obstacle():
    manager = _manager()
    manager.select_unit_type("scout_drone")

    # 空中单位可以在障碍物上方部署
    assert manager.place_unit(60, 60)
    assert len(manager.manual_units) == 1


def test_command_node_cannot_be_placed_on_obstacle():
    manager = _manager()
    manager.select_unit_type("command_node")

    assert not manager.place_unit(60, 60)
    assert manager.manual_units == []


def test_undo_deployment_removes_last_unit():
    manager = _manager()
    manager.place_unit(20, 20)
    manager.place_unit(30, 30)

    assert manager.undo()
    assert len(manager.manual_units) == 1


def test_clear_deployment_removes_all_units():
    manager = _manager()
    manager.place_unit(20, 20)
    manager.place_unit(30, 30)

    manager.clear_manual()

    assert manager.manual_units == []


def test_cannot_start_without_units():
    manager = _manager()

    result = manager.finalize()

    assert not result.ok


def test_cannot_start_with_only_one_team():
    manager = _manager()
    manager.place_unit(20, 20)

    result = manager.finalize()

    assert not result.ok


def test_can_start_when_red_and_blue_have_units():
    manager = _manager()
    manager.selected_team = "red"
    manager.place_unit(20, 20)
    manager.selected_team = "blue"
    manager.select_unit_type("command_node")
    manager.place_unit(150, 150)

    result = manager.finalize()

    assert result.ok
    assert len(result.units) == 2
    assert isinstance(result.units[1], CommandNode)
