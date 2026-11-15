"""RDMA 分配器的角色适配、Demand 和 per-unit 可见性单元测试。"""

from __future__ import annotations

from copy import deepcopy

from config import DETECTION_TIMEOUT_STEPS, STATUS_EVADE
from core.battlefield import Battlefield, Obstacle
from core.cooperative_allocator import CooperativeAllocator
from core.engagement import EngagementPhase, EngagementState
from core.target_pool import TargetSighting
from core.unit_config_loader import get_cooperative_assignment_config
from core.units import CommandNode, GroundVehicle, ScoutDrone, StrikeDrone


def _config(**overrides):
    config = deepcopy(get_cooperative_assignment_config())
    config.setdefault("role_fit", {})
    config.update(overrides)
    return config


def _sighting(target, step=1, available_step=1):
    return TargetSighting(target, last_seen_step=step, available_step=available_step)


def test_empty_and_invalid_target_inputs_return_no_assignments():
    unit = StrikeDrone(id="r1", name="R1", team="red", x=100, y=100,
                       speed=0, reaction_delay=0, attack_cooldown=0)
    target = GroundVehicle(id="b1", name="Target", team="blue", x=200, y=100,
                           speed=0)
    allocator = CooperativeAllocator(_config())
    battlefield = Battlefield(800, 600)

    assert allocator.allocate([], [_sighting(target)], 1,
                              battlefield).assignments == {}
    assert allocator.allocate([unit], [], 1, battlefield).assignments == {}

    target.take_damage(target.hp)
    assert allocator.allocate([unit], [_sighting(target)], 1,
                              battlefield).assignments == {}


def test_stale_and_not_yet_delivered_targets_are_not_assigned():
    unit = StrikeDrone(id="r1", name="R1", team="red", x=100, y=100,
                       speed=0, reaction_delay=0, attack_cooldown=0)
    target = GroundVehicle(id="b1", name="Target", team="blue", x=200, y=100,
                           speed=0)
    allocator = CooperativeAllocator(_config())
    battlefield = Battlefield(800, 600)
    visible = {"r1": {"b1"}}

    stale = _sighting(target, step=0, available_step=0)
    assert allocator.allocate(
        [unit], [stale], DETECTION_TIMEOUT_STEPS + 1, battlefield,
        visible_ids_by_unit=visible).assignments == {}

    undelivered = _sighting(target, step=1, available_step=5)
    assert allocator.allocate(
        [unit], [undelivered], 1, battlefield).assignments == {}
    assert allocator.allocate(
        [unit], [undelivered], 5, battlefield).assignments == {"r1": "b1"}


def test_unavailable_units_are_excluded_from_new_assignments():
    target = GroundVehicle(id="b1", name="Target", team="blue", x=200, y=100,
                           speed=0)
    no_ammo = StrikeDrone(id="r1", name="NoAmmo", team="red", x=100, y=100,
                          speed=0, ammo=0, reaction_delay=0,
                          attack_cooldown=0)
    command = CommandNode(id="r2", name="Command", team="red", x=110, y=100,
                          speed=0)
    evading = StrikeDrone(id="r3", name="Evading", team="red", x=120, y=100,
                          speed=0, reaction_delay=0, attack_cooldown=0)
    evading.status = STATUS_EVADE

    result = CooperativeAllocator(_config()).allocate(
        [no_ammo, command, evading], [_sighting(target)], 1,
        Battlefield(800, 600),
        visible_ids_by_unit={unit.id: {"b1"}
                             for unit in (no_ammo, command, evading)})

    assert result.assignments == {}


def test_assignment_is_deterministic_under_input_order():
    units = [
        StrikeDrone(id="r1", name="R1", team="red", x=100, y=100, speed=0,
                    reaction_delay=0, attack_cooldown=0),
        StrikeDrone(id="r2", name="R2", team="red", x=120, y=100, speed=0,
                    reaction_delay=0, attack_cooldown=0),
    ]
    targets = [
        GroundVehicle(id="b1", name="B1", team="blue", x=300, y=100,
                      speed=0, hp=1000, max_hp=1000),
        GroundVehicle(id="b2", name="B2", team="blue", x=320, y=100,
                      speed=0, hp=1000, max_hp=1000),
    ]
    config = _config(max_assignments_per_target=1, min_assignment_bid=0.0)
    battlefield = Battlefield(800, 600)
    visible = {"r1": {"b1", "b2"}, "r2": {"b1", "b2"}}

    first = CooperativeAllocator(config).allocate(
        units, [_sighting(targets[0]), _sighting(targets[1])], 1,
        battlefield, visible_ids_by_unit=visible)
    second = CooperativeAllocator(config).allocate(
        list(reversed(units)),
        [_sighting(targets[1]), _sighting(targets[0])], 1,
        battlefield, visible_ids_by_unit=visible)

    assert first.assignments == second.assignments
    assert first.target_members == second.target_members
    assert first.demand == second.demand
    assert len(first.assignments) == 2


