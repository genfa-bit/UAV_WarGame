"""固定随机种子的 Baseline / RDMA 对比实验。

Baseline 表示未启用协同分配时的旧 ``focus_target`` 机制。两套实验使用
同一场景定义、同一随机种子和同一仿真步数，只在 Simulator.cooperative_enabled
上不同。

用法（在项目根目录执行）：
    python tools/cooperative_benchmark.py --seeds 5 --steps 200
    python tools/cooperative_benchmark.py --json benchmark.json
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.battlefield import Battlefield, Obstacle  # noqa: E402
from core.simulator import Simulator  # noqa: E402
from core.units import (CommandNode, GroundVehicle, MissileVehicle,  # noqa: E402
                        ScoutDrone, StrikeDrone, Unit)

OVERALLOCATION_RATIO = 1.5


def _mirrored_units(prefix: str, team: str, x_center: float) -> list[Unit]:
    """生成红蓝镜像编队；ID 前缀保证双方不会冲突。"""
    specs = [
        (StrikeDrone, "strike", x_center - 40, 220),
        (StrikeDrone, "strike2", x_center - 20, 260),
        (GroundVehicle, "ground", x_center, 300),
        (MissileVehicle, "missile", x_center - 30, 340),
        (ScoutDrone, "scout", x_center - 60, 380),
        (CommandNode, "command", 120 if team == "red" else 680, 300),
    ]
    units: list[Unit] = []
    for cls, suffix, x, y in specs:
        units.append(cls(id=f"{prefix}_{suffix}", name=f"{prefix}-{suffix}",
                         team=team, x=x, y=y))
    return units


def build_scenario(name: str) -> tuple[Battlefield, list[Unit]]:
    obstacles = [
        Obstacle(380, 250, 30, 90, name="中央建筑", type="building"),
        Obstacle(390, 120, 50, 40, name="北侧山地", type="mountain"),
    ]
    if name == "mirrored":
        battlefield = Battlefield(800, 600, obstacles=obstacles)
        units = _mirrored_units("red", "red", 300)
        units += _mirrored_units("blue", "blue", 500)
        return battlefield, units
    if name == "clustered":
        battlefield = Battlefield(800, 600, obstacles=obstacles)
        units = _mirrored_units("red", "red", 280)
        blue = []
        for index, (x, y) in enumerate([(500, 260), (520, 300), (500, 340),
                                       (540, 280), (540, 320)]):
            blue.append(GroundVehicle(id=f"blue_ground{index}",
                                      name=f"blue-ground{index}",
                                      team="blue", x=x, y=y))
        blue.append(CommandNode(id="blue_command", name="blue-command",
                                team="blue", x=680, y=300))
        units += blue
        return battlefield, units
    if name == "base_rush":
        # 红方缺少正面兵力，只能依靠基地战略目标打开局面；
        # 蓝方仅留一个远处单位，避免首步“无单位即判负”。
        battlefield = Battlefield(800, 600, red_base=(80, 300),
                                  blue_base=(700, 300), obstacles=[])
        units = [
            StrikeDrone(id="red_strike1", name="red-strike1", team="red",
                        x=560, y=250),
            StrikeDrone(id="red_strike2", name="red-strike2", team="red",
                        x=560, y=350),
            ScoutDrone(id="red_scout", name="red-scout", team="red",
                       x=500, y=300),
            CommandNode(id="red_command", name="red-command", team="red",
                        x=120, y=300),
            GroundVehicle(id="blue_ground", name="blue-ground", team="blue",
                          x=160, y=120),
            CommandNode(id="blue_command", name="blue-command", team="blue",
                        x=680, y=120),
        ]
        return battlefield, units
    if name == "defended_base":
        # 蓝方基地有地面与导弹单位掩护，考验分配器在基地与
        # 护航单位之间的目标价值权衡。
        battlefield = Battlefield(800, 600, red_base=(80, 300),
                                  blue_base=(700, 300),
                                  obstacles=[Obstacle(420, 250, 40, 100,
                                                      name="中线建筑",
                                                      type="building")])
        units = [
            StrikeDrone(id="red_strike1", name="red-strike1", team="red",
                        x=380, y=220),
            StrikeDrone(id="red_strike2", name="red-strike2", team="red",
                        x=380, y=380),
            MissileVehicle(id="red_missile", name="red-missile", team="red",
                           x=360, y=300),
            ScoutDrone(id="red_scout", name="red-scout", team="red",
                       x=300, y=300),
            CommandNode(id="red_command", name="red-command", team="red",
                        x=120, y=300),
            GroundVehicle(id="blue_ground1", name="blue-ground1", team="blue",
                          x=640, y=250),
            GroundVehicle(id="blue_ground2", name="blue-ground2", team="blue",
                          x=640, y=350),
            MissileVehicle(id="blue_missile", name="blue-missile", team="blue",
                           x=620, y=300),
            CommandNode(id="blue_command", name="blue-command", team="blue",
                        x=680, y=120),
        ]
        return battlefield, units
    if name == "asymmetric":
        # 红方侦察与导弹组合对蓝方地面集群和基地；双方兵力与
        # 目标类型都不对称。
        battlefield = Battlefield(800, 600, red_base=(80, 300),
                                  blue_base=(700, 300), obstacles=obstacles)
        units = [
            ScoutDrone(id="red_scout", name="red-scout", team="red",
                       x=320, y=240),
            MissileVehicle(id="red_missile1", name="red-missile1", team="red",
                           x=300, y=300),
            MissileVehicle(id="red_missile2", name="red-missile2", team="red",
                           x=300, y=360),
            CommandNode(id="red_command", name="red-command", team="red",
                        x=120, y=300),
        ]
        for index, (x, y) in enumerate([(560, 260), (580, 300), (560, 340)]):
            units.append(GroundVehicle(id=f"blue_ground{index}",
                                       name=f"blue-ground{index}",
                                       team="blue", x=x, y=y))
        units.append(CommandNode(id="blue_command", name="blue-command",
                                 team="blue", x=680, y=120))
        return battlefield, units
    raise ValueError(f"未知场景: {name}")


def _is_available(unit: Unit) -> bool:
    return (not unit.is_destroyed and unit.attack_power > 0
            and unit.ammo > 0 and unit.unit_type != "command_node")


def _target_map(simulator: Simulator) -> dict[str, Unit]:
    targets = {unit.id: unit for unit in simulator.units
               if not unit.is_destroyed}
    for team in ("red", "blue"):
        base = simulator.battlefield.base_obj(team)
        if not base.is_destroyed:
            targets[base.id] = base
    return targets


def _assignment_snapshot(simulator: Simulator, cooperative: bool
                         ) -> dict[str, str]:
    """每步的“单位 → 目标”映射。

    Baseline 没有分配器，用旧规则“可见 focus，否则最近可见敌人”近似其有效
    目标；RDMA 使用真实分配结果。两者都只看该单位自己的可见集合，避免把
    未送达的共享侦察算进 Baseline 的利用率。旧路径的基地攻击不经过
    focus_target，因此 Baseline 在攻击射程内时也把敌方基地记为有效目标。
    """
    result: dict[str, str] = {}
    if cooperative:
        for team_assignments in simulator.assignments.values():
            result.update(team_assignments.assignments)
        return result
    for team in ("red", "blue"):
        focus = simulator.focus_targets.get(team)
        enemy_base = simulator.battlefield.base_obj(
            "blue" if team == "red" else "red")
        for unit in simulator.active_units(team):
            if not _is_available(unit):
                continue
            visible = simulator._visible_targets_for(unit)
            visible_ids = {target.id for target in visible}
            if focus is not None and not focus.is_destroyed and focus.id in visible_ids:
                result[unit.id] = focus.id
            elif visible:
                nearest = min(visible, key=unit.distance_to)
                result[unit.id] = nearest.id
            elif (not enemy_base.is_destroyed
                  and unit.distance_to(enemy_base) <= unit.detect_range
                  and unit.can_attack(enemy_base)):
                result[unit.id] = enemy_base.id
    return result


def _overallocation(simulator: Simulator, assignments: dict[str, str],
                    target_by_id: dict[str, Unit]) -> bool:
    expected: dict[str, float] = {}
    for unit_id, target_id in assignments.items():
        unit = next((u for u in simulator.active_units() if u.id == unit_id), None)
        target = target_by_id.get(target_id)
        if unit is None or target is None or not unit.can_engage(target):
            continue
        value = simulator.allocator._expected_damage(
            unit, target, simulator.battlefield)
        expected[target_id] = expected.get(target_id, 0.0) + value
    for target_id, damage in expected.items():
        target = target_by_id.get(target_id)
        if target is not None and damage > OVERALLOCATION_RATIO * max(1, target.hp):
            return True
    return False


def run_once(scenario: str, seed: int, cooperative: bool,
             steps: int) -> dict:
    random.seed(seed)
    battlefield, units = build_scenario(scenario)
    simulator = Simulator(battlefield, units, max_steps=steps,
                          step_duration_seconds=0.22)
    simulator.cooperative_enabled = cooperative
    if not cooperative:
        simulator._assignment_ready_step = {"red": None, "blue": None}

    allocation_times: list[float] = []
    original_allocate = simulator.allocator.allocate

    def timed_allocate(*args, **kwargs):
        started = time.perf_counter()
        result = original_allocate(*args, **kwargs)
        allocation_times.append((time.perf_counter() - started) * 1000.0)
        return result

    simulator.allocator.allocate = timed_allocate  # type: ignore[method-assign]

    bases = {team: battlefield.base_obj(team) for team in ("red", "blue")}
    initial_hp = {unit.id: unit.hp
                  for unit in simulator.units + [bases["red"], bases["blue"]]}
    initial_ammo = {unit.id: unit.ammo for unit in simulator.units}
    previous_assignments: dict[str, str] = {}
    coverage_steps = 0.0
    available_steps = 0
    assigned_steps = 0
    switch_count = 0
    overallocated_steps = 0
    target_steps = 0
    base_detection_step: dict[str, int | None] = {"red": None, "blue": None}
    base_first_assignment_step: dict[str, int | None] = {
        "red": None, "blue": None}
    base_assigned_unit_steps = 0

    with contextlib.redirect_stdout(io.StringIO()):
        while simulator.winner is None and simulator.time_step < steps:
            simulator.step()
            active = simulator.active_units()
            target_by_id = _target_map(simulator)
            assignments = _assignment_snapshot(simulator, cooperative)
            available = [unit for unit in active if _is_available(unit)]
            assigned = [unit for unit in available if unit.id in assignments
                        and assignments[unit.id] in target_by_id]
            available_steps += len(available)
            assigned_steps += len(assigned)
            coverage_steps += len(set(assignments.values()))
            if assignments:
                target_steps += 1
                if _overallocation(simulator, assignments, target_by_id):
                    overallocated_steps += 1
            for team in ("red", "blue"):
                enemy_base = bases["blue" if team == "red" else "red"]
                if base_detection_step[team] is None:
                    if cooperative:
                        known = any(simulator._base_visible_to(unit)
                                    for unit in simulator.active_units(team))
                    else:
                        known = any(
                            unit.distance_to(enemy_base) <= unit.detect_range
                            for unit in simulator.active_units(team))
                    if known:
                        base_detection_step[team] = simulator.time_step
                base_assigned = [
                    unit_id for unit_id, target_id in assignments.items()
                    if target_id == enemy_base.id]
                if base_assigned:
                    base_assigned_unit_steps += len(base_assigned)
                    if base_first_assignment_step[team] is None:
                        base_first_assignment_step[team] = simulator.time_step
            for unit_id, target_id in assignments.items():
                previous = previous_assignments.get(unit_id)
                if previous is not None and previous != target_id:
                    switch_count += 1
            previous_assignments = assignments

    hits = simulator.hit_count
    total_damage = simulator.total_damage
    destroyed = simulator.destroyed_count
    ammo_spent = sum(initial_ammo.get(unit.id, unit.ammo) - unit.ammo
                     for unit in simulator.units)
    damage_by_target: dict[str, int] = {}
    for row in simulator.records:
        if row.get("category") == "combat" and row.get("event") == "hit":
            target_id = row.get("target_id")
            damage_by_target[target_id] = (damage_by_target.get(target_id, 0)
                                           + int(row.get("damage", 0)))
    destroyed_ids = {row["unit_id"] for row in simulator.destroyed_units}
    overkill_unit = 0
    overkill_base = 0
    for target_id, start_hp in initial_hp.items():
        if target_id not in destroyed_ids:
            continue
        excess = max(0, damage_by_target.get(target_id, 0) - start_hp)
        if target_id in ("red_base", "blue_base"):
            overkill_base += excess
        else:
            overkill_unit += excess
    overkill = overkill_unit + overkill_base

    return {
        "scenario": scenario,
        "seed": seed,
        "variant": "rdma" if cooperative else "baseline",
        "winner": simulator.winner,
        "finish_reason": simulator.finish_reason,
        "steps": simulator.time_step,
        "red_remaining": simulator.remaining_count("red"),
        "blue_remaining": simulator.remaining_count("blue"),
        "red_destroyed": destroyed["red"],
        "blue_destroyed": destroyed["blue"],
        "red_kills": simulator.kill_count["red"],
        "blue_kills": simulator.kill_count["blue"],
        "red_attacks": simulator.attack_count["red"],
        "blue_attacks": simulator.attack_count["blue"],
        "red_hits": hits["red"],
        "blue_hits": hits["blue"],
        "red_damage": total_damage["red"],
        "blue_damage": total_damage["blue"],
        "red_base_hp": bases["blue"].hp,
        "blue_base_hp": bases["red"].hp,
        "red_base_destroyed": bases["blue"].is_destroyed,
        "blue_base_destroyed": bases["red"].is_destroyed,
        "red_base_damage": damage_by_target.get("blue_base", 0),
        "blue_base_damage": damage_by_target.get("red_base", 0),
        "red_base_detection_step": base_detection_step["red"],
        "blue_base_detection_step": base_detection_step["blue"],
        "red_base_first_assignment_step": base_first_assignment_step["red"],
        "blue_base_first_assignment_step": base_first_assignment_step["blue"],
        "base_assignment_rate": (base_assigned_unit_steps
                                 / max(1, available_steps)),
        "ammo_spent": ammo_spent,
        "overkill": overkill,
        "unit_overkill": overkill_unit,
        "base_overkill": overkill_base,
        "target_coverage": coverage_steps / max(1, simulator.time_step),
        "unit_utilization": assigned_steps / max(1, available_steps),
        "overallocation_rate": overallocated_steps / max(1, target_steps),
        "switches_per_100_steps": (switch_count / max(1, available_steps)) * 100.0,
        "allocation_ms": (statistics.mean(allocation_times)
                          if allocation_times else 0.0),
        "allocation_calls": len(allocation_times),
    }


def _mean_known(values: list[int | None]) -> float | None:
    known = [value for value in values if value is not None]
    return statistics.mean(known) if known else None


def _aggregate(runs: list[dict]) -> dict:
    games = len(runs)
    return {
        "games": games,
        "red_win_rate": sum(run["winner"] == "red" for run in runs) / games,
        "blue_win_rate": sum(run["winner"] == "blue" for run in runs) / games,
        "draw_rate": sum(run["winner"] == "draw" for run in runs) / games,
        "avg_steps": statistics.mean(run["steps"] for run in runs),
        "avg_target_coverage": statistics.mean(run["target_coverage"] for run in runs),
        "avg_unit_utilization": statistics.mean(run["unit_utilization"] for run in runs),
        "avg_overallocation_rate": statistics.mean(run["overallocation_rate"]
                                                   for run in runs),
        "avg_switches_per_100_steps": statistics.mean(
            run["switches_per_100_steps"] for run in runs),
        "avg_allocation_ms": statistics.mean(run["allocation_ms"] for run in runs),
        "avg_ammo_spent": statistics.mean(run["ammo_spent"] for run in runs),
        "avg_base_assignment_rate": statistics.mean(
            run["base_assignment_rate"] for run in runs),
        "avg_red_base_detection_step": _mean_known(
            [run["red_base_detection_step"] for run in runs]),
        "avg_blue_base_detection_step": _mean_known(
            [run["blue_base_detection_step"] for run in runs]),
        "avg_red_base_first_assignment_step": _mean_known(
            [run["red_base_first_assignment_step"] for run in runs]),
        "avg_blue_base_first_assignment_step": _mean_known(
            [run["blue_base_first_assignment_step"] for run in runs]),
        "total_overkill": sum(run["overkill"] for run in runs),
        "total_unit_overkill": sum(run["unit_overkill"] for run in runs),
        "total_base_overkill": sum(run["base_overkill"] for run in runs),
        "total_red_base_damage": sum(run["red_base_damage"] for run in runs),
        "total_blue_base_damage": sum(run["blue_base_damage"] for run in runs),
        "red_base_destroyed": sum(run["red_base_destroyed"] for run in runs),
        "blue_base_destroyed": sum(run["blue_base_destroyed"] for run in runs),
        "total_red_kills": sum(run["red_kills"] for run in runs),
        "total_blue_kills": sum(run["blue_kills"] for run in runs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baseline / RDMA 固定种子对比实验")
    parser.add_argument("--scenario",
                        choices=("mirrored", "clustered", "base_rush",
                                 "defended_base", "asymmetric", "all"),
                        default="all")
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--steps", type=int, default=200)
    parser.add_argument("--json", type=Path, default=None,
                        help="把逐局与汇总结果写入 JSON 文件")
    args = parser.parse_args(argv)

    scenarios = (("mirrored", "clustered", "base_rush", "defended_base",
                  "asymmetric") if args.scenario == "all" else (args.scenario,))
    all_runs: list[dict] = []
    output = {}
    for scenario in scenarios:
        scenario_output = {}
        for variant, cooperative in (("baseline", False), ("rdma", True)):
            runs = [run_once(scenario, seed, cooperative, args.steps)
                    for seed in range(1, args.seeds + 1)]
            all_runs.extend(runs)
            scenario_output[variant] = {
                "aggregate": _aggregate(runs),
                "runs": runs,
            }
        output[scenario] = scenario_output

    for scenario in scenarios:
        print(f"\n场景 {scenario}（{args.seeds} 个固定种子，≤{args.steps} 步）")
        print(f"{'指标':<24}{'Baseline':>12}{'RDMA':>12}")
        baseline = output[scenario]["baseline"]["aggregate"]
        rdma = output[scenario]["rdma"]["aggregate"]
        rows = [
            ("红方胜率", "red_win_rate", "{:.0%}"),
            ("蓝方胜率", "blue_win_rate", "{:.0%}"),
            ("平局率", "draw_rate", "{:.0%}"),
            ("平均结束步数", "avg_steps", "{:.1f}"),
            ("目标覆盖数", "avg_target_coverage", "{:.2f}"),
            ("单位任务利用率", "avg_unit_utilization", "{:.1%}"),
            ("基地分配单位步占比", "avg_base_assignment_rate", "{:.1%}"),
            ("过度分配率", "avg_overallocation_rate", "{:.1%}"),
            ("每百单位步切换", "avg_switches_per_100_steps", "{:.2f}"),
            ("平均分配耗时(ms)", "avg_allocation_ms", "{:.3f}"),
            ("平均弹药消耗", "avg_ammo_spent", "{:.1f}"),
            ("红方发现蓝基地步", "avg_red_base_detection_step", "{:.1f}"),
            ("红方首次分配基地步", "avg_red_base_first_assignment_step", "{:.1f}"),
            ("蓝方发现红基地步", "avg_blue_base_detection_step", "{:.1f}"),
            ("蓝方首次分配基地步", "avg_blue_base_first_assignment_step", "{:.1f}"),
            ("红方对蓝基地伤害", "total_red_base_damage", "{:.0f}"),
            ("蓝方对红基地伤害", "total_blue_base_damage", "{:.0f}"),
            ("蓝基地被摧毁局数", "blue_base_destroyed", "{:.0f}"),
            ("红基地被摧毁局数", "red_base_destroyed", "{:.0f}"),
            ("累计单位超杀", "total_unit_overkill", "{:.0f}"),
            ("累计基地超杀", "total_base_overkill", "{:.0f}"),
            ("累计超杀伤害", "total_overkill", "{:.0f}"),
        ]
        for label, key, fmt in rows:
            values = []
            for aggregate in (baseline, rdma):
                value = aggregate[key]
                values.append("-" if value is None else fmt.format(value))
            print(f"{label:<24}{values[0]:>12}{values[1]:>12}")

    payload = {
        "seeds": args.seeds,
        "max_steps": args.steps,
        "scenarios": output,
        "all_runs": all_runs,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"\n已写入 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
