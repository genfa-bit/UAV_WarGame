from config import STATUS_ATTACK, STATUS_DESTROYED, STATUS_MOVE, STATUS_SCOUT
from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import GroundVehicle, ScoutDrone, StrikeDrone


def test_destroyed_state_cannot_act():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100, hp=0)
    blue = GroundVehicle(id="b1", name="Blue vehicle", team="blue", x=200, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert red.status == STATUS_DESTROYED
    assert (red.x, red.y) == (100, 100)


def test_target_in_attack_range_enters_attack_state():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="Blue scout", team="blue", x=170, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert red.status == STATUS_ATTACK


def test_target_outside_attack_range_enters_move_state():
    red = StrikeDrone(id="r1", name="Red striker", team="red", x=100, y=100)
    blue = GroundVehicle(id="b1", name="Blue vehicle", team="blue", x=300, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])
    simulator.red_detected_targets["b1"] = blue

    simulator.step()

    assert red.status == STATUS_MOVE


def test_no_target_enters_move_state():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    simulator = Simulator(Battlefield(800, 600), [red])

    simulator.step()

    # 无敌人时向敌方基地方向机动
    assert red.status == STATUS_MOVE