def test_role_fit_is_driven_by_unit_type_and_target_type_configuration():
    red = StrikeDrone(id="r1", name="R1", team="red", x=100, y=100,
                      speed=0, reaction_delay=0, attack_cooldown=0)
    air = ScoutDrone(id="b1", name="Air", team="blue", x=200, y=100, speed=0)
    ground = GroundVehicle(id="b2", name="Ground", team="blue", x=200, y=120, speed=0)

    config = _config(
        max_assignments_per_target=1,
        min_assignment_bid=0.0,
        bid_weights={"target_priority": 0.0, "role_fit": 1.0,
                     "readiness": 0.0, "freshness": 0.0, "distance_cost": 0.0},
    )
    config["role_fit"]["strike_drone"]["scout_drone"] = 0.95
    config["role_fit"]["strike_drone"]["ground_vehicle"] = 0.25
    result = CooperativeAllocator(config).allocate(
        [red], [_sighting(air), _sighting(ground)], 1, Battlefield(800, 600),
        visible_ids_by_unit={"r1": {"b1", "b2"}})
    assert result.assignments == {"r1": "b1"}

    config["role_fit"]["strike_drone"]["scout_drone"] = 0.20
    config["role_fit"]["strike_drone"]["ground_vehicle"] = 0.90
    result = CooperativeAllocator(config).allocate(
        [red], [_sighting(air), _sighting(ground)], 1, Battlefield(800, 600),
        visible_ids_by_unit={"r1": {"b1", "b2"}})
    assert result.assignments == {"r1": "b2"}


def test_can_engage_is_a_hard_constraint_but_does_not_require_attack_range():
    red = StrikeDrone(id="r1", name="R1", team="red", x=100, y=100,
                      speed=0, can_attack_air=False,
                      reaction_delay=0, attack_cooldown=0)
    air = ScoutDrone(id="b1", name="Air", team="blue", x=200, y=100, speed=0)
    ground = GroundVehicle(id="b2", name="Ground", team="blue", x=500, y=100, speed=0)

    assert red.can_engage(ground)
    assert not red.can_attack(ground)       # 超出射程但仍可分配
    assert not red.can_engage(air)          # 域限制是硬约束

    config = _config(min_assignment_bid=0.0)
    result = CooperativeAllocator(config).allocate(
        [red], [_sighting(air), _sighting(ground)], 1, Battlefield(800, 600),
        visible_ids_by_unit={"r1": {"b1", "b2"}})
    assert "b1" not in result.assignments.values()
    assert result.assignments.get("r1") == "b2"


def test_unreceived_private_recon_is_not_visible_to_teammate():
    observer = StrikeDrone(id="r1", name="Observer", team="red", x=100, y=100,
                           speed=0, reaction_delay=0, attack_cooldown=0)
    receiver = StrikeDrone(id="r2", name="Receiver", team="red", x=120, y=100,
                           speed=0, reaction_delay=0, attack_cooldown=0)
    target = GroundVehicle(id="b1", name="Target", team="blue", x=220, y=100,
                           speed=0, hp=1000, max_hp=1000)
    allocator = CooperativeAllocator(_config())
    sights = [_sighting(target)]

    result = allocator.allocate(
        [observer, receiver], sights, 1, Battlefield(800, 600),
        visible_ids_by_unit={"r1": {"b1"}, "r2": set()})
    assert result.assignments == {"r1": "b1"}

    result = allocator.allocate(
        [observer, receiver], sights, 1, Battlefield(800, 600),
        visible_ids_by_unit={"r1": {"b1"}, "r2": {"b1"}})
    assert set(result.assignments) == {"r1", "r2"}


def test_demand_uses_expected_damage_and_avoids_synchronous_overkill():
    units = [
        StrikeDrone(id=f"r{i}", name=f"R{i}", team="red", x=100 + i * 5,
                    y=100, speed=0, reaction_delay=0, attack_cooldown=0)
        for i in range(3)
    ]
    target = GroundVehicle(id="b1", name="Target", team="blue", x=200, y=100,
                           speed=0, hp=20, max_hp=20)
    result = CooperativeAllocator(_config(max_assignments_per_target=3)).allocate(
        units, [_sighting(target)], 1, Battlefield(800, 600),
        visible_ids_by_unit={unit.id: {"b1"} for unit in units})

    # 单个单位的期望伤害已超过目标血量，需求为 1，不应三人同时过杀。
    assert result.demand["b1"] == 1
    assert len(result.assignments) == 1


