"""战局逐帧记录与回放轨迹。

运行记录（``runs/<run_id>.json``）原本只保存事件日志和保存那一刻的最终状态，
无法还原单位如何移动、在哪一步开火。本模块按步采样单位与基地的紧凑状态，
编码为 int16 + base64 存入 schema 3 运行记录的 ``replay`` 块，并在解码后
按游标提供单位快照、攻击连线、统计与日志。

``STATUS_CODES`` 与 ``ENGAGEMENT_CODES`` 是**冻结**编码表：只能追加，
不能重排，否则旧记录里的索引会指向错误的取值。
"""

from __future__ import annotations

import base64
import bisect
import sys
from array import array
from typing import Any, Iterable

from config import STATUS_EVADE, TEAM_BLUE, TEAM_RED
from core.threat import situation_label, tactics_label, team_strength

POSITION_SCALE = 10
FIELD_LAYOUT = ("x", "y", "hp", "ammo", "status", "engagement", "destroyed")
FRAME_FIELDS = len(FIELD_LAYOUT)
STATUS_CODES = ("Scout", "Move", "Attack", "Evade", "Destroyed")
ENGAGEMENT_CODES = ("搜索", "反应", "攻击", "冷却")
BASE_IDS = ("red_base", "blue_base")
BUFFER_SCHEMA = 1
DTYPE = "int16"
# 实时连线从 life=8 起算，并在产生它的那一步 tick 到 7（Simulator._tick_attack_events）。
ATTACK_EVENT_LIFE = 7

_INT16_MIN = -32768
_INT16_MAX = 32767
_DEFAULT_STEP_DURATION = 0.22


class ReplayError(ValueError):
    """运行记录缺少可回放的逐帧数据。"""


def _clamp_int16(value: float) -> int:
    return max(_INT16_MIN, min(_INT16_MAX, int(value)))


def _code(table: tuple[str, ...], value: str) -> int:
    try:
        return table.index(value)
    except ValueError:
        # 码表冻结；未知取值只能落到表首，靠测试保证枚举与码表同步。
        return 0


def pack_unit(unit: Any) -> list[int]:
    """把一个单位当前状态压成 7 个 int16。"""
    return [
        _clamp_int16(round(float(unit.x) * POSITION_SCALE)),
        _clamp_int16(round(float(unit.y) * POSITION_SCALE)),
        _clamp_int16(int(unit.hp)),
        _clamp_int16(int(unit.ammo)),
        _code(STATUS_CODES, str(unit.status)),
        _code(ENGAGEMENT_CODES, str(unit.engagement_state.phase_name)),
        1 if unit.is_destroyed else 0,
    ]


class FrameBuffer:
    """按冻结的单位顺序逐步累积 int16 采样。"""

    def __init__(self, unit_ids: Iterable[str]) -> None:
        self.unit_ids: list[str] = list(unit_ids)
        self._values = array("h")
        self._encoded: str | None = None

    @property
    def unit_count(self) -> int:
        return len(self.unit_ids)

    @property
    def frame_count(self) -> int:
        stride = self.unit_count * FRAME_FIELDS
        return len(self._values) // stride if stride else 0

    def capture(self, units: Iterable[Any], red_base: Any, blue_base: Any) -> None:
        """追加一帧。基地不在 ``Simulator.units`` 里，需要显式传入。"""
        lookup = {unit.id: unit for unit in units}
        lookup[BASE_IDS[0]] = red_base
        lookup[BASE_IDS[1]] = blue_base
        for index, unit_id in enumerate(self.unit_ids):
            unit = lookup.get(unit_id)
            if unit is None:
                # 防御性兜底：正常一局内单位集合固定，不会走到这里。
                self._values.extend(self._previous_values(index))
                continue
            self._values.extend(pack_unit(unit))
        self._encoded = None

    def _previous_values(self, index: int) -> list[int]:
        if self.frame_count == 0:
            return [0] * FRAME_FIELDS
        start = ((self.frame_count - 1) * self.unit_count + index) * FRAME_FIELDS
        return list(self._values[start:start + FRAME_FIELDS])

    def encode(self) -> str:
        """base64 文本；按帧数缓存，自动保存时无需重复编码。"""
        if self._encoded is None:
            data = self._values
            if sys.byteorder == "big":
                data = array("h", data)
                data.byteswap()
            self._encoded = base64.b64encode(data.tobytes()).decode("ascii")
        return self._encoded


