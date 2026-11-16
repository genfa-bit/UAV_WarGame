"""时间协调：到达时间估计（ETA）、打击时刻（TOT）与火力门。

HTCS 与 RDMA v2 的核心差别是**时间维**：分配不只回答“谁打谁”，还回答
“什么时候打”。本模块提供三个纯函数/小对象，供规划器与 Simulator 共用：

- ``estimate_eta``：单位机动到可开火位置还需要多少步；
- ``estimate_eta_interval``：同一估计的标称值/上界。标称值用于 TOT 与时间
  折扣，上界用于迟到宽限、可行性分类和再定时，避免“点估计偏小 → 合法
  射击被误判迟到”；
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


@dataclass(frozen=True)
class EtaEstimate:
    """ETA 的标称值与保守上界（单位：步）。

    ``nominal`` 与 ``estimate_eta`` 完全一致，供 TOT/时间折扣使用；
    ``upper`` 计入路径地形减速、绕障附加路程与最终安全系数，供迟到
    宽限、可行性分类与再定时使用。二者分开，避免用一个过于保守的值
    把整个波次的 TOT 推后。
    """

    nominal: int
    upper: int

    @property
    def slack(self) -> int:
        return max(0, int(self.upper) - int(self.nominal))


def estimate_eta_interval(
    unit, target, battlefield=None, *, include_reaction: bool = True,
    standoff_ratio: float = 0.85, target_speed: float = 0.0,
    sample_px: float = 8.0, detour_factor: float = 0.5,
    slack_ratio: float = 1.10,
) -> EtaEstimate:
    """估计 ETA 的标称值与上界。

    上界在标称路径之外依次计入：

    - **路径地形**：沿“单位 → 待机点”直线采样 ``effective_speed``，
      按分段速度累加时间，而不是只看出发地当前格子的速度；
    - **绕障附加**：采样点落在不可进入障碍内时，额外计入
      ``detour_factor × 受阻路程``，近似 Bug2 沿边绕行的代价；
    - **目标运动**：目标以 ``target_speed`` 远离时按相对速度放大时间；
    - **安全系数**：``slack_ratio`` 覆盖单位分离、卡死恢复等未建模损耗。

    返回的上界不低于标称值，且不超过 ``_HORIZON_CAP``。没有战场或单位
    速度为零时退化为“标称值 × 安全系数”，保证纯函数可独立测试。
    """
    nominal = estimate_eta(
        unit, target, battlefield, include_reaction=include_reaction,
        standoff_ratio=standoff_ratio)
    if nominal >= _HORIZON_CAP:
        return EtaEstimate(nominal, nominal)

    distance = unit.distance_to(target)
    if unit.attack_range > 0 and distance <= unit.attack_range:
        return EtaEstimate(nominal, nominal)
    speed = (unit.effective_speed(battlefield)
             if battlefield is not None else unit.speed)
    if speed <= 0 or unit.speed <= 0:
        return EtaEstimate(nominal, nominal)

    standoff = unit.attack_range * standoff_ratio
    travel_distance = max(0.0, distance - standoff)
    reaction = 0
    if include_reaction and unit.engagement_state.phase.name == "SEARCH":
        reaction = max(0, int(unit.reaction_delay))

    if battlefield is None or travel_distance <= 0.0:
        upper_travel = math.ceil(travel_distance / speed * float(slack_ratio))
    else:
        samples = max(1, min(64, math.ceil(travel_distance / max(1.0, sample_px))))
        segment = travel_distance / samples
        elapsed = 0.0
        blocked = 0.0
        for index in range(samples):
            fraction = (index + 0.5) / samples
            ratio = fraction * travel_distance / distance
            x = unit.x + (target.x - unit.x) * ratio
            y = unit.y + (target.y - unit.y) * ratio
            local_speed = unit.effective_speed(battlefield, x, y)
            if local_speed <= 0:
                local_speed = max(1e-6, unit.speed * 0.25)
            elapsed += segment / local_speed
            if not battlefield.is_position_valid(x, y, unit):
                blocked += segment
        # 绕障附加路程按单位基础速度折算；受阻段本身已经在 elapsed 中
        # 按“可通行”速度计过，这里只补绕行多出来的距离。
        detour = (blocked * max(0.0, float(detour_factor))
                  / max(1e-6, unit.speed))
        ratio_speed = max(0.0, float(target_speed)) / max(1e-6, unit.speed)
        upper_travel = math.ceil((elapsed + detour)
                                 * (1.0 + min(2.0, ratio_speed))
                                 * max(1.0, float(slack_ratio)))
    upper = max(nominal, int(upper_travel) + reaction)
    return EtaEstimate(nominal, max(0, min(_HORIZON_CAP, upper)))


def plan_tot(step: int, etas, horizon_steps: int) -> int:
    """由一组 ETA 生成共同打击时刻。

    取任务内最晚的到达者作为 TOT，使先到单位短暂待机、后到单位到达即
    开火，形成近似同时到达。``horizon_steps`` 是**时间视野**，不再是
    波次长度：HTCS 用 ``tot_horizon_steps``（默认 60 步）为上界，使
    反应 + 冷却周期 39–61 步的导弹发射车也能获得真实可执行的 TOT。
    超出视野的 ETA 才被截断，避免远距离目标无限推迟本波次。
    """
    values = [int(eta) for eta in etas] or [0]
    latest = max(0, max(values))
    horizon = max(1, int(horizon_steps))
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
    # ── 自适应迟到策略（late_fire_policy="adaptive"）使用的执行状态 ──
    # 标称/上界 ETA 在安装计划时冻结，用于计算本计划的迟到宽限；重定时
    # 会重新估计。``reached`` 表示单位至少一次真正进入过可开火位置，
    # 用于区分“没赶到”与“赶到了但没打出去”。``retimes`` 是单条计划
    # 已被推迟的次数，由任务级上限约束。
    eta_nominal: int = 0
    eta_upper: int = 0
    reached: bool = False
    blocked_by_discipline: bool = False
    retimes: int = 0

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
