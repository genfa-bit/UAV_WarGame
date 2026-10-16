"""Frontend-neutral application controller and serializable snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

from config import (
    GAME_DEPLOYMENT,
    GAME_FINISHED,
    GAME_PAUSED,
    GAME_REPLAY,
    GAME_REPLAY_PAUSED,
    GAME_REPLAY_STATES,
    GAME_RUNNING,
    MAX_SIMULATION_STEPS,
    MIN_STEP_DURATION_SECONDS,
    MAX_STEP_DURATION_SECONDS,
    MAX_CONFIGURABLE_STEPS,
    OBSTACLE_TYPE_LABELS,
    SIM_SPEED_LEVELS,
    SIMULATION_INTERVAL_MS,
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
    load_scenario_file, read_json_document, save_scenario, user_scenario_dir,
    write_json_atomic,
)
from core.replay import (BASE_IDS, ENGAGEMENT_CODES, STATUS_CODES, ReplayError,
                         ReplayTrack, encode_replay_block)
from core.scenario_loader import load_scenario
from core.simulator import Simulator
from core.threat import team_strength
from core.terrain_catalog import MAP_STYLES, map_presentation
from core.unit_config_loader import get_unit_stats
from core.units import Unit


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIO_PATH = BASE_DIR / "data" / "scenario_1.json"
DEFAULT_SAVE_PATH = user_scenario_dir() / "saved_map.json"
_RECORD_AUTOSAVE_INTERVAL_SECONDS = 5.0
# v3 增加逐帧 replay 块与静态 map 负载；v2 记录仍可读取，只是不能回放。
JOURNAL_SCHEMA = 3
SUPPORTED_JOURNAL_SCHEMAS = (2, 3)


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
        self.step_duration_seconds = SIMULATION_INTERVAL_MS / 1000
        self.max_steps = MAX_SIMULATION_STEPS
        self.last_message = ""
        self.current_save_path: Path | None = None
        self.scene_id = ""
        self.scene_name = self.scenario_path.stem
        self._initial_deployment = None
        self._run_deployment = None
        self._run_id = ""
        self._run_started_at = ""
        self._record_save_path = ""
        self._recording_error = ""
        self._history: list[dict[str, Any]] | None = None
        self._last_run_payload: dict[str, Any] | None = None
        self._unsaved_runs: dict[str, dict[str, Any]] = {}
        self._last_record_save_step = 0
        self._last_record_save_at = 0.0
        self._replay: ReplayTrack | None = None
        self._replay_cursor = 0
        self._replay_run_id = ""
        self._replay_save_path = ""
        # 退出回放要恢复的那份部署，在进入回放时捕获（见 replay_run）。
        self._replay_return = None
        self._show_wrecks = True
        battlefield, units = load_scenario(self.scenario_path)
        self._accept_scenario(battlefield, units, self.scenario_path)

    @property
    def speed_label(self) -> str:
        label = SIM_SPEED_LEVELS[self.speed_index][0]
        return "快速计算" if label == "MAX" else label

    @property
    def speed_interval_ms(self) -> int:
        base_interval = SIM_SPEED_LEVELS[self.speed_index][1]
        if base_interval == 0:
            return 0
        multiplier = SIM_SPEED_LEVELS[0][1] / base_interval
        return max(1, round(self.step_duration_seconds * 1000 / multiplier))

    @property
    def recording_directory(self) -> Path:
        return user_scenario_dir().parent / "runs"

    def set_timing(self, duration: float, max_steps: int) -> CommandResult:
        """Apply both values together, without changing elapsed simulation time."""
        if self.game_state not in (GAME_DEPLOYMENT, GAME_PAUSED):
            self.last_message = "只能在部署或暂停时修改时间设置"
            return CommandResult(False, self.last_message)
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not MIN_STEP_DURATION_SECONDS <= duration <= MAX_STEP_DURATION_SECONDS
                or not math.isfinite(duration)):
            self.last_message = "单步时长须为 0.01 至 60 秒"
            return CommandResult(False, self.last_message)
        if (isinstance(max_steps, bool) or not isinstance(max_steps, int)
                or not 1 <= max_steps <= MAX_CONFIGURABLE_STEPS):
            self.last_message = f"最大步数须为 1 至 {MAX_CONFIGURABLE_STEPS} 的整数"
            return CommandResult(False, self.last_message)
        if self.simulator and max_steps <= self.simulator.time_step:
            self.last_message = "最大步数必须大于当前已运行步数"
            return CommandResult(False, self.last_message)
        if self.simulator:
            try:
                self.simulator.configure_timing(float(duration), max_steps)
            except ValueError as exc:
                self.last_message = str(exc)
                return CommandResult(False, self.last_message)
        self.step_duration_seconds = float(duration)
        self.max_steps = max_steps
        self.last_message = f"时间设置已更新：每步 {duration:g} 秒，最多 {max_steps} 步"
        if self.simulator:
            self._persist_run()
            self.last_message = self._with_recording_warning(self.last_message)
        return CommandResult(True, self.last_message)

    def reset(self) -> CommandResult:
        # 回放时 _replay 仍持有数据，直接 reset 会让状态与画面不一致。
        if self._replay is not None:
            self.last_message = "回放中不能返回部署，请先退出回放"
            return CommandResult(False, self.last_message)
        baseline = self._run_deployment if self.game_state != GAME_DEPLOYMENT else self._initial_deployment
        if baseline is None:
            return CommandResult(False, "没有可恢复的部署")
        self._archive_run("reset", "已返回部署阶段")
        self._restore_deployment(baseline)
        self._run_deployment = None
        self.last_message = self._with_recording_warning("已返回部署阶段，可修改部署后再次运行")
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def _restore_deployment(self, baseline) -> None:
        battlefield, units = deepcopy(baseline)
        self.battlefield = battlefield
        self.deployment = DeploymentManager(battlefield, units)
        self.simulator = None
        self.game_state = GAME_DEPLOYMENT

    # ═══════════════════════════════════════════════════════════
    #  回放
    # ═══════════════════════════════════════════════════════════

    @property
    def replaying(self) -> bool:
        return self._replay is not None

    @property
    def replay_playing(self) -> bool:
        return self.game_state == GAME_REPLAY

    def replay_run(self, filepath: str | Path) -> CommandResult:
        """载入一局运行记录的逐帧数据并停在第一帧（部署帧），等待播放。"""
        source = Path(filepath).expanduser()
        try:
            payload = read_json_document(source)
        except (OSError, ValueError) as exc:
            self.last_message = f"无法读取运行记录：{exc}"
            return CommandResult(False, self.last_message)
        if not isinstance(payload, dict):
            self.last_message = "运行记录格式不正确"
            return CommandResult(False, self.last_message)
        if payload.get("schema_version") not in SUPPORTED_JOURNAL_SCHEMAS:
            self.last_message = "无法识别的运行记录版本"
            return CommandResult(False, self.last_message)
        if not isinstance(payload.get("replay"), dict):
            self.last_message = "该记录是旧版本，未包含逐帧数据，无法回放"
            return CommandResult(False, self.last_message)
        try:
            track = ReplayTrack.from_payload(payload)
        except ReplayError as exc:
            self.last_message = str(exc)
            return CommandResult(False, self.last_message)
        if track.frame_count <= 0:
            self.last_message = "该记录没有可回放的帧"
            return CommandResult(False, self.last_message)
        # 先落盘进行中的对局，避免它只留在内存里。
        if self._replay is None:
            if self.simulator is not None:
                self._persist_run()
            # 从部署态直接进回放时，退出要回到用户此刻正在编辑的布局；
            # 沿用 _run_deployment 会退回上一局开跑前的旧布局，丢掉刚做的编辑。
            self._replay_return = (deepcopy((self.battlefield, self.deployment.deploy_units))
                                   if self.game_state == GAME_DEPLOYMENT
                                   else self._run_deployment)
        self._replay = track
        # 停在第一帧而不是末帧：回放看的是这一局怎么打起来的，从部署态起播才是它该有的开头。
        self._replay_cursor = 0
        self._replay_run_id = track.run_id
        self._replay_save_path = str(source)
        self._show_wrecks = True
        self.game_state = GAME_REPLAY_PAUSED
        self.last_message = (f"回放：{track.scene_name or source.stem}，"
                             f"共 {track.frame_count} 帧（第 0–{track.max_step} 步），"
                             f"已停在第一帧")
        return CommandResult(True, self.last_message)

    def replay_current_run(self) -> CommandResult:
        """回放刚刚打完的这一局（读它已落盘的运行记录）。"""
        if not self._run_id:
            return CommandResult(False, "还没有可回放的对局")
        path = Path(self._record_save_path) if self._record_save_path else \
            self.recording_directory / f"{self._run_id}.json"
        if not self._replay and self.simulator is not None:
            self._persist_run()
            if self._record_save_path:
                path = Path(self._record_save_path)
        if not path.exists():
            return CommandResult(False, "本局记录尚未保存，无法回放")
        return self.replay_run(path)

    def exit_replay(self) -> CommandResult:
        if self._replay is None:
            return CommandResult(False, "当前不在回放")
        baseline = self._replay_return if self._replay_return is not None \
            else self._run_deployment or self._initial_deployment
        self._replay = None
        self._replay_cursor = 0
        self._replay_run_id = ""
        self._replay_save_path = ""
        self._replay_return = None
        if baseline is None:
            self.game_state = GAME_DEPLOYMENT
            self.last_message = "已退出回放"
            return CommandResult(True, self.last_message)
        self._restore_deployment(baseline)
        self.last_message = "已退出回放，返回部署阶段"
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def seek_replay(self, index: int) -> CommandResult:
        if self._replay is None:
            return CommandResult(False, "当前不在回放")
        self._replay_cursor = self._replay.clamp(index)
        self.last_message = f"回放定位到第 {self._replay_cursor} 步"
        return CommandResult(True, self.last_message)

    def replay_step(self, delta: int = 1) -> CommandResult:
        if self._replay is None:
            return CommandResult(False, "当前不在回放")
        if isinstance(delta, bool) or not isinstance(delta, int):
            return CommandResult(False, "无效的回放步进")
        if self.game_state == GAME_REPLAY:
            self.game_state = GAME_REPLAY_PAUSED
        return self.seek_replay(self._replay_cursor + delta)

    def _replay_advance(self) -> CommandResult:
        track = self._replay
        if track is None or self.game_state != GAME_REPLAY:
            return CommandResult(False, "")
        if self._replay_cursor >= track.max_step:
            self.game_state = GAME_REPLAY_PAUSED
            self.last_message = "回放结束"
            return CommandResult(True, self.last_message)
        self._replay_cursor += 1
        if self._replay_cursor >= track.max_step:
            self.game_state = GAME_REPLAY_PAUSED
            self.last_message = "回放结束"
        return CommandResult(True, self.last_message)

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
        if self._replay is not None:
            self.last_message = "回放中不能重新运行，请先退出回放"
            return CommandResult(False, self.last_message)
        if self._run_deployment is not None:
            self._archive_run("restart", "重新运行，保存上一局记录")
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
        self.simulator = Simulator(self.battlefield, result.units,
                                   max_steps=self.max_steps,
                                   step_duration_seconds=self.step_duration_seconds)
        self.game_state = GAME_RUNNING
        now = datetime.now(timezone.utc)
        self._run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        self._run_started_at = now.isoformat()
        self._record_save_path = ""
        self._recording_error = ""
        self._last_record_save_step = 0
        self.simulator.record_event("lifecycle", "仿真已开始", action="start",
                                    step_duration_seconds=self.step_duration_seconds,
                                    max_steps=self.max_steps)
        self._persist_run()
        self.last_message = self._with_recording_warning("仿真已开始")
        return CommandResult(True, self.last_message)

    def toggle_pause(self) -> CommandResult:
        if self.game_state in GAME_REPLAY_STATES:
            self.game_state = (GAME_REPLAY_PAUSED if self.game_state == GAME_REPLAY
                               else GAME_REPLAY)
            self.last_message = "回放继续" if self.game_state == GAME_REPLAY else "回放暂停"
            return CommandResult(True, self.last_message)
        if self.game_state == GAME_RUNNING:
            self.game_state = GAME_PAUSED
            self.simulator.record_event("lifecycle", "仿真已暂停", action="pause")
            self._persist_run()
            self.last_message = self._with_recording_warning("仿真已暂停")
            return CommandResult(True, self.last_message)
        if self.game_state == GAME_PAUSED:
            self.game_state = GAME_RUNNING
            self.simulator.record_event("lifecycle", "仿真继续", action="resume")
            self._persist_run()
            self.last_message = self._with_recording_warning("仿真继续")
            return CommandResult(True, self.last_message)
        return CommandResult(False, "当前状态不能暂停或继续")

    def step(self) -> CommandResult:
        if self._replay is not None:
            return self.replay_step(1)
        if self.simulator is None or self.game_state not in (
            GAME_RUNNING,
            GAME_PAUSED,
        ):
            return CommandResult(False, "请先开始仿真")
        if self.game_state == GAME_RUNNING:
            self.simulator.record_event("lifecycle", "单步运行后暂停", action="pause")
        self.simulator.step()
        self.game_state = GAME_FINISHED if self.simulator.winner else GAME_PAUSED
        self._persist_run()
        self.last_message = self._with_recording_warning("仿真结束" if self.simulator.winner else "已推进一个时间步")
        return CommandResult(True, self.last_message)

    def advance(self) -> CommandResult:
        if self._replay is not None:
            return self._replay_advance()
        if self.simulator is None or self.game_state != GAME_RUNNING:
            return CommandResult(False, "")
        self.simulator.step()
        if self.simulator.winner:
            self.game_state = GAME_FINISHED
            self.last_message = "仿真结束"
            self._persist_run()
            self.last_message = self._with_recording_warning(self.last_message)
        elif (self.simulator.time_step - self._last_record_save_step >= 50
              and monotonic() - self._last_record_save_at >= _RECORD_AUTOSAVE_INTERVAL_SECONDS):
            self._persist_run()
            self.last_message = self._with_recording_warning("仿真运行中")
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
        if self._replay is not None:
            self._show_wrecks = not self._show_wrecks
        elif self.simulator is not None:
            self.simulator.show_wrecks = not self.simulator.show_wrecks
            self._show_wrecks = self.simulator.show_wrecks
        else:
            return CommandResult(False, "请先开始仿真")
        label = "显示" if self._show_wrecks else "隐藏"
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

    @property
    def editor_active(self) -> bool:
        """部署阶段是否有进行中的编辑手势，供界面区分点击与平移。"""
        return self.game_state == GAME_DEPLOYMENT and self.deployment.editor_active

    def pointer_cancel(self) -> CommandResult:
        if self.game_state != GAME_DEPLOYMENT:
            return CommandResult(False, "")
        self.deployment.handle_mouse_cancel()
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
        if self._replay is not None:
            self.last_message = "回放中不能保存地图，请先退出回放"
            return CommandResult(False, self.last_message)
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
        if self._replay is not None:
            self.last_message = "回放中不能载入地图，请先退出回放"
            return CommandResult(False, self.last_message)
        path = Path(filepath).expanduser() if filepath is not None else self.current_save_path or user_scenario_dir() / "saved_map.json"
        if not path.exists():
            self.last_message = f"未找到地图：{path.name}"
            return CommandResult(False, self.last_message)
        try:
            battlefield, units = load_scenario_file(path)
        except Exception as exc:
            self.last_message = f"加载失败：{exc}"
            return CommandResult(False, self.last_message)
        self._archive_run("scene_change", f"加载场景：{path.stem}")
        self._accept_scenario(battlefield, units, path)
        self.last_message = self._with_recording_warning(f"地图已加载：{path.name}")
        self.deployment.last_message = self.last_message
        return CommandResult(True, self.last_message)

    def export_result(self, filepath: str | Path) -> CommandResult:
        if self.game_state != GAME_FINISHED or self.simulator is None:
            return CommandResult(False, "请先完成仿真，再导出结果")
        return self._export_run(filepath, "all", "结果")

    def export_records(self, filepath: str | Path, category: str = "all") -> CommandResult:
        """Export every event from the current or most recently archived run."""
        return self._export_run(filepath, category, "记录")

    def flush_records(self) -> CommandResult:
        """Save the current journal on normal application shutdown."""
        if self._replay is not None:
            # 回放不写记录，但仍要补存此前失败的对局。
            self._retry_unsaved_runs()
            saved = True
        elif self.simulator is None:
            saved = self._retry_unsaved_runs()
        else:
            saved = self._persist_run()
        if not saved:
            self.last_message = self._with_recording_warning("运行状态保持不变")
            return CommandResult(False, self.last_message)
        self.last_message = "运行记录已保存"
        return CommandResult(True, self.last_message)

    def _export_run(self, filepath: str | Path, category: str, label: str) -> CommandResult:
        allowed = {"all", "scout", "sharing", "destroyed", "tactical", "result", "settings", "lifecycle", "combat"}
        if category not in allowed:
            self.last_message = "无效的记录类型"
            return CommandResult(False, self.last_message)
        payload = self._run_payload() if self.simulator else deepcopy(self._last_run_payload)
        if payload is None:
            self.last_message = "请先开始仿真，再导出记录"
            return CommandResult(False, self.last_message)
        if category != "all":
            payload["records"] = [record for record in payload["records"]
                                  if record["category"] == category]
        payload["record_filter"] = category
        payload["exported_record_count"] = len(payload["records"])
        path = Path(filepath).expanduser()
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            if is_builtin_scenario(path):
                raise ValueError("不能覆盖内置预设场景")
            write_json_atomic(path, payload)
        except Exception as exc:
            self.last_message = f"导出失败：{exc}"
            return CommandResult(False, self.last_message)
        self.last_message = f"{label}已导出：{path.name}"
        return CommandResult(True, self.last_message)

    def _ensure_record_history(self) -> None:
        if self._history is not None:
            return
        self._history = []
        try:
            files = sorted(self.recording_directory.glob("*.json"), reverse=True)
            for path in files:
                try:
                    payload = read_json_document(path)
                    if (isinstance(payload, dict)
                            and payload.get("schema_version") in SUPPORTED_JOURNAL_SCHEMAS
                            and isinstance(payload.get("run_id"), str) and payload["run_id"]
                            and isinstance(payload.get("statistics"), dict)
                            and isinstance(payload.get("records"), list)):
                        self._history.append(self._run_summary(payload, str(path)))
                except (OSError, ValueError, TypeError, KeyError):
                    # A damaged individual file must not hide other saved runs.
                    continue
        except OSError as exc:
            self._recording_error = f"读取历史记录失败：{exc}"

    @staticmethod
    def _run_summary(payload: dict[str, Any], save_path: str) -> dict[str, Any]:
        statistics = payload["statistics"]
        return {
            "run_id": payload["run_id"],
            "scene_name": payload.get("scene_name", ""),
            "finished": bool(payload.get("finished")),
            "steps": statistics.get("time_step", 0),
            "elapsed_seconds": statistics.get("elapsed_seconds", 0.0),
            "winner": statistics.get("winner") or "",
            "record_count": len(payload.get("records", [])),
            "save_path": save_path,
            "replayable": isinstance(payload.get("replay"), dict),
        }

    def _run_payload(self) -> dict[str, Any] | None:
        if self.simulator is None:
            return None
        self._ensure_record_history()
        statistics = self._statistics_snapshot(self.simulator.units)
        return {
            "schema_version": JOURNAL_SCHEMA,
            "run_id": self._run_id,
            "started_at": self._run_started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "scene_id": self.scene_id,
            "scene_name": self.scene_name,
            "phase": self.game_state,
            "finished": self.game_state == GAME_FINISHED,
            "settings": {"step_duration_seconds": self.step_duration_seconds,
                         "max_steps": self.max_steps},
            "statistics": statistics,
            "result": {"winner": statistics.get("winner"),
                       "finish_reason": statistics.get("finish_reason", ""),
                       "steps": statistics.get("time_step", 0),
                       "elapsed_seconds": statistics.get("elapsed_seconds", 0.0)},
            "units": self._units_snapshot(self.simulator.units),
            "destroyed_units": deepcopy(self.simulator.destroyed_units),
            "records": deepcopy(self.simulator.records),
            "logs": list(self.simulator.combat_logs),
            "history": deepcopy(self._history[:20]),
            "map": self._map_payload(),
            "replay": encode_replay_block(self.simulator.frame_buffer,
                                          self._replay_unit_meta(self.simulator)),
        }

    def _replay_unit_meta(self, simulator: Simulator) -> dict[str, dict[str, Any]]:
        """回放所需的静态单位属性；位置只存在于帧里，不在此重复。"""
        units = list(simulator.units) + [simulator.battlefield.base_obj(TEAM_RED),
                                         simulator.battlefield.base_obj(TEAM_BLUE)]
        meta = {}
        for unit in units:
            meta[unit.id] = {
                "name": unit.name,
                "team": unit.team,
                "unit_type": unit.unit_type,
                "type_label": UNIT_TYPE_LABELS.get(unit.unit_type, unit.unit_type),
                "domain": unit.domain,
                "domain_label": {"air": "空中平台", "ground": "地面平台",
                                 "command": "指挥节点"}.get(unit.domain, unit.domain),
                "speed": unit.speed,
                "attack_power": unit.attack_power,
                "max_hp": unit.max_hp,
                "max_ammo": get_unit_stats(unit.unit_type).get("ammo", unit.ammo),
                "detect_range": unit.detect_range,
                "attack_range": unit.attack_range,
            }
        return meta

    def _map_payload(self) -> dict[str, Any]:
        """运行记录里的静态地图：不含编辑态，供回放画出当时的战场。"""
        snapshot = self._map_snapshot()
        snapshot.pop("preview", None)
        for obstacle in snapshot["obstacles"]:
            obstacle.pop("selected", None)
        return snapshot

    def _persist_run(self) -> bool:
        # 回放期间绝不新建或覆盖运行记录。
        if self._replay is not None:
            return True
        payload = self._run_payload()
        if payload is None:
            return True
        self._last_record_save_step = self.simulator.time_step
        self._last_run_payload = payload
        path = self.recording_directory / f"{self._run_id}.json"
        try:
            write_json_atomic(path, payload, compress=True)
        except Exception as exc:
            self._recording_error = f"自动保存记录失败：{exc}"
            self._unsaved_runs[self._run_id] = payload
            saved = False
        else:
            self._record_save_path = str(path)
            self._recording_error = ""
            self._unsaved_runs.pop(self._run_id, None)
            saved = True
        summary = self._run_summary(payload, self._record_save_path)
        self._history = [summary] + [row for row in self._history if row["run_id"] != self._run_id]
        pending_saved = self._retry_unsaved_runs(exclude_run_id=self._run_id)
        self._last_record_save_at = monotonic()
        return saved and pending_saved

    def _retry_unsaved_runs(self, exclude_run_id: str | None = None) -> bool:
        """Recover archived journals after a transient storage failure."""
        self._ensure_record_history()
        all_saved = True
        for run_id, payload in list(self._unsaved_runs.items()):
            if run_id == exclude_run_id:
                continue
            path = self.recording_directory / f"{run_id}.json"
            try:
                write_json_atomic(path, payload, compress=True)
            except Exception as exc:
                self._recording_error = f"自动保存记录失败：{exc}"
                all_saved = False
            else:
                self._unsaved_runs.pop(run_id, None)
                if run_id == self._run_id:
                    self._record_save_path = str(path)
                summary = self._run_summary(payload, str(path))
                self._history = [summary] + [row for row in self._history if row["run_id"] != run_id]
        self._history.sort(key=lambda row: row["run_id"], reverse=True)
        if not self._unsaved_runs:
            self._recording_error = ""
        return all_saved

    def _archive_run(self, action: str, message: str) -> None:
        if self._replay is not None or self.simulator is None:
            return
        self.simulator.record_event("lifecycle", message, action=action)
        self._persist_run()

    def _with_recording_warning(self, message: str) -> str:
        if self._recording_error:
            return f"{message}；{self._recording_error}，记录仍保留在内存中，请导出记录"
        return message

    def _recording_snapshot(self) -> dict[str, Any]:
        self._ensure_record_history()
        track = self._replay
        if track is not None:
            # 回放时记录面板只显示游标之前的事件，读起来正是那一刻的样子。
            records = track.records_up_to(self._replay_cursor)
            return {
                "has_run": True,
                "run_id": self._replay_run_id,
                "record_count": len(records),
                "records": deepcopy(records[-200:]),
                "destroyed_units": deepcopy(track.destroyed_up_to(self._replay_cursor)),
                "history": deepcopy(self._history[:20]),
                "save_path": self._replay_save_path,
                "last_error": "",
                "unsaved_count": 0,
                "directory": str(self.recording_directory),
                "replayable": True,
            }
        payload = self._last_run_payload
        records = self.simulator.records if self.simulator else payload.get("records", []) if payload else []
        destroyed = self.simulator.destroyed_units if self.simulator else payload.get("destroyed_units", []) if payload else []
        return {
            "has_run": self.simulator is not None or payload is not None,
            "run_id": self._run_id,
            "record_count": len(records),
            "records": deepcopy(records[-200:]),
            "destroyed_units": deepcopy(destroyed),
            "history": deepcopy(self._history[:20]),
            "save_path": self._record_save_path,
            "last_error": self._recording_error,
            "unsaved_count": len(self._unsaved_runs),
            "directory": str(self.recording_directory),
            "replayable": (self.simulator is not None
                           or bool(payload) and isinstance(payload.get("replay"), dict)),
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a QML-safe snapshot containing only basic Python values.

        回放时键名与形状和实时完全一致，只是取值来自逐帧记录与游标，
        因此地图、单位、连线、详情和统计面板都无需区分两种模式。
        """
        track = self._replay
        if track is not None:
            cursor = self._replay_cursor
            dynamic = {
                "map": self._replay_map_snapshot(),
                "units": self._replay_units_snapshot(),
                "attack_events": track.attack_events(cursor),
                "statistics": track.statistics(cursor),
                "logs": track.logs_up_to(cursor),
            }
        else:
            units = (
                self.deployment.display_units()
                if self.game_state == GAME_DEPLOYMENT
                else self.simulator.units if self.simulator else []
            )
            dynamic = {
                "map": self._map_snapshot(),
                "units": self._units_snapshot(units),
                "attack_events": self._attack_event_snapshot(),
                "statistics": self._statistics_snapshot(units),
                "logs": list(self.simulator.combat_logs) if self.simulator else [],
            }
        scene_name = track.scene_name if track else self.scene_name
        snapshot = {
            "game_state": self.game_state,
            "state_label": STATE_LABELS.get(self.game_state, self.game_state),
            "message": self.last_message,
            "speed_label": self.speed_label,
            "speed_interval_ms": self.speed_interval_ms,
            "speed_index": self.speed_index,
            "scene_id": track.scene_id if track else self.scene_id,
            "scene_name": scene_name,
            "current_scenario": scene_name,
            "scenarios": self.available_scenarios(),
            "current_save_path": (self._replay_save_path if track
                                  else str(self.current_save_path) if self.current_save_path else ""),
            "show_wrecks": (self._show_wrecks if track
                            else self.simulator.show_wrecks if self.simulator else True),
            "timing": ({"step_duration_seconds": track.step_duration_seconds,
                        "max_steps": track.max_step, "editable": False} if track
                       else {"step_duration_seconds": self.step_duration_seconds,
                             "max_steps": self.max_steps,
                             "editable": self.game_state in (GAME_DEPLOYMENT, GAME_PAUSED)}),
            "recording": self._recording_snapshot(),
            "deployment": self._deployment_snapshot(),
            "replay": self._replay_snapshot(),
        }
        snapshot.update(dynamic)
        return snapshot

    def _replay_snapshot(self) -> dict[str, Any]:
        track = self._replay
        if track is None:
            return {"active": False, "playing": False, "cursor": 0, "frame_count": 0,
                    "max_step": 0, "run_id": "", "scene_name": "",
                    "step_duration_seconds": 0.0, "elapsed_seconds": 0.0,
                    "records_up_to": 0, "finished": False}
        cursor = self._replay_cursor
        return {
            "active": True,
            "playing": self.game_state == GAME_REPLAY,
            "cursor": cursor,
            "frame_count": track.frame_count,
            "max_step": track.max_step,
            "run_id": self._replay_run_id,
            "scene_name": track.scene_name,
            "step_duration_seconds": track.step_duration_seconds,
            "elapsed_seconds": round(cursor * track.step_duration_seconds, 9),
            "records_up_to": len(track.records_up_to(cursor)),
            "finished": track.finished,
        }

    def _replay_units_snapshot(self) -> list[dict[str, Any]]:
        """与 ``_unit_snapshot`` 逐字段一致，取值来自游标帧与静态单位属性。"""
        track = self._replay
        positions = track.frame(self._replay_cursor)
        destroyed = {row["unit_id"]: row for row in track.destroyed_up_to(self._replay_cursor)}
        rows = []
        for unit_id in track.unit_ids:
            if unit_id in BASE_IDS:
                continue  # 基地由地图负载渲染，与实时一致
            values = positions.get(unit_id)
            if not values:
                continue
            meta = track.unit_meta.get(unit_id) or {}
            status = STATUS_CODES[values[4]]
            engagement = ENGAGEMENT_CODES[values[5]]
            type_label = meta.get("type_label", meta.get("unit_type", ""))
            # 摧毁信息只在游标越过该单位被摧毁的那一步后才出现。
            destruction = destroyed.get(unit_id) or {}
            rows.append({
                "id": unit_id,
                "name": meta.get("name", unit_id),
                "team": meta.get("team", ""),
                "unit_type": meta.get("unit_type", ""),
                "type_label": type_label,
                "unit_type_label": type_label,
                "domain": meta.get("domain", ""),
                "domain_label": meta.get("domain_label", ""),
                "x": values[0] / track.scale,
                "y": values[1] / track.scale,
                "hp": values[2],
                "max_hp": meta.get("max_hp", 0),
                "ammo": values[3],
                "max_ammo": meta.get("max_ammo", values[3]),
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
                "speed": meta.get("speed", 0),
                "detect_range": meta.get("detect_range", 0),
                "attack_range": meta.get("attack_range", 0),
                "target_id": "",
                "destroyed": bool(values[6]),
                "destroyed_step": destruction.get("step"),
                "destroyed_elapsed_seconds": destruction.get("elapsed_seconds"),
                "killer_id": destruction.get("killer_id") or "",
                "killer_name": destruction.get("killer_name") or "",
                "engagement": engagement,
                "engagement_label": engagement,
            })
        return rows

    def _replay_map_snapshot(self) -> dict[str, Any]:
        """画当时那张地图：障碍与地形取自记录，基地血量按游标覆盖。"""
        track = self._replay
        cursor = self._replay_cursor
        snapshot = deepcopy(track.map_payload)
        snapshot.setdefault("width", self.battlefield.width)
        snapshot.setdefault("height", self.battlefield.height)
        snapshot.setdefault("terrain", self.battlefield.terrain)
        snapshot.setdefault("style", self.battlefield.map_style)
        snapshot.setdefault("visual", map_presentation(snapshot["style"], snapshot["width"],
                                                       snapshot["height"]))
        snapshot["red_base"] = track.base_snapshot(cursor, TEAM_RED)
        snapshot["blue_base"] = track.base_snapshot(cursor, TEAM_BLUE)
        snapshot["preview"] = {"visible": False, "x": 0, "y": 0, "width": 0, "height": 0}
        for index, obstacle in enumerate(snapshot.get("obstacles") or []):
            obstacle.setdefault("index", index)
            obstacle["selected"] = False
        return snapshot

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
    def _unit_snapshot(unit: Unit, destruction: dict[str, Any] | None = None) -> dict[str, Any]:
        max_ammo = get_unit_stats(unit.unit_type).get("ammo", unit.ammo)
        destruction = destruction or {}
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
            "destroyed_step": destruction.get("step"),
            "destroyed_elapsed_seconds": destruction.get("elapsed_seconds"),
            "killer_id": destruction.get("killer_id") or "",
            "killer_name": destruction.get("killer_name") or "",
            "engagement": unit.engagement_state.phase_name,
            "engagement_label": unit.engagement_state.phase_name,
        }

    def _units_snapshot(self, units: list[Unit]) -> list[dict[str, Any]]:
        destroyed = {row["unit_id"]: row for row in self.simulator.destroyed_units} if self.simulator else {}
        return [self._unit_snapshot(unit, destroyed.get(unit.id)) for unit in units]

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
            "max_steps": self.max_steps,
            "step_duration_seconds": self.step_duration_seconds,
            "elapsed_seconds": 0.0,
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
