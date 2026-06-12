"""简化交战状态机。

每个单位独立维护交战状态，控制攻击时序：
SEARCH → REACTING → ATTACK → COOLDOWN → SEARCH

反应延迟和攻击冷却均采用单位创建时的随机值，消除"先发现→先攻击→绝对优势"问题。
"""

from __future__ import annotations

from enum import Enum, auto


class EngagementPhase(Enum):
    """交战状态阶段。"""
    SEARCH = auto()      # 搜索目标
    REACTING = auto()    # 反应中（发现目标后延迟）
    ATTACK = auto()      # 可攻击
    COOLDOWN = auto()    # 攻击后冷却


class EngagementState:
    """单位交战状态机，控制攻击时机。"""

    def __init__(self, reaction_delay: int, attack_cooldown: int):
        self.phase = EngagementPhase.SEARCH
        self.reaction_delay = reaction_delay
        self.attack_cooldown = attack_cooldown
        self.reaction_progress = 0
        self.cooldown_progress = 0
        self.current_target_id: str | None = None

    @property
    def can_attack(self) -> bool:
        """当前帧是否允许发起攻击。"""
        return self.phase == EngagementPhase.ATTACK

    @property
    def phase_name(self) -> str:
        """返回中文阶段名（用于调试）。"""
        names = {
            EngagementPhase.SEARCH: "搜索",
            EngagementPhase.REACTING: "反应",
            EngagementPhase.ATTACK: "攻击",
            EngagementPhase.COOLDOWN: "冷却",
        }
        return names.get(self.phase, "未知")

    def on_target_spotted(self, target_id: str) -> None:
        """探测到目标时调用。仅在 SEARCH 阶段进入反应或直接攻击。
        已在反应/攻击/冷却中则忽略新目标，避免多目标乒乓导致永不攻击。"""
        if self.phase == EngagementPhase.SEARCH:
            if self.reaction_delay <= 0:
                self.phase = EngagementPhase.ATTACK
            else:
                self.phase = EngagementPhase.REACTING
                self.reaction_progress = 0
            self.current_target_id = target_id

    def on_target_lost(self) -> None:
        """目标丢失时调用。反应期丢失则重置，攻击/冷却期保持不变。"""
        if self.phase == EngagementPhase.REACTING:
            self.phase = EngagementPhase.SEARCH
            self.reaction_progress = 0
            self.current_target_id = None

    def tick(self) -> None:
        """每帧推进状态机。"""
        if self.phase == EngagementPhase.REACTING:
            self.reaction_progress += 1
            if self.reaction_progress >= self.reaction_delay:
                self.phase = EngagementPhase.ATTACK
                self.reaction_progress = 0
        elif self.phase == EngagementPhase.COOLDOWN:
            self.cooldown_progress += 1
            if self.cooldown_progress >= self.attack_cooldown:
                self.phase = EngagementPhase.SEARCH
                self.cooldown_progress = 0
                self.current_target_id = None

    def on_attack_executed(self) -> None:
        """攻击执行后调用，进入冷却。"""
        self.phase = EngagementPhase.COOLDOWN
        self.cooldown_progress = 0

    def on_attack_queued(self) -> None:
        """攻击加入队列后调用（与 on_attack_executed 同义，择一调用）。"""
        self.on_attack_executed()

    def reset_to_search(self) -> None:
        """强制重置为搜索状态（用于恢复异常卡死）。"""
        self.phase = EngagementPhase.SEARCH
        self.reaction_progress = 0
        self.cooldown_progress = 0
        self.current_target_id = None
