"""HTCS 与 Simulator 的集成测试。

覆盖模式开关、火力计划安装、火力门/火力纪律、BDA/再攻击、SEAD 压制、
机会射击、分布式降级与滚动波次重规划。所有命中判定都被固定，断言只依赖
确定性逻辑。
"""

from __future__ import annotations

from copy import deepcopy

from core.battlefield import Battlefield
from core.engagement import EngagementPhase
from core.simulator import Simulator
from core.time_coordination import FirePlan, FireWindow
from core.unit_config_loader import get_cooperative_assignment_config
from core.units import CommandNode, GroundVehicle, StrikeDrone


def _config(mode="htcs", **htcs_overrides):
    config = deepcopy(get_cooperative_assignment_config())
    config["mode"] = mode
    config["htcs"].update(htcs_overrides)
    return config


def _drone(uid="r1", team="red", x=300.0, y=300.0, *, ammo=7,
           reaction_delay=0, attack_cooldown=0):
    return StrikeDrone(id=uid, name=uid, team=team, x=x, y=y, speed=0,
                       ammo=ammo, reaction_delay=reaction_delay,
                       attack_cooldown=attack_cooldown)


def _target(uid="b1", x=400.0, hp=500):
    return GroundVehicle(id=uid, name=uid, team="blue", x=x, y=300.0,
                         speed=0, hp=hp, max_hp=hp, reaction_delay=5,
                         attack_cooldown=5)


def _sim(units, mode="htcs", **htcs_overrides):
    return Simulator(Battlefield(800, 600), units,
                     cooperative_config=_config(mode, **htcs_overrides))


def _events(simulator, name):
    return [row for row in simulator.records if row.get("event") == name]


# ── 模式开关 ────────────────────────────────────────────────────
def test_rdma_v2_mode_leaves_htcs_dormant():
    simulator = _sim([_drone(), _target()], mode="rdma_v2")
    assert simulator.htcs_enabled is False
    assert simulator.strike_planner is None
    simulator.step()
    assert simulator.fire_plans == {"red": {}, "blue": {}}
    assert simulator.assignments["red"].assignments


def test_htcs_mode_builds_planner_and_ledger():
    simulator = _sim([_drone(), _target()])
    assert simulator.htcs_enabled is True
    assert simulator.strike_planner is not None
    simulator.step()
    assert simulator.fire_plans["red"]["r1"]


def test_disabled_cooperation_also_disables_htcs():
    config = _config()
    config["enabled"] = False
    simulator = Simulator(Battlefield(800, 600), [_drone(), _target()],
                          cooperative_config=config)
    assert simulator.htcs_enabled is False


# ── 火力计划与 TOT ──────────────────────────────────────────────
def test_fire_plans_target_the_assigned_target():
    simulator = _sim([_drone(), _target()])
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    assert plans
    assert plans[0].target_id == "b1"
    assert plans[0].tot >= simulator.time_step


def test_fire_plan_shot_count_matches_task_bundle():
    # 反应中单位本步不会开火，因此计划列表完整保留。
    simulator = _sim([_drone(reaction_delay=5, attack_cooldown=2), _target()])
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    task = simulator.assignments["red"].tasks[plans[0].task_id]
    assert len(plans) == task.shots["r1"]


def test_fire_plan_shot_tots_are_staggered_by_shooting_cycle():
    unit = _drone(reaction_delay=2, attack_cooldown=0)
    simulator = _sim([unit, _target()])
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    assert len(plans) >= 2
    cycle = unit.reaction_delay + unit.attack_cooldown + 1
    assert plans[1].tot == plans[0].tot + cycle


def test_unit_holds_fire_before_the_fire_window():
    simulator = _sim([_drone(), _target()])
    simulator.step()
    plans = simulator.fire_plans["red"]["r1"]
    plans[0] = FirePlan(task_id=plans[0].task_id, target_id=plans[0].target_id,
                        wave=plans[0].wave, role="strike",
                        window=FireWindow(tot=50, tolerance=1, late=3))
    red = simulator.units[0]
    red.engagement_state.phase = EngagementPhase.ATTACK
    simulator.combat.clear_intents()
    simulator._attack_phase()
    assert not [i for i in simulator.combat._intents
                if i.attacker_id == "r1"]


def test_unit_fires_inside_the_fire_window(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.0)
    target = _target()
    simulator = _sim([_drone(), target])
    simulator.step()
    assert target.hp < 500


# ── 火力纪律 ────────────────────────────────────────────────────
def test_fire_discipline_blocks_saturated_target():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.damage_ledger.reserve("r1", "b1", 500)
    assert simulator._htcs_fire_allowed(red, target) is False
    assert _events(simulator, "fire_discipline_hold")


