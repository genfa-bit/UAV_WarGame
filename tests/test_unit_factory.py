import pytest

from core.unit_factory import UnitFactory
from core.units import CommandNode, GroundVehicle, MissileVehicle, ScoutDrone, StrikeDrone


def _unit_data(unit_type: str) -> dict:
    return {
        "id": f"test-{unit_type}",
        "name": unit_type,
        "team": "red",
        "unit_type": unit_type,
        "x": 10,
        "y": 20,
    }


def test_create_scout_drone():
    assert isinstance(UnitFactory.create(_unit_data("scout_drone")), ScoutDrone)


def test_create_strike_drone():
    assert isinstance(UnitFactory.create(_unit_data("strike_drone")), StrikeDrone)


def test_create_ground_vehicle():
    assert isinstance(UnitFactory.create(_unit_data("ground_vehicle")), GroundVehicle)


def test_create_missile_vehicle():
    assert isinstance(UnitFactory.create(_unit_data("missile_vehicle")), MissileVehicle)


def test_create_command_node():
    assert isinstance(UnitFactory.create(_unit_data("command_node")), CommandNode)


def test_unknown_unit_type_raises_error():
    with pytest.raises(ValueError, match="未知 unit_type"):
        UnitFactory.create(_unit_data("unknown_unit"))
