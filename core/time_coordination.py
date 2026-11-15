"""时间协调：到达时间估计（ETA）、打击时刻（TOT）与火力门。

HTCS 与 RDMA v2 的核心差别是**时间维**：分配不只回答“谁打谁”，还回答
“什么时候打”。本模块提供三个纯函数/小对象，供规划器与 Simulator 共用：

- ``estimate_eta``：单位机动到可开火位置还需要多少步；
- ``plan_tot``：把同一任务内各单位的 ETA 收敛成一个共同打击时刻（齐射
  的 time-to-go 一致性思路）；
- ``FireWindow``/``FirePlan``：火力门。提前到达的单位进入待机，窗口内
  或在迟到宽限内才允许排队攻击。

全部逻辑只依赖单位、目标和战场，不修改任何状态，便于单元测试。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_HORIZON_CAP = 999


def estimate_eta(unit, target, battlefield=None, *, include_reaction=True,
                 standoff_ratio: float = 0.85) -> int:
    """估计单位进入可开火位置所需的步数。

    - 已在射程内：0；
    - 否则按地形修正后的实际速度估计路程，并在 READY 前计入反应延迟；
    - 速度为 0（指挥节点/基地）且不在射程内：返回很大的值，表示无法
      在合理时间内抵达，规划器会把它排除在时间敏感任务之外。
    """
    distance = unit.distance_to(target)
    if unit.attack_range > 0 and distance <= unit.attack_range:
        travel = 0.0
    else:
        speed = (unit.effective_speed(battlefield)
                 if battlefield is not None else unit.speed)
        if speed <= 0:
            return _HORIZON_CAP
        standoff = unit.attack_range * standoff_ratio
        travel = max(0.0, distance - standoff)
        travel = math.ceil(travel / speed)
    eta = int(travel)
    if include_reaction and unit.engagement_state.phase.name == "SEARCH":
        eta += max(0, int(unit.reaction_delay))
    return max(0, min(_HORIZON_CAP, eta))


def plan_tot(step: int, etas, wave_length_steps: int) -> int:
    """由一组 ETA 生成共同打击时刻。

    取任务内最晚的到达者作为 TOT，使先到单位短暂待机、后到单位到达即
    开火，形成近似同时到达。TOT 最多推迟一个波次长度，超出部分按迟到
    处理（迟到宽限内仍可开火），避免远距离目标无限推迟本波次。
    """
    values = [int(eta) for eta in etas] or [0]
    latest = max(0, max(values))
    horizon = max(1, int(wave_length_steps))
    return int(step) + max(1, min(horizon, latest))


def staging_standoff(unit, ratio: float = 1.15) -> float:
    """提前到达时的待机距离：射程外沿稍远处，避免提前进入交战。"""
    return max(24.0, unit.attack_range * max(0.0, float(ratio)))


@dataclass(frozen=True)
class FireWindow:
    """一个打击时刻及其允许的开火窗口。"""

    tot: int
    tolerance: int = 1
    late: int = 3

    @property
    def window_start(self) -> int:
        return max(0, int(self.tot) - max(0, int(self.tolerance)))

    @property
    def window_end(self) -> int:
        return int(self.tot)

    @property
    def late_until(self) -> int:
        return int(self.tot) + max(0, int(self.late))

    def permits(self, step: int) -> bool:
        """当前步是否允许开火（早于窗口需待机，迟到宽限内仍可开火）。"""
        return self.window_start <= int(step) <= self.late_until

    def is_early(self, step: int) -> bool:
        return int(step) < self.window_start

    def is_late(self, step: int) -> bool:
        return int(step) > self.late_until

    def expired(self, step: int) -> bool:
        return int(step) > self.late_until


@dataclass
class FirePlan:
    """单位的一次计划射击：目标、任务、打击时刻与窗口。"""

    task_id: str
    target_id: str
    wave: int
    role: str
    window: FireWindow

    @property
    def tot(self) -> int:
        return self.window.tot

    @property
    def window_start(self) -> int:
        return self.window.window_start

    @property
    def late_until(self) -> int:
        return self.window.late_until

    def permits(self, step: int) -> bool:
        return self.window.permits(step)

    def is_early(self, step: int) -> bool:
        return self.window.is_early(step)
