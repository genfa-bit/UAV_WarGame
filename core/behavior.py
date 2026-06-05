"""统一行为决策管理器。

每个单位每帧只执行一个最高优先级行为，避免多模块控制冲突。
优先级：Attack > Evade > Scout > Patrol
"""

from __future__ import annotations

from enum import IntEnum

from config import STATUS_ATTACK, STATUS_EVADE, STATUS_MOVE, STATUS_SCOUT

MAX_EVADE_STEPS = 20        # 规避最大持续帧
EVADE_COOLDOWN = 120         # 规避退出后冷却帧数（≈26秒）


class Behavior(IntEnum):
    """行为优先级（值越大优先级越高）。"""
    PATROL = 0
    SCOUT = 1
    EVADE = 2
    ATTACK = 3


BEHAVIOR_LABELS = {
    Behavior.ATTACK: "攻击",
    Behavior.EVADE: "规避",
    Behavior.SCOUT: "侦察",
    Behavior.PATROL: "巡逻",
}

STATUS_TO_BEHAVIOR = {
    STATUS_ATTACK: Behavior.ATTACK,
    STATUS_EVADE: Behavior.EVADE,
    STATUS_SCOUT: Behavior.SCOUT,
    STATUS_MOVE: Behavior.PATROL,
}


class BehaviorManager:
    """统一行为决策：每帧选取当前最高优先级行为执行。"""

    def __init__(self):
        self._current: dict[str, Behavior] = {}
        self._stuck_counters: dict[str, int] = {}
        self._stuck_positions: dict[str, tuple[float, float]] = {}
        self._target_locks: dict[str, tuple[str, int]] = {}
        self._evade_duration: dict[str, int] = {}
        self._evade_cooldown: dict[str, int] = {}

    def resolve(self, unit_id: str, candidates: list[tuple[Behavior, callable]],
                force_exit_evade: bool = False) -> Behavior:
        """从候选行为中选择优先级最高者并执行。

        force_exit_evade: 强制移除 Evade 候选，用于达到最大规避时长时退出。
        """
        if force_exit_evade:
            candidates = [(b, a) for b, a in candidates if b != Behavior.EVADE]
        if not candidates:
            return Behavior.PATROL
        candidates.sort(key=lambda x: x[0], reverse=True)
        chosen_behavior, action = candidates[0]
        action()
        self._current[unit_id] = chosen_behavior
        # 更新规避时长
        if chosen_behavior == Behavior.EVADE:
            self._evade_duration[unit_id] = self._evade_duration.get(unit_id, 0) + 1
        else:
            self._evade_duration[unit_id] = 0
        return chosen_behavior

    def evade_exceeded(self, unit_id: str) -> bool:
        """规避是否超过最大持续帧。"""
        return self._evade_duration.get(unit_id, 0) >= MAX_EVADE_STEPS

    def start_evade_cooldown(self, unit_id: str) -> None:
        """规避退出后开始冷却，期间不可再次规避。"""
        self._evade_cooldown[unit_id] = EVADE_COOLDOWN

    def on_evade_cooldown(self, unit_id: str) -> bool:
        """是否处于规避冷却期。"""
        return self._evade_cooldown.get(unit_id, 0) > 0

    def tick_cooldowns(self) -> None:
        """每帧递减冷却计数。"""
        expired = []
        for uid in list(self._evade_cooldown):
            self._evade_cooldown[uid] -= 1
            if self._evade_cooldown[uid] <= 0:
                expired.append(uid)
        for uid in expired:
            del self._evade_cooldown[uid]

    def current_behavior(self, unit_id: str) -> Behavior:
        return self._current.get(unit_id, Behavior.PATROL)

    # ═══════════════════════════════════════════════════════════
    #  卡死检测
    # ═══════════════════════════════════════════════════════════

    def update_stuck(self, unit_id: str, x: float, y: float,
                     stuck_threshold: int, stuck_delta: float) -> bool:
        prev = self._stuck_positions.get(unit_id)
        if prev is None:
            self._stuck_counters[unit_id] = 0
            self._stuck_positions[unit_id] = (x, y)
            return False
        dist = ((x - prev[0]) ** 2 + (y - prev[1]) ** 2) ** 0.5
        if dist < stuck_delta:
            self._stuck_counters[unit_id] = self._stuck_counters.get(unit_id, 0) + 1
        else:
            self._stuck_counters[unit_id] = 0
        self._stuck_positions[unit_id] = (x, y)
        return self._stuck_counters.get(unit_id, 0) >= stuck_threshold

    def clear_stuck(self, unit_id: str) -> None:
        self._stuck_counters[unit_id] = 0

    # ═══════════════════════════════════════════════════════════
    #  目标锁定
    # ═══════════════════════════════════════════════════════════

    def lock_target(self, unit_id: str, target_id: str, lock_time: int) -> None:
        self._target_locks[unit_id] = (target_id, lock_time)

    def is_locked(self, unit_id: str, target_id: str) -> bool:
        lock = self._target_locks.get(unit_id)
        if lock is None:
            return False
        return lock[0] == target_id and lock[1] > 0

    def tick_target_locks(self) -> None:
        to_remove = []
        for uid, (tid, remaining) in self._target_locks.items():
            if remaining <= 1:
                to_remove.append(uid)
            else:
                self._target_locks[uid] = (tid, remaining - 1)
        for uid in to_remove:
            del self._target_locks[uid]