def test_fire_discipline_hold_is_logged_once_per_wave():
    red, target = _drone(), _target()
    simulator = _sim([red, target])
    simulator.damage_ledger.reserve("r1", "b1", 500)
    simulator._htcs_fire_allowed(red, target)
    simulator._htcs_fire_allowed(red, target)
    assert len(_events(simulator, "fire_discipline_hold")) == 1


def test_fire_discipline_can_be_disabled():
    red, target = _drone(), _target()
    simulator = _sim([red, target], fire_discipline=False)
    simulator.damage_ledger.reserve("r1", "b1", 500)
    assert simulator._htcs_fire_allowed(red, target) is True


def test_fire_discipline_allows_fire_below_the_overkill_ratio():
    red, target = _drone(), _target()
    simulator = _sim([red, target], overkill_fire_ratio=2.0)
    simulator.damage_ledger.reserve("r1", "b1", 400)
    assert simulator._htcs_fire_allowed(red, target) is True


def test_fire_discipline_blocks_a_crossing_shot():
    # 只剩 40 点血、已预约 10 点；再加 34 点会越过阈值（10 本身未饱和）。
    red, target = _drone(), _target(hp=40)
    simulator = _sim([red, target])
    simulator.damage_ledger.reserve("r2", "b1", 10)
    assert simulator._htcs_fire_allowed(
        red, target, incoming=34.0) is False
    assert _events(simulator, "fire_discipline_hold")


def test_fire_discipline_allows_the_first_finisher():
    # 账本为空时，即使单发伤害远大于残血也必须允许开火。
    red, target = _drone(), _target(hp=5)
    simulator = _sim([red, target])
    assert simulator._htcs_fire_allowed(red, target, incoming=34.0) is True


# ── 迟到射击硬性拦截 ────────────────────────────────────────────
def _expired_plan() -> FirePlan:
    return FirePlan(task_id="b1:strike:0", target_id="b1", wave=0,
                    role="strike",
                    window=FireWindow(tot=0, tolerance=0, late=0))


def test_expired_plan_is_hard_intercepted():
    simulator = _sim([_drone(), _target()])
    simulator.step()
    simulator.fire_plans["red"]["r1"] = [_expired_plan()]
    red = simulator.units[0]
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.engagement_state.current_target_id = "b1"
    simulator.combat.clear_intents()
    simulator._attack_phase()
    assert not [i for i in simulator.combat._intents
                if i.attacker_id == "r1"]
    missed = _events(simulator, "fire_window_missed")
    assert missed and missed[0]["target_id"] == "b1"
    assert not simulator.fire_plans["red"]["r1"]


def test_late_fire_hold_blocks_opportunity_fire():
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target])
    simulator._htcs_target_hold[("r1", "b1")] = simulator.time_step + 5
    assert simulator._htcs_opportunity_target(red, [target]) is None


def test_late_fire_hold_expires():
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target])
    simulator._htcs_target_hold[("r1", "b1")] = simulator.time_step - 1
    assert simulator._htcs_opportunity_target(red, [target]) is target


def test_lenient_policy_keeps_legacy_late_fire(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.0)
    simulator = _sim([_drone(), _target()], late_fire_policy="lenient")
    simulator.step()
    simulator.fire_plans["red"]["r1"] = [_expired_plan()]
    red = simulator.units[0]
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.engagement_state.current_target_id = "b1"
    simulator.combat.clear_intents()
    simulator._attack_phase()
    assert [i for i in simulator.combat._intents
            if i.attacker_id == "r1"]
    assert not _events(simulator, "fire_window_missed")


# ── 名义伤害与过杀记录 ──────────────────────────────────────────
def test_resolve_records_nominal_damage_and_overkill(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.0)
    red, target = _drone(), _target(hp=5)
    simulator = _sim([red, target])
    simulator.combat.queue_attack(red, target, simulator.battlefield)
    simulator._resolve_attacks()
    event = simulator.attack_events[-1]
    assert event.nominal_damage > 5
    assert event.damage == 5
    assert event.overkill == event.nominal_damage - event.damage
    assert simulator.overkill_damage["red"] == event.overkill


# ── BDA 与再攻击 ────────────────────────────────────────────────
def _ready_task(simulator, team="red"):
    """返回本队第一个 ready 状态的 HTCS 任务。"""
    for task in simulator.assignments[team].tasks.values():
        if task.state == "ready":
            return task
    raise AssertionError("本步没有生成 ready 任务")