def encode_replay_block(buffer: FrameBuffer, unit_meta: dict[str, dict]) -> dict:
    """把帧缓冲与静态单位属性打包成运行记录里的 ``replay`` 块。"""
    return {
        "schema": BUFFER_SCHEMA,
        "frame_count": buffer.frame_count,
        "unit_count": buffer.unit_count,
        "byteorder": "little",
        "dtype": DTYPE,
        "scale": POSITION_SCALE,
        "field_layout": list(FIELD_LAYOUT),
        "status_codes": list(STATUS_CODES),
        "engagement_codes": list(ENGAGEMENT_CODES),
        "unit_ids": list(buffer.unit_ids),
        "units": {unit_id: dict(unit_meta.get(unit_id) or {}) for unit_id in buffer.unit_ids},
        "frames": buffer.encode(),
    }


def decode_frames(block: dict) -> tuple[array, list[str], int]:
    """解码 ``frames`` 字段，返回 (缓冲区, 单位 id 顺序, 单位数)。"""
    unit_ids = list(block.get("unit_ids") or [])
    unit_count = int(block.get("unit_count", len(unit_ids)))
    frame_count = int(block.get("frame_count", 0))
    payload = block.get("frames") or ""
    try:
        raw_bytes = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        raise ReplayError(f"回放数据无法解码：{exc}") from exc
    values = array("h")
    if len(raw_bytes) % values.itemsize:
        raise ReplayError("回放数据的字节长度无效")
    try:
        values.frombytes(raw_bytes)
    except (BufferError, MemoryError, ValueError) as exc:
        raise ReplayError(f"回放数据无法解码：{exc}") from exc
    if (sys.byteorder == "big") != (block.get("byteorder") == "big"):
        values.byteswap()
    if unit_count != len(unit_ids) or unit_count <= 0:
        raise ReplayError("回放数据的单位数量不一致")
    if len(values) != frame_count * unit_count * FRAME_FIELDS:
        raise ReplayError("回放数据的帧数与缓冲区长度不一致")
    return values, unit_ids, unit_count


class _UnitStandIn:
    """给 ``core.threat.team_strength`` 用的轻量替身，只带战力计算需要的字段。"""

    __slots__ = ("attack_power", "hp", "ammo", "is_destroyed")

    def __init__(self, attack_power: int, hp: int, ammo: int, is_destroyed: bool) -> None:
        self.attack_power = attack_power
        self.hp = hp
        self.ammo = ammo
        self.is_destroyed = is_destroyed


