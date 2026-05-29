from config import DETECTION_TIMEOUT_STEPS
from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import GroundVehicle, ScoutDrone


def test_detected_target_is_added_to_pool_with_last_seen_step():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="Blue scout", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert "b1" in simulator.red_detected_targets
    assert simulator.red_detected_targets.last_seen_step("b1") == simulator.time_step


def test_destroyed_target_is_removed_from_detection_pool():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    blue = GroundVehicle(id="b1", name="Blue vehicle", team="blue", x=500, y=100, hp=0)
    simulator = Simulator(Battlefield(800, 600), [red, blue])
    simulator.red_detected_targets["b1"] = blue

    simulator.step()

    assert "b1" not in simulator.red_detected_targets


def test_stale_target_is_removed_from_detection_pool():
    red = ScoutDrone(id="r1", name="Red scout", team="red", x=100, y=100)
    blue = GroundVehicle(id="b1", name="Blue vehicle", team="blue", x=700, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])
    simulator.red_detected_targets.sight(blue, step=0)
    simulator.time_step = DETECTION_TIMEOUT_STEPS

    simulator.step()

    assert "b1" not in simulator.red_detected_targets