def _ready_sim(**htcs_overrides):
    """构造一个本波次能满编覆盖的目标，保证任务状态为 ready。"""
    simulator = _sim([_drone(), _target(hp=50)], **htcs_overrides)
    simulator.step()
    return simulator, _ready_task(simulator)


def test_bda_completes_task_when_target_is_destroyed():
    simulator, task = _ready_sim()
    target = simulator._entity(task.target_id)
    target.take_damage(target.hp)
    simulator._update_destroyed_stats()
    simulator._bda_phase()
    assert task.state == "done"
    completed = _events(simulator, "bda_completed")
    assert completed and completed[0]["target_id"] == task.target_id


def test_bda_flags_reattack_after_window_without_delivery():
    simulator, task = _ready_sim()
    task.late_until = -1
    task.planned_damage = 1000.0
    simulator.damage_ledger.reset()
    simulator._bda_phase()
    assert task.state == "failed"
    assert task.target_id in simulator._htcs_reattack["red"]
    assert _events(simulator, "reattack_required")


def test_bda_accepts_partial_delivery_above_the_ratio():
    simulator, task = _ready_sim(bda_delivery_ratio=0.5)
    task.late_until = -1
    task.planned_damage = 100.0
    simulator.damage_ledger.reset()
    simulator.damage_ledger.settle("ghost", task.target_id, 60)
    simulator._bda_phase()
    assert task.state == "done"
    assert not _events(simulator, "reattack_required")


def test_bda_ignores_tasks_still_inside_their_window():
    simulator, task = _ready_sim()
    before = task.state
    assert task.late_until >= simulator.time_step
    simulator._bda_phase()
    assert task.state == before


def test_bda_disabled_leaves_tasks_untouched():
    simulator, task = _ready_sim(bda_enabled=False)
    task.late_until = -1
    simulator.damage_ledger.reset()
    simulator._bda_phase()
    assert task.state == "ready"
    assert not _events(simulator, "reattack_required")


# ── 任务退役：跨波次承诺仍要被核对 ──────────────────────────────
def _replanned_sim(monkeypatch):
    """跑过一个波次边界，返回（仿真器，退役任务列表）。"""
    monkeypatch.setattr("core.combat.random.random", lambda: 1.0)
    simulator = _sim([_drone(), _target(hp=50)], wave_length_steps=3)
    simulator.step()
    assert simulator.assignments["red"].tasks
    for _ in range(3):
        simulator.step()
    return simulator, simulator._htcs_retired["red"]


def test_replanning_retires_undecided_tasks(monkeypatch):
    simulator, retired = _replanned_sim(monkeypatch)
    assert retired
    assert all(task.state not in ("done", "failed") for task in retired)


def test_retired_task_is_still_assessed(monkeypatch):
    simulator, retired = _replanned_sim(monkeypatch)
    task = retired[0]
    task.late_until = -1
    task.planned_damage = 1000.0
    simulator.damage_ledger.reset()
    simulator._bda_phase()
    assert task.state == "failed"
    assert task.target_id in simulator._htcs_reattack["red"]
    assert task not in simulator._htcs_retired["red"]


def test_retired_task_without_conclusion_is_kept(monkeypatch):
    simulator, retired = _replanned_sim(monkeypatch)
    task = retired[0]
    task.late_until = simulator.time_step + 5
    simulator._bda_phase()
    assert task.state not in ("done", "failed")
    assert task in simulator._htcs_retired["red"]


def test_destroyed_target_drops_its_retired_tasks(monkeypatch):
    simulator, retired = _replanned_sim(monkeypatch)
    task = retired[0]
    target = simulator._entity(task.target_id)
    target.take_damage(target.hp)
    simulator._update_destroyed_stats()
    simulator._bda_phase()
    assert not [row for row in simulator._htcs_retired["red"]
                if row.target_id == task.target_id]


# ── SEAD 压制 ───────────────────────────────────────────────────
def test_sead_hit_suppresses_the_target(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.0)
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target], sead_suppression_steps=3)
    simulator.combat.queue_attack(red, target, simulator.battlefield,
                                  role="sead")
    simulator._resolve_attacks()
    assert target.suppressed_until == simulator.time_step + 3
    suppressed = _events(simulator, "sead_suppressed")
    assert suppressed and suppressed[0]["target_id"] == "b1"


def test_zero_suppression_steps_does_not_apply(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 0.0)
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target], sead_suppression_steps=0)
    simulator.combat.queue_attack(red, target, simulator.battlefield,
                                  role="sead")
    simulator._resolve_attacks()
    assert target.suppressed_until == 0
    assert not _events(simulator, "sead_suppressed")


