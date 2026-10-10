"""Frontend-neutral application controller and serializable snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any

from config import (
    GAME_DEPLOYMENT,
    GAME_FINISHED,
    GAME_PAUSED,
    GAME_RUNNING,
    MAX_SIMULATION_STEPS,
    OBSTACLE_TYPE_LABELS,
    SIM_SPEED_LEVELS,
    STATE_LABELS,
    STATUS_LABELS,
    TEAM_BLUE,
    TEAM_RED,
    UNIT_TYPE_LABELS,
)
from core.battlefield import obstacle_display_name
from core.deployment import DeploymentManager
from core.map_persistence import (
    BUILTIN_SCENARIOS, BUILTIN_SCENARIO_DIR, is_builtin_scenario, list_scenarios,
    load_scenario_file, save_scenario, user_scenario_dir, write_json_atomic,
)
from core.scenario_loader import load_scenario
from core.simulator import Simulator
from core.threat import team_strength
from core.terrain_catalog import MAP_STYLES, map_presentation
from core.unit_config_loader import get_unit_stats
from core.units import Unit


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIO_PATH = BASE_DIR / "data" / "scenario_1.json"
DEFAULT_SAVE_PATH = user_scenario_dir() / "saved_map.json"


@dataclass(frozen=True)
class CommandResult:
    """Result returned by commands exposed to frontends."""

    ok: bool
    message: str = ""


class SimulationController:
    """Own the application lifecycle without depending on a UI toolkit."""

    def __init__(self, scenario_path: str | Path = DEFAULT_SCENARIO_PATH):
        self.scenario_path = Path(scenario_path)
        self.battlefield = None
        self.deployment = None
        self.simulator: Simulator | None = None
        self.game_state = GAME_DEPLOYMENT
        self.speed_index = 0
        self.last_message = ""
        self.current_save_path: Path | None = None
        self.scene_id = ""
        self.scene_name = self.scenario_path.stem
        self._initial_deployment = None
        self._run_deployment = None
        battlefield, units = load_scenario(self.scenario_path)
        self._accept_scenario(battlefield, units, self.scenario_path)

    @property
    def speed_label(self) -> str:
        label = SIM_SPEED_LEVELS[self.speed_index][0]
        return "快速计算" if label == "MAX" else label

    @property
    def speed_interval_ms(self) -> int:
        return SIM_SPEED_LEVELS[self.speed_index][1]

    def reset(self) -> CommandResult:
        baseline = self._run_deployment if self.game_state != GAME_DEPLOYMENT else self._initial_deployment
        if baseline is None:
            return CommandResult(False, "没有可恢复的部署")
        self._restore_deployment(baseline)
        self._run_deployment = None
        self.last_message = "已返回部署阶段，可修改部署后再次运行"
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def _restore_deployment(self, baseline) -> None:
        battlefield, units = deepcopy(baseline)
        self.battlefield = battlefield
        self.deployment = DeploymentManager(battlefield, units)
        self.simulator = None
        self.game_state = GAME_DEPLOYMENT

    def _accept_scenario(self, battlefield, units, path: Path) -> None:
        self.scenario_path = path
        self._initial_deployment = deepcopy((battlefield, units))
        self._run_deployment = None
        self._restore_deployment(self._initial_deployment)
        preset = next(((scene_id, name) for scene_id, name, filename in BUILTIN_SCENARIOS
                       if path.resolve() == (BUILTIN_SCENARIO_DIR / filename).resolve()), None)
        self.scene_id, self.scene_name = preset or (f"user:{path.name}", path.stem)
        self.current_save_path = None if is_builtin_scenario(path) else path
        self.last_message = self.deployment.last_message

    def available_scenarios(self) -> list[dict[str, str]]:
        catalog = [{"id": scene_id, "name": name, "path": str(BUILTIN_SCENARIO_DIR / filename)}
                   for scene_id, name, filename in BUILTIN_SCENARIOS]
        catalog.extend({"id": f"user:{name}", "name": Path(name).stem,
                        "path": str(user_scenario_dir() / name)}
                       for name in list_scenarios())
        return catalog

    def select_scene(self, scene_id: str) -> CommandResult:
        scene = next((item for item in self.available_scenarios() if item["id"] == scene_id), None)
        if scene is None:
            return CommandResult(False, f"未知场景：{scene_id}")
        return self.load_map(scene["path"])

    def set_map_style(self, style: str) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段切换地图样式")
        if not isinstance(style, str) or style not in MAP_STYLES:
            self.last_message = "无效的地图样式"
            return CommandResult(False, self.last_message)
        self.battlefield.map_style = style
        self.last_message = f"地图样式：{map_presentation(style, self.battlefield.width, self.battlefield.height)['title']}"
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def restart(self) -> CommandResult:
        if self._run_deployment is not None:
            self._restore_deployment(self._run_deployment)
        return self.start()

    def start(self) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "当前不在部署阶段")
        result = self.deployment.finalize()
        self.last_message = result.message
        if not result.ok:
            return CommandResult(False, result.message)
        self._run_deployment = deepcopy((self.battlefield, result.units))
        self.simulator = Simulator(self.battlefield, result.units)
        self.game_state = GAME_RUNNING
        self.last_message = "仿真已开始"
        return CommandResult(True, self.last_message)

    def toggle_pause(self) -> CommandResult:
        if self.game_state == GAME_RUNNING:
            self.game_state = GAME_PAUSED
            self.last_message = "仿真已暂停"
            return CommandResult(True, self.last_message)
        if self.game_state == GAME_PAUSED:
            self.game_state = GAME_RUNNING
            self.last_message = "仿真继续"
            return CommandResult(True, self.last_message)
        return CommandResult(False, "当前状态不能暂停或继续")

    def step(self) -> CommandResult:
        if self.simulator is None or self.game_state not in (
            GAME_RUNNING,
            GAME_PAUSED,
        ):
            return CommandResult(False, "请先开始仿真")
        self.simulator.step()
        self.game_state = GAME_FINISHED if self.simulator.winner else GAME_PAUSED
        self.last_message = "已推进一个时间步"
        return CommandResult(True, self.last_message)

    def advance(self) -> CommandResult:
        if self.simulator is None or self.game_state != GAME_RUNNING:
            return CommandResult(False, "")
        self.simulator.step()
        if self.simulator.winner:
            self.game_state = GAME_FINISHED
            self.last_message = "仿真结束"
        return CommandResult(True, self.last_message)

    def cycle_speed(self) -> CommandResult:
        return self.set_speed((self.speed_index + 1) % len(SIM_SPEED_LEVELS))

    def set_speed(self, index: int) -> CommandResult:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(SIM_SPEED_LEVELS):
            return CommandResult(False, "无效的仿真速度")
        self.speed_index = index
        self.last_message = f"仿真速度：{self.speed_label}"
        return CommandResult(True, self.last_message)

    def toggle_wrecks(self) -> CommandResult:
        if self.simulator is None:
            return CommandResult(False, "请先开始仿真")
        self.simulator.show_wrecks = not self.simulator.show_wrecks
        label = "显示" if self.simulator.show_wrecks else "隐藏"
        self.last_message = f"已{label}残骸"
        return CommandResult(True, self.last_message)

    def toggle_team(self) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段切换阵营")
        self.deployment.toggle_team()
        return self._deployment_result(True)

    def select_unit_type(self, unit_type: str) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段选择单位")
        if unit_type not in UNIT_TYPE_LABELS:
            return CommandResult(False, f"未知兵种：{unit_type}")
        self.deployment._select_unit_type(unit_type)
        return self._deployment_result(True)

    def select_obstacle_type(self, obstacle_type: str) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段选择障碍物")
        if obstacle_type not in OBSTACLE_TYPE_LABELS:
            return CommandResult(False, f"未知障碍物：{obstacle_type}")
        self.deployment._select_obstacle_type(obstacle_type)
        return self._deployment_result(True)

    def place_at(self, x: float, y: float) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段放置单位")
        ok = self.deployment._place_unit_at(x, y)
        return self._deployment_result(ok)

    def pointer_press(self, button: int, x: float, y: float) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "")
        self.deployment.handle_mouse_down(button, x, y)
        return self._sync_editor_message()

    def pointer_move(self, x: float, y: float) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "")
        self.deployment.handle_mouse_motion(x, y)
        return self._sync_editor_message()

    def pointer_release(self, button: int, x: float, y: float) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "")
        self.deployment.handle_mouse_up(button, x, y)
        return self._sync_editor_message()

    def undo(self) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段撤销")
        self.deployment.undo_last_unit()
        return self._deployment_result(True)

    def clear_deployment(self) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段清空")
        self.deployment.clear_map()
        return self._deployment_result(True)

    def delete_selected(self) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "只能在部署阶段删除障碍物")
        ok = self.deployment.editor.delete_selected()
        return self._sync_editor_message(ok)

    def save_map(self, filepath: str | Path | None = None) -> CommandResult:
        path = Path(filepath).expanduser() if filepath is not None else self.current_save_path or user_scenario_dir() / "saved_map.json"
        try:
            if self.game_state == GAME_DEPLOYMENT:
                battlefield, units = self.battlefield, self.deployment.display_units()
            else:
                battlefield, units = self._run_deployment
            save_scenario(battlefield, units, path)
        except Exception as exc:
            self.last_message = f"保存失败：{exc}"
            return CommandResult(False, self.last_message)
        self.current_save_path = path
        self.last_message = f"地图已保存：{path.name}"
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def load_map(self, filepath: str | Path | None = None) -> CommandResult:
        path = Path(filepath).expanduser() if filepath is not None else self.current_save_path or user_scenario_dir() / "saved_map.json"
        if not path.exists():
            self.last_message = f"未找到地图：{path.name}"
            return CommandResult(False, self.last_message)
        try:
            battlefield, units = load_scenario_file(path)
        except Exception as exc:
            self.last_message = f"加载失败：{exc}"
            return CommandResult(False, self.last_message)
        self._accept_scenario(battlefield, units, path)
        self.last_message = f"地图已加载：{path.name}"
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def export_result(self, filepath: str | Path) -> CommandResult:
        if self.game_state != GAME_FINISHED or self.simulator is None:
            return CommandResult(False, "请先完成仿真，再导出结果")
        path = Path(filepath).expanduser()
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            if is_builtin_scenario(path):
                raise ValueError("不能覆盖内置预设场景")
            write_json_atomic(path, {
                "schema_version": 1,
                "scene_id": self.scene_id,
                "scene_name": self.scene_name,
                "statistics": self._statistics_snapshot(self.simulator.units),
                "units": [self._unit_snapshot(unit) for unit in self.simulator.units],
                "logs": list(self.simulator.combat_logs),
            })
        except Exception as exc:
            self.last_message = f"导出失败：{exc}"
            return CommandResult(False, self.last_message)
        self.last_message = f"结果已导出：{path.name}"
        return CommandResult(True, self.last_message)

    def snapshot(self) -> dict[str, Any]:
        """Return a QML-safe snapshot containing only basic Python values."""
        units = (
            self.deployment.display_units()
            if self.game_state == GAME_DEPLOYMENT
            else self.simulator.units if self.simulator else []
        )
        return {
            "game_state": self.game_state,
            "state_label": STATE_LABELS.get(self.game_state, self.game_state),
            "message": self.last_message,
            "speed_label": self.speed_label,
            "speed_interval_ms": self.speed_interval_ms,
            "speed_index": self.speed_index,
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "current_scenario": self.scene_name,
            "scenarios": self.available_scenarios(),
            "current_save_path": str(self.current_save_path) if self.current_save_path else "",
            "show_wrecks": self.simulator.show_wrecks if self.simulator else True,
            "map": self._map_snapshot(),
            "units": [self._unit_snapshot(unit) for unit in units],
            "attack_events": self._attack_event_snapshot(),
            "deployment": self._deployment_snapshot(),
            "statistics": self._statistics_snapshot(units),
            "logs": list(self.simulator.combat_logs) if self.simulator else [],
        }

    def _map_snapshot(self) -> dict[str, Any]:
        editor = self.deployment.editor
        preview = editor.preview_rect
        selected = editor.state.selected_obs_idx
        return {
            "width": self.battlefield.width,
            "height": self.battlefield.height,
            "terrain": self.battlefield.terrain,
            "style": self.battlefield.map_style,
            "visual": map_presentation(self.battlefield.map_style,
                                       self.battlefield.width, self.battlefield.height),
            "red_base": self._base_snapshot(TEAM_RED),
            "blue_base": self._base_snapshot(TEAM_BLUE),
            "obstacles": [
                {
                    "index": index,
                    "name": obstacle_display_name(obstacle),
                    "type": obstacle.type,
                    "x": obstacle.x,
                    "y": obstacle.y,
                    "width": obstacle.width,
                    "height": obstacle.height,
                    "selected": selected == index,
                }
                for index, obstacle in enumerate(self.battlefield.obstacles)
            ],
            "preview": (
                {
                    "visible": True,
                    "x": preview[0],
                    "y": preview[1],
                    "width": preview[2],
                    "height": preview[3],
                }
                if preview
                else {"visible": False, "x": 0, "y": 0, "width": 0, "height": 0}
            ),
        }

    def _base_snapshot(self, team: str) -> dict[str, Any]:
        base = self.battlefield.base_obj(team)
        return {
            "team": team,
            "x": base.x,
            "y": base.y,
            "hp": base.hp,
            "max_hp": base.max_hp,
            "destroyed": base.is_destroyed,
        }

    @staticmethod
    def _unit_snapshot(unit: Unit) -> dict[str, Any]:
        max_ammo = get_unit_stats(unit.unit_type).get("ammo", unit.ammo)
        return {
            "id": unit.id,
            "name": unit.name,
            "team": unit.team,
            "unit_type": unit.unit_type,
            "type_label": UNIT_TYPE_LABELS.get(unit.unit_type, unit.unit_type),
            "unit_type_label": UNIT_TYPE_LABELS.get(unit.unit_type, unit.unit_type),
            "domain": unit.domain,
            "domain_label": {"air": "空中平台", "ground": "地面平台", "command": "指挥节点"}.get(unit.domain, unit.domain),
            "x": unit.x,
            "y": unit.y,
            "hp": unit.hp,
            "max_hp": unit.max_hp,
            "ammo": unit.ammo,
            "max_ammo": max_ammo,
            "status": unit.status,
            "status_label": STATUS_LABELS.get(unit.status, unit.status),
            "speed": unit.speed,
            "detect_range": unit.detect_range,
            "attack_range": unit.attack_range,
            "target_id": unit.target_id or "",
            "destroyed": unit.is_destroyed,
            "engagement": unit.engagement_state.phase_name,
            "engagement_label": unit.engagement_state.phase_name,
        }

    def _attack_event_snapshot(self) -> list[dict[str, Any]]:
        if not self.simulator:
            return []
        unit_map = {unit.id: unit for unit in self.simulator.units}
        snapshots = []
        for event in self.simulator.attack_events:
            attacker = unit_map.get(event.attacker_id)
            snapshots.append({
                "event_id": str(event.event_id),
                "attacker_id": event.attacker_id,
                "target_id": event.target_id,
                "attacker_team": attacker.team if attacker else "",
                "attacker_type": attacker.unit_type if attacker else "",
                "start": list(event.start),
                "end": list(event.end),
                "damage": event.damage,
                "target_hp": event.target_hp,
                "target_destroyed": event.target_destroyed,
                "critical": event.is_critical,
                "miss": event.is_miss,
                "life": event.life,
            })
        return snapshots

    def _deployment_snapshot(self) -> dict[str, Any]:
        selected_type = (
            self.deployment.selected_unit_type
            or self.deployment.selected_obstacle_type
            or ""
        )
        return {
            "phase": self.game_state,
            "phase_label": STATE_LABELS.get(self.game_state, self.game_state),
            "selected_team": self.deployment.selected_team,
            "selected_unit_type": self.deployment.selected_unit_type or "",
            "selected_obstacle_type": self.deployment.selected_obstacle_type or "",
            "selected_type": selected_type,
            "selected_label": self.deployment.selected_label,
            "display_unit_count": len(self.deployment.display_units()),
            "message": self.deployment.last_message,
        }

    def _statistics_snapshot(self, units: list[Unit]) -> dict[str, Any]:
        if self.simulator:
            statistics = self.simulator.status_snapshot()
            hits = getattr(self.simulator, "hit_count", {})
            statistics.setdefault("red_hits", hits.get(TEAM_RED, 0))
            statistics.setdefault("blue_hits", hits.get(TEAM_BLUE, 0))
            return statistics
        red_units = [unit for unit in units if unit.team == TEAM_RED]
        blue_units = [unit for unit in units if unit.team == TEAM_BLUE]
        return {
            "time_step": 0,
            "max_steps": MAX_SIMULATION_STEPS,
            "finish_reason": "",
            "red_remaining": len(red_units),
            "blue_remaining": len(blue_units),
            "red_destroyed": 0,
            "blue_destroyed": 0,
            "red_kills": 0,
            "blue_kills": 0,
            "red_attacks": 0,
            "blue_attacks": 0,
            "red_hits": 0,
            "blue_hits": 0,
            "red_damage": 0,
            "blue_damage": 0,
            "red_detected": 0,
            "blue_detected": 0,
            "red_focus": "无",
            "blue_focus": "无",
            "red_evading": 0,
            "blue_evading": 0,
            "evading_units": "",
            "red_strength": team_strength(red_units),
            "blue_strength": team_strength(blue_units),
            "red_situation": "待命",
            "blue_situation": "待命",
            "red_tactics": "部署",
            "blue_tactics": "部署",
            "red_behavior": "待命",
            "blue_behavior": "待命",
            "red_base_hp": self.battlefield.base_obj(TEAM_RED).hp,
            "blue_base_hp": self.battlefield.base_obj(TEAM_BLUE).hp,
            "red_base_max": self.battlefield.base_obj(TEAM_RED).max_hp,
            "blue_base_max": self.battlefield.base_obj(TEAM_BLUE).max_hp,
            "winner": None,
        }

    def _deployment_result(self, ok: bool) -> CommandResult:
        self.last_message = self.deployment.last_message
        return CommandResult(ok, self.last_message)

    def _sync_editor_message(self, ok: bool = True) -> CommandResult:
        message = self.deployment.editor.message
        if message:
            self.deployment.last_message = message
        return self._deployment_result(ok)
