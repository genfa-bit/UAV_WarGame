from core.battlefield import Battlefield, Obstacle
from core.deployment import DeploymentManager
from core.units import CommandNode, GroundVehicle, ScoutDrone


def _manager() -> DeploymentManager:
    battlefield = Battlefield(200, 200, [Obstacle(x=50, y=50, width=40, height=40)])
    return DeploymentManager(battlefield, [])


def test_can_place_scout_drone_at_valid_position():
    manager = _manager()
    manager.selected_unit_type = "scout_drone"

    assert manager._place_unit_at(20, 20)
    assert isinstance(manager.deploy_units[0], ScoutDrone)


def test_can_place_ground_vehicle_at_valid_position():
    manager = _manager()
    manager.selected_unit_type = "ground_vehicle"

    assert manager._place_unit_at(20, 20)
    assert isinstance(manager.deploy_units[0], GroundVehicle)


def test_ground_vehicle_cannot_be_placed_on_obstacle():
    manager = _manager()
    manager.selected_unit_type = "ground_vehicle"

    assert not manager._place_unit_at(60, 60)
    assert manager.deploy_units == []


def test_air_unit_cannot_be_placed_on_obstacle():
    manager = _manager()
    manager.selected_unit_type = "scout_drone"

    assert not manager._place_unit_at(60, 60)
    assert manager.deploy_units == []


def test_command_node_cannot_be_placed_on_obstacle():
    manager = _manager()
    manager.selected_unit_type = "command_node"

    assert not manager._place_unit_at(60, 60)
    assert manager.deploy_units == []


def test_undo_last_unit():
    manager = _manager()
    manager._place_unit_at(20, 20)
    manager._place_unit_at(30, 30)

    manager.undo_last_unit()
    assert len(manager.deploy_units) == 1


def test_clear_map_removes_all():
    manager = _manager()
    manager._place_unit_at(20, 20)
    manager._place_unit_at(30, 30)

    manager.clear_map()
    assert manager.deploy_units == []


def test_cannot_start_without_units():
    manager = _manager()
    result = manager.finalize()
    assert not result.ok


def test_cannot_start_with_only_one_team():
    manager = _manager()
    manager._place_unit_at(20, 20)
    result = manager.finalize()
    assert not result.ok


def test_can_start_when_red_and_blue_have_units():
    manager = _manager()
    manager.selected_team = "red"
    manager._place_unit_at(20, 20)
    manager.selected_team = "blue"
    manager.selected_unit_type = "command_node"
    manager._place_unit_at(150, 150)

    result = manager.finalize()
    assert result.ok
    assert len(result.units) == 2
    assert isinstance(result.units[1], CommandNode)