def test_suppressed_unit_is_skipped_in_attack_phase(monkeypatch):
    red, target = _drone(team="blue", x=500.0), _target(x=450.0)
    simulator = _sim([red, target])
    called: list[str] = []
    monkeypatch.setattr(simulator, "_htcs_attack_unit",
                        lambda unit: called.append(unit.id))
    red.engagement_state.phase = EngagementPhase.ATTACK
    red.suppressed_until = 10
    simulator._attack_phase()
    assert "r1" not in called


def test_unsuppressed_unit_is_processed_in_attack_phase(monkeypatch):
    red, target = _drone(team="blue", x=500.0), _target(x=450.0)
    simulator = _sim([red, target])
    called: list[str] = []
    monkeypatch.setattr(simulator, "_htcs_attack_unit",
                        lambda unit: called.append(unit.id))
    red.engagement_state.phase = EngagementPhase.ATTACK
    simulator._attack_phase()
    assert "r1" in called


# ── 机会射击 ────────────────────────────────────────────────────
def test_unassigned_unit_can_fire_at_opportunity_target():
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target])
    assert simulator._htcs_opportunity_target(red, [target]) is target


def test_opportunity_fire_skips_saturated_targets():
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target])
    simulator.damage_ledger.reserve("r1", "b1", 500)
    assert simulator._htcs_opportunity_target(red, [target]) is None


def test_opportunity_fire_requires_ammo():
    red, target = _drone(ammo=0), _target(x=350.0)
    simulator = _sim([red, target])
    assert simulator._htcs_opportunity_target(red, [target]) is None


def test_opportunity_fire_can_be_disabled():
    red, target = _drone(), _target(x=350.0)
    simulator = _sim([red, target], opportunity_fire=False)
    assert simulator._htcs_opportunity_target(red, [target]) is None


# ── 分布式降级 ──────────────────────────────────────────────────
def _fallback_scene(distributed: bool):
    command = CommandNode(id="c1", name="c1", team="red", x=100.0, y=300.0)
    connected = _drone("r1", x=150.0)
    detached = _drone("r2", x=700.0)
    enemy = _target("b1", x=120.0)
    simulator = _sim([command, connected, detached, enemy],
                     distributed_fallback=distributed)
    simulator.shared_targets["red"].sight(enemy, step=0, available_step=0)
    return simulator, connected, detached


def test_distributed_fallback_keeps_detached_units_on_local_sightings():
    simulator, connected, detached = _fallback_scene(distributed=True)
    visible = simulator._visible_target_ids_by_unit()
    assert "b1" in visible["r1"]
    assert "b1" not in visible["r2"]


def test_without_fallback_every_unit_receives_the_shared_pool():
    simulator, connected, detached = _fallback_scene(distributed=False)
    visible = simulator._visible_target_ids_by_unit()
    assert "b1" in visible["r1"]
    assert "b1" in visible["r2"]


def test_command_node_is_always_on_the_command_chain():
    simulator, _connected, _detached = _fallback_scene(distributed=True)
    assert "c1" in simulator._htcs_connected_units()


def test_no_command_node_degrades_every_unit():
    drone = _drone("r1", x=150.0)
    simulator = _sim([drone, _target("b1", x=120.0)],
                     distributed_fallback=True)
    simulator.shared_targets["red"].sight(
        simulator.units[1], step=0, available_step=0)
    visible = simulator._visible_target_ids_by_unit()
    assert "b1" not in visible["r1"]


# ── 滚动波次 ────────────────────────────────────────────────────
def test_wave_id_advances_at_each_wave_boundary(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 1.0)
    simulator = _sim([_drone(), _target()], wave_length_steps=3)
    for _ in range(3):
        simulator.step()
    assert simulator.assignments["red"].wave_id == 1
    for _ in range(3):
        simulator.step()
    assert simulator.assignments["red"].wave_id == 2


def test_rdma_v2_does_not_advance_wave_id(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 1.0)
    simulator = _sim([_drone(), _target()], mode="rdma_v2",
                     wave_length_steps=3)
    for _ in range(4):
        simulator.step()
    assert simulator.assignments["red"].wave_id == 0


def test_htcs_replans_on_the_wave_boundary(monkeypatch):
    monkeypatch.setattr("core.combat.random.random", lambda: 1.0)
    simulator = _sim([_drone(), _target()], wave_length_steps=4)
    simulator.step()
    first = simulator.assignments["red"].updated_step
    while simulator.time_step < 4:
        simulator.step()
    assert simulator.assignments["red"].updated_step == 4
    assert simulator.assignments["red"].updated_step > first
