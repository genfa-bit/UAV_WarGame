"""战斗结算系统。

第十阶段改造为攻击意图队列模式：
- 单位攻击时仅生成 AttackIntent，不立即扣减生命值
- 每帧所有单位行为更新后统一调用 resolve_all_attacks() 批量结算
- 同步结算消除先手优势
- 新增动态命中概率计算（含掩体遮挡因子）
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

from config import STATUS_ATTACK
from core.units import Unit


_attack_event_ids = itertools.count(1)


@dataclass
class AttackEvent:
    """用于界面展示和日志输出的攻击事件。"""

    attacker_id: str
    target_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    damage: int = 0
    target_hp: int = 0
    target_destroyed: bool = False
    is_critical: bool = False
    is_miss: bool = False
    life: int = 8
    event_id: int = field(default_factory=lambda: next(_attack_event_ids))


@dataclass
class AttackIntent:
    """攻击意图记录，在 resolve 阶段统一结算。"""

    attacker_id: str
    target_id: str
    attacker_team: str
    start: tuple[float, float]
    end: tuple[float, float]
    damage: float
    hit_probability: float
    is_critical: bool
    attacker: Unit = field(repr=False)
    target: Unit = field(repr=False)


def _segment_intersects_rect(
    x1: float, y1: float, x2: float, y2: float,
    rx: float, ry: float, rw: float, rh: float,
) -> bool:
    """Liang-Barsky 线段裁剪算法：判断线段是否与矩形相交。"""
    dx = x2 - x1
    dy = y2 - y1
    p = [-dx, dx, -dy, dy]
    q = [x1 - rx, rx + rw - x1, y1 - ry, ry + rh - y1]

    u1, u2 = 0.0, 1.0
    for i in range(4):
        if abs(p[i]) < 1e-10:
            if q[i] < 0:
                return False
        else:
            t = q[i] / p[i]
            if p[i] < 0:
                u1 = max(u1, t)
            else:
                u2 = min(u2, t)
    return u1 <= u2


def calculate_hit_probability(
    attacker: Unit,
    target: Unit,
    battlefield=None,
    is_evading: bool = False,
) -> float:
    """基于多因子动态计算命中概率。

    因子包括：
    - 距离因子：越近命中率越高，射程边缘衰减
    - 目标速度因子：目标越快越难命中
    - 自身状态因子：规避状态时命中率下降
    - 掩体遮挡因子：视线穿过障碍物大幅降低命中率
    """
    base = attacker.base_hit_prob
    if base <= 0:
        return 0.0

    # ── 距离因子（射程边缘仅衰减 20%，保证远距离仍有可观命中率）──
    dist = attacker.distance_to(target)
    max_range = attacker.attack_range
    if max_range > 0:
        dist_factor = 1.0 - (dist / max_range) * 0.2
    else:
        dist_factor = 1.0

    # ── 速度因子 ──
    speed_factor = 1.0 - min(target.speed / 10.0, 1.0) * 0.4

    # ── 自身状态因子 ──
    status_factor = 0.7 if is_evading else 1.0

    # ── 掩体遮挡因子 ──
    cover_factor = 1.0
    if battlefield is not None:
        for obs in battlefield.obstacles:
            if _segment_intersects_rect(
                attacker.x, attacker.y, target.x, target.y,
                obs.x, obs.y, obs.width, obs.height,
            ):
                cover_factor = 0.3
                break

    prob = base * dist_factor * speed_factor * status_factor * cover_factor
    return max(0.05, min(0.95, prob))


class CombatSystem:
    """封装攻击范围检查、攻击意图队列和同步结算。"""

    def __init__(self):
        self._intents: list[AttackIntent] = []

    def can_attack(self, attacker: Unit, target: Unit) -> bool:
        return attacker.can_attack(target)

    def attack(self, attacker: Unit, target: Unit) -> AttackEvent | None:
        """执行一次直接攻击（兼容旧接口）。"""
        if not self.can_attack(attacker, target):
            return None
        attacker.ammo -= 1
        attacker.status = STATUS_ATTACK
        actual_damage = target.take_damage(attacker.attack_power)
        return AttackEvent(
            attacker_id=attacker.id,
            target_id=target.id,
            start=(attacker.x, attacker.y),
            end=(target.x, target.y),
            damage=actual_damage,
            target_hp=target.hp,
            target_destroyed=target.is_destroyed,
        )

    def queue_attack(
        self,
        attacker: Unit,
        target: Unit,
        battlefield=None,
        is_evading: bool = False,
    ) -> AttackIntent | None:
        """将攻击加入意图队列，不立即结算伤害。"""
        if not self.can_attack(attacker, target):
            return None
        attacker.ammo -= 1
        attacker.status = STATUS_ATTACK
        hit_prob = calculate_hit_probability(
            attacker, target, battlefield, is_evading)
        is_critical = random.random() < 0.1
        damage = attacker.attack_power * 1.5 if is_critical else float(attacker.attack_power)

        intent = AttackIntent(
            attacker_id=attacker.id,
            target_id=target.id,
            attacker_team=attacker.team,
            start=(attacker.x, attacker.y),
            end=(target.x, target.y),
            damage=damage,
            hit_probability=hit_prob,
            is_critical=is_critical,
            attacker=attacker,
            target=target,
        )
        self._intents.append(intent)
        return intent

    def resolve_all_attacks(self) -> list[AttackEvent]:
        """批量结算所有攻击意图，消除执行顺序导致的不公平。

        所有意图基于同一帧初的状态排队，结算时不因前置意图的结果
        而跳过后续意图 —— 这才是真正的"同步结算"。
        """
        events: list[AttackEvent] = []
        for intent in self._intents:
            target = intent.target

            if target is None:
                continue

            if random.random() < intent.hit_probability:
                if hasattr(target, 'take_damage'):
                    actual_damage = target.take_damage(int(intent.damage))
                else:
                    actual_damage = 0
                event = AttackEvent(
                    attacker_id=intent.attacker_id,
                    target_id=intent.target_id,
                    start=intent.start,
                    end=intent.end,
                    damage=actual_damage,
                    target_hp=target.hp if hasattr(target, 'hp') else 0,
                    target_destroyed=getattr(target, 'is_destroyed', False),
                    is_critical=intent.is_critical,
                    is_miss=False,
                )
            else:
                event = AttackEvent(
                    attacker_id=intent.attacker_id,
                    target_id=intent.target_id,
                    start=intent.start,
                    end=intent.end,
                    damage=0,
                    target_hp=target.hp if hasattr(target, 'hp') else 0,
                    target_destroyed=False,
                    is_critical=False,
                    is_miss=True,
                )
            events.append(event)
        self._intents.clear()
        return events

    def clear_intents(self) -> None:
        """清空意图队列（用于重置或状态异常时）。"""
        self._intents.clear()
