from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import CommandNode, GroundVehicle, ScoutDrone


def test_red_destroyed_blue_wins():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "blue"


def test_blue_destroyed_red_wins():
    red = GroundVehicle(id="r1", name="红无人车", team="red", x=100, y=100)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=180, y=100, hp=0)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "red"


def test_both_sides_destroyed_is_draw():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=180, y=100, hp=0)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.winner == "draw"


def test_victory_result_is_in_status_snapshot():
    red = ScoutDrone(id="r1", name="红无人机", team="red", x=100, y=100, hp=0)
    blue = GroundVehicle(id="b1", name="蓝无人车", team="blue", x=180, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue])

    simulator.step()

    assert simulator.status_snapshot()["winner"] == "blue"


def test_step_limit_verdict_prefers_stronger_remaining_force():
    # 相距 400px，首步无法互相发现/开火；超时按剩余战力判定。
    red = GroundVehicle(id="r1", name="红无人车", team="red", x=200, y=300)
    blue = ScoutDrone(id="b1", name="蓝无人机", team="blue", x=600, y=300)
    simulator = Simulator(Battlefield(800, 600), [red, blue], max_steps=1)

    simulator.step()

    assert simulator.winner == "red"
    assert simulator.finish_reason == "step_limit"
    assert any("按剩余战力判定红方获胜" in line for line in simulator.combat_logs)


def test_step_limit_verdict_uses_base_hp_when_strength_ties():
    red = CommandNode(id="r1", name="红指挥", team="red", x=100, y=100)
    blue = CommandNode(id="b1", name="蓝指挥", team="blue", x=300, y=100)
    simulator = Simulator(Battlefield(800, 600), [red, blue], max_steps=1)
    simulator.battlefield.base_obj("blue").take_damage(100)

    simulator.step()

    assert simulator.winner == "red"
    assert simulator.finish_reason == "step_limit"