class ReplayTrack:
    """一局运行记录解码后的回放轨迹，按游标（步数）提供各界面负载。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        block = payload.get("replay")
        if not isinstance(block, dict):
            raise ReplayError("该记录没有回放数据（旧版本格式）")
        self._values, self.unit_ids, self.unit_count = decode_frames(block)
        self.scale = int(block.get("scale", POSITION_SCALE)) or POSITION_SCALE
        self.frame_count = int(block.get("frame_count", 0))
        self.unit_meta: dict[str, dict] = {
            str(key): dict(value) for key, value in (block.get("units") or {}).items()
            if isinstance(value, dict)
        }
        self.run_id = str(payload.get("run_id", ""))
        self.scene_id = str(payload.get("scene_id", ""))
        self.scene_name = str(payload.get("scene_name", ""))
        self.settings: dict = dict(payload.get("settings") or {})
        self.records: list[dict] = [
            row for row in (payload.get("records") or []) if isinstance(row, dict)
        ]
        self.destroyed_units: list[dict] = [
            row for row in (payload.get("destroyed_units") or []) if isinstance(row, dict)
        ]
        self.statistics_final: dict = dict(payload.get("statistics") or {})
        self.result: dict = dict(payload.get("result") or {})
        self.map_payload: dict = dict(payload.get("map") or {})
        self.finished = bool(payload.get("finished"))
        self._record_steps = [int(row.get("step", 0) or 0) for row in self.records]
        self._combat_records = [row for row in self.records if row.get("category") == "combat"]
        self._combat_steps = [int(row.get("step", 0) or 0) for row in self._combat_records]
        self._timing_segments = self._build_timing_segments()

    def _build_timing_segments(self) -> list[tuple[int, float, float]]:
        """Return (start step, elapsed seconds, duration) segments.

        Timing-change records already preserve the clock value at the boundary,
        so replay can reconstruct elapsed time without expanding every frame.
        """
        segments: list[tuple[int, float, float]] = []
        for row in self.records:
            if row.get("event") not in {"created", "timing_changed"}:
                continue
            try:
                step = int(row.get("step", 0) or 0)
                elapsed = float(row.get("elapsed_seconds", 0.0) or 0.0)
                duration = float(row["step_duration_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if duration > 0:
                segments.append((step, elapsed, duration))
        if not segments:
            segments.append((0, 0.0, self.step_duration_seconds))
        segments.sort(key=lambda item: item[0])
        return segments

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReplayTrack":
        return cls(payload)

    @property
    def max_step(self) -> int:
        return max(0, self.frame_count - 1)

    @property
    def step_duration_seconds(self) -> float:
        try:
            return float(self.settings.get("step_duration_seconds", _DEFAULT_STEP_DURATION))
        except (TypeError, ValueError):
            return _DEFAULT_STEP_DURATION

    def timing_at(self, cursor: int) -> tuple[float, float]:
        """Return the duration and cumulative clock at a replay cursor."""
        cursor = self.clamp(cursor)
        segment = self._timing_segments[0]
        for candidate in self._timing_segments[1:]:
            if candidate[0] > cursor:
                break
            segment = candidate
        step, elapsed, duration = segment
        return duration, round(elapsed + (cursor - step) * duration, 9)

    def clamp(self, index: int) -> int:
        try:
            value = int(index)
        except (TypeError, ValueError):
            return 0
        return max(0, min(self.max_step, value))

    def frame(self, index: int) -> dict[str, tuple[int, ...]]:
        """第 ``index`` 步（0 为部署态）各单位与基地的原始字段。"""
        index = self.clamp(index)
        stride = self.unit_count * FRAME_FIELDS
        start = index * stride
        values = self._values[start:start + stride]
        return {
            unit_id: tuple(values[offset * FRAME_FIELDS:(offset + 1) * FRAME_FIELDS])
            for offset, unit_id in enumerate(self.unit_ids)
        }

    def position(self, values: tuple[int, ...] | None) -> list[float]:
        if not values:
            return [0.0, 0.0]
        return [values[0] / self.scale, values[1] / self.scale]

    def unit_frame(self, index: int, unit_id: str) -> tuple[int, ...] | None:
        return self.frame(index).get(unit_id)

    def records_up_to(self, step: int) -> list[dict]:
        return self.records[:bisect.bisect_right(self._record_steps, int(step))]

    def combat_up_to(self, step: int) -> list[dict]:
        return self._combat_records[:bisect.bisect_right(self._combat_steps, int(step))]

    def destroyed_up_to(self, step: int) -> list[dict]:
        step = int(step)
        return [row for row in self.destroyed_units if int(row.get("step", 0) or 0) <= step]

    def logs_up_to(self, step: int, limit: int = 12) -> list[str]:
        rows = [row for row in self.records_up_to(step) if row.get("log_category")]
        return [f"[{row['log_category']}] {row['message']}" for row in rows[-limit:]]

    def attack_events(self, cursor: int) -> list[dict]:
        """重建游标处的攻击连线。

        事件记录写于结算阶段，其源/目标位置正是同一步移动阶段之后的位置，
        因此可直接从该步的帧里取回，无需额外持久化线段。
        """
        cursor = self.clamp(cursor)
        first = bisect.bisect_left(self._combat_steps, cursor - ATTACK_EVENT_LIFE + 1)
        last = bisect.bisect_right(self._combat_steps, cursor)
        frames: dict[int, dict[str, tuple[int, ...]]] = {}
        events = []
        for record in self._combat_records[first:last]:
            step = int(record.get("step", 0) or 0)
            life = ATTACK_EVENT_LIFE - (cursor - step)
            if life < 1:
                continue
            positions = frames.get(step)
            if positions is None:
                positions = self.frame(step)
                frames[step] = positions
            events.append(self._attack_event(record, positions, life))
        return events

    def _attack_event(self, record: dict, positions: dict, life: int) -> dict:
        source_id = str(record.get("source_id") or "")
        target_id = str(record.get("target_id") or "")
        step = int(record.get("step", 0) or 0)
        source_meta = self.unit_meta.get(source_id) or {}
        return {
            "event_id": f"{step}:{record.get('seq', 0)}",
            "attacker_id": source_id,
            "target_id": target_id,
            "attacker_team": source_meta.get("team", str(record.get("team") or "")),
            "attacker_type": source_meta.get("unit_type", ""),
            "start": self.position(positions.get(source_id)),
            "end": self.position(positions.get(target_id)),
            "damage": record.get("damage", 0),
            "target_hp": record.get("target_hp", 0),
            "target_destroyed": any(
                row.get("unit_id") == target_id and int(row.get("step", 0) or 0) == step
                for row in self.destroyed_units
            ),
            "critical": bool(record.get("is_critical", False)),
            "miss": record.get("event") == "miss",
            "life": life,
        }

    def statistics(self, cursor: int) -> dict:
        """按游标重建统计面板。

        可推导的量（步数/时间、剩余与摧毁、攻击/命中/伤害、战力、态势、基地血量、
        记录条数、规避数）取游标处真值；不可推导的定性字段（集火目标、探测数、
        行为标签、胜者与结束原因）沿用该局最终值。
        """
        cursor = self.clamp(cursor)
        stats = dict(self.statistics_final)
        stats["time_step"] = cursor
        duration, elapsed = self.timing_at(cursor)
        stats["elapsed_seconds"] = elapsed
        stats["step_duration_seconds"] = duration
        stats["max_steps"] = int(self.settings.get("max_steps", stats.get("max_steps", 0)) or 0)
        stats["record_count"] = len(self.records_up_to(cursor))

        positions = self.frame(cursor)
        remaining = {TEAM_RED: 0, TEAM_BLUE: 0}
        destroyed_now = {TEAM_RED: 0, TEAM_BLUE: 0}
        evading = {TEAM_RED: [], TEAM_BLUE: []}
        stand_ins: dict[str, list[_UnitStandIn]] = {TEAM_RED: [], TEAM_BLUE: []}
        for unit_id in self.unit_ids:
            if unit_id in BASE_IDS:
                continue
            meta = self.unit_meta.get(unit_id) or {}
            team = meta.get("team")
            values = positions.get(unit_id)
            if team not in remaining or not values:
                continue
            hp, ammo, status_code, destroyed = values[2], values[3], values[4], bool(values[6])
            if destroyed:
                destroyed_now[team] += 1
            else:
                remaining[team] += 1
                if STATUS_CODES[status_code] == STATUS_EVADE:
                    evading[team].append(str(meta.get("name", unit_id)))
            stand_ins[team].append(
                _UnitStandIn(int(meta.get("attack_power", 0) or 0), hp, ammo, destroyed))

        stats["red_remaining"] = remaining[TEAM_RED]
        stats["blue_remaining"] = remaining[TEAM_BLUE]
        stats["red_destroyed"] = destroyed_now[TEAM_RED]
        stats["blue_destroyed"] = destroyed_now[TEAM_BLUE]
        stats["red_evading"] = len(evading[TEAM_RED])
        stats["blue_evading"] = len(evading[TEAM_BLUE])
        stats["evading_units"] = ", ".join(evading[TEAM_RED] + evading[TEAM_BLUE])

        red_strength = team_strength(stand_ins[TEAM_RED])
        blue_strength = team_strength(stand_ins[TEAM_BLUE])
        red_situation = situation_label(red_strength, blue_strength, TEAM_RED)
        blue_situation = situation_label(red_strength, blue_strength, TEAM_BLUE)
        stats["red_strength"] = red_strength
        stats["blue_strength"] = blue_strength
        stats["red_situation"] = red_situation
        stats["blue_situation"] = blue_situation
        stats["red_tactics"] = tactics_label(red_situation)
        stats["blue_tactics"] = tactics_label(blue_situation)

        kills = {TEAM_RED: 0, TEAM_BLUE: 0}
        for row in self.destroyed_up_to(cursor):
            killer_team = (self.unit_meta.get(str(row.get("killer_id") or "")) or {}).get("team")
            if killer_team in kills:
                kills[killer_team] += 1
        stats["red_kills"] = kills[TEAM_RED]
        stats["blue_kills"] = kills[TEAM_BLUE]

        attacks = {TEAM_RED: 0, TEAM_BLUE: 0}
        hits = {TEAM_RED: 0, TEAM_BLUE: 0}
        damage = {TEAM_RED: 0, TEAM_BLUE: 0}
        for record in self.combat_up_to(cursor):
            team = record.get("team")
            if team not in attacks:
                continue
            attacks[team] += 1
            if record.get("event") == "hit":
                hits[team] += 1
                damage[team] += int(record.get("damage", 0) or 0)
        stats["red_attacks"] = attacks[TEAM_RED]
        stats["blue_attacks"] = attacks[TEAM_BLUE]
        stats["red_hits"] = hits[TEAM_RED]
        stats["blue_hits"] = hits[TEAM_BLUE]
        stats["red_damage"] = damage[TEAM_RED]
        stats["blue_damage"] = damage[TEAM_BLUE]

        for key, base_id in (("red", BASE_IDS[0]), ("blue", BASE_IDS[1])):
            values = positions.get(base_id)
            if values:
                stats[f"{key}_base_hp"] = values[2]
        return stats

    def base_snapshot(self, cursor: int, team: str) -> dict:
        """按游标覆盖地图负载里的基地状态。"""
        base_id = BASE_IDS[0] if team == TEAM_RED else BASE_IDS[1]
        values = self.frame(self.clamp(cursor)).get(base_id)
        meta = self.unit_meta.get(base_id) or {}
        current = dict(self.map_payload.get(f"{team}_base") or {})
        if values:
            current.update({
                "x": values[0] / self.scale,
                "y": values[1] / self.scale,
                "hp": values[2],
                "destroyed": bool(values[6]),
            })
        current.setdefault("team", team)
        current.setdefault("max_hp", int(meta.get("max_hp", 0) or 0))
        return current