def test_demand_respects_attack_phase_cooldown_horizon():
    ready_one = StrikeDrone(id="r1", name="R1", team="red", x=100, y=100,
                            speed=0, reaction_delay=0, attack_cooldown=0)
    ready_two = StrikeDrone(id="r2", name="R2", team="red", x=100, y=120,
                            speed=0, reaction_delay=0, attack_cooldown=0)
    cooling = StrikeDrone(id="r3", name="R3", team="red", x=100, y=80,
                          speed=0, reaction_delay=0, attack_cooldown=50)
    cooling.engagement_state.phase = EngagementPhase.COOLDOWN
    cooling.engagement_state.cooldown_progress = 0
    cooling.engagement_state.current_target_id = "b1"
    target = GroundVehicle(id="b1", name="Target", team="blue", x=200, y=100,
                           speed=0, hp=260, max_hp=260)
    config = _config(demand_horizon_steps=10)
    battlefield = Battlefield(800, 600)

    ready_result = CooperativeAllocator(config).allocate(
        [ready_one, ready_two], [_sighting(target)], 1, battlefield,
        visible_ids_by_unit={"r1": {"b1"}, "r2": {"b1"}})
    cooling_result = CooperativeAllocator(config).allocate(
        [ready_one, cooling], [_sighting(target)], 1, battlefield,
        visible_ids_by_unit={"r1": {"b1"}, "r3": {"b1"}})

    assert ready_result.demand["b1"] == 2
    assert len(ready_result.assignments) == 2
    assert CooperativeAllocator(config)._expected_damage(
        cooling, target, battlefield) == 0
    # 冷却中的单位本窗口贡献 0 期望伤害，因此只需一名就绪单位。
    assert cooling_result.demand["b1"] == 1
    assert cooling_result.assignments == {"r1": "b1"}


def test_zero_damage_window_keeps_minimum_demand_not_all_units():
    cooling = []
    for index in range(3):
        unit = StrikeDrone(id=f"r{index}", name=f"R{index}", team="red",
                           x=100 + index * 5, y=100, speed=0,
                           reaction_delay=0, attack_cooldown=50)
        unit.engagement_state.phase = EngagementPhase.COOLDOWN
        unit.engagement_state.cooldown_progress = 0
        unit.engagement_state.current_target_id = "b1"
        cooling.append(unit)
    target = GroundVehicle(id="b1", name="Target", team="blue", x=200, y=100,
                           speed=0, hp=1000, max_hp=1000)

    result = CooperativeAllocator(_config(
        demand_horizon_steps=10, max_assignments_per_target=3)).allocate(
        cooling, [_sighting(target)], 1, Battlefield(800, 600),
        visible_ids_by_unit={unit.id: {"b1"} for unit in cooling})

    assert result.demand["b1"] == 1
    assert len(result.assignments) == 1


def test_expected_damage_reuses_distance_and_cover_factors():
    allocator = CooperativeAllocator(_config())
    target = GroundVehicle(id="b1", name="Target", team="blue", x=400, y=100,
                           speed=0)
    near = StrikeDrone(id="near", name="Near", team="red", x=350, y=100,
                       speed=0, reaction_delay=0, attack_cooldown=0)
    far = StrikeDrone(id="far", name="Far", team="red", x=100, y=100,
                      speed=0, reaction_delay=0, attack_cooldown=0)
    battlefield = Battlefield(800, 600)
    assert allocator._expected_damage(near, target, battlefield) > \
        allocator._expected_damage(far, target, battlefield)

    battlefield_with_cover = Battlefield(
        800, 600, obstacles=[Obstacle(220, 80, 20, 80)])
    assert allocator._expected_damage(far, target, battlefield_with_cover) < \
        allocator._expected_damage(far, target, battlefield)


def test_engagement_assignment_change_resets_reaction_but_preserves_cooldown():
    eng = EngagementState(reaction_delay=4, attack_cooldown=6)
    eng.on_target_spotted("old")
    eng.reaction_progress = 2
    eng.on_assignment_changed("new")
    assert eng.phase == EngagementPhase.REACTING
    assert eng.current_target_id == "new"
    assert eng.reaction_progress == 0

    eng.phase = EngagementPhase.COOLDOWN
    eng.cooldown_progress = 3
    eng.current_target_id = "old"
    eng.on_assignment_changed("new")
    assert eng.phase == EngagementPhase.COOLDOWN
    assert eng.cooldown_progress == 3
    assert eng.current_target_id is None
