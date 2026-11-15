"""RDMA 与 Simulator/EngagementState 的集成回归。"""

from __future__ import annotations

from core.battlefield import Battlefield
from core.engagement import EngagementPhase
from core.simulator import Simulator
from core.units import CommandNode, GroundVehicle, StrikeDrone


def _unit(unit_id, team, x, **kwargs):
    defaults = dict(
        id=unit_id, name=unit_id, team=team, x=x, y=300, speed=0,
        reaction_delay=5, attack_cooldown=2,
    )
    defaults.update(kwargs)
    return StrikeDrone(**defaults)


def _target(unit_id, x, hp=500):
    return GroundVehicle(id=unit_id, name=unit_id, team="blue", x=x, y=300,
                         speed=0, hp=hp, max_hp=hp,
                         reaction_delay=5, attack_cooldown=5)


def test_unassigned_unit_does_not_fall_back_to_focus_or_nearest_target():
    assigned = _unit("r1", "red", 350)
    unassigned = _unit("r2", "red", 360)
    target = _target("b1", 400, hp=10)
    simulator = Simulator(Battlefield(800, 600), [assigned, unassigned, target])

    simulator.step()

    result = simulator.assignments["red"]
    assert len(result.assignments) == 1
    assert simulator.focus_targets["red"] is target
    assert simulator._assignment_mode_active("red")
    if "r1" in result.assignments:
        assert simulator._attack_target_for(unassigned) is None
        assert simulator._attack_target_for(assigned) is target
    else:
        assert simulator._attack_target_for(assigned) is None
        assert simulator._attack_target_for(unassigned) is target


def test_assignment_change_restarts_reaction_and_authorizes_new_target_only():
    red = _unit("r1", "red", 350)
    first = _target("b1", 400)
    second = _target("b2", 420)
    third = _target("b3", 440)
    simulator = Simulator(Battlefield(800, 600), [red, first, second, third])

    for _ in range(3):
        simulator.step()
    assigned_id = simulator.assignments["red"].assignments["r1"]
    assert red.engagement_state.current_target_id == assigned_id
    assert red.engagement_state.phase == EngagementPhase.REACTING
    assert simulator._attack_target_for(red) is not None

    old_target = next(unit for unit in simulator.units if unit.id == assigned_id)
    old_target.take_damage(old_target.hp)
    simulator.step()

    new_id = simulator.assignments["red"].assignments["r1"]
    assert new_id != assigned_id
    assert red.engagement_state.current_target_id == new_id
    assert red.engagement_state.phase == EngagementPhase.REACTING
    assert red.engagement_state.reaction_progress == 0

    # 当前交战目标与分配不一致时不得开火。
    other_id = next(unit.id for unit in simulator.units
                    if unit.team == "blue" and unit.id != new_id
                    and not unit.is_destroyed)
    red.engagement_state.current_target_id = other_id
    assert simulator._attack_target_for(red) is None
    red.engagement_state.current_target_id = new_id
    assert simulator._attack_target_for(red) is not None


def test_unassigned_counter_excludes_command_nodes():
    command = CommandNode(id="r_cmd", name="R-CMD", team="red", x=100, y=300,
                          speed=0)
    simulator = Simulator(Battlefield(800, 600), [command])

    statistics = simulator.status_snapshot()

    assert statistics["red_unassigned"] == 0
    assert statistics["blue_unassigned"] == 0


def test_assignment_targets_are_recomputed_from_per_unit_delivered_view():
    observer = _unit("r1", "red", 100, detect_range=180)
    receiver = _unit("r2", "red", 50, detect_range=5)
    target = _target("b1", 200)
    simulator = Simulator(Battlefield(800, 600), [observer, receiver, target])

    simulator.step()

    # 通信尚未交付：只有观察者可以获得分配。
    assert "r1" in simulator.assignments["red"].assignments
    assert "r2" not in simulator.assignments["red"].assignments
    assert simulator._attack_target_for(receiver) is None
