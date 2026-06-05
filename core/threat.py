"""威胁评估与战场态势感知系统。"""

from __future__ import annotations

from config import (
    BASE_THREAT_SCORE,
    SITUATION_ADVANTAGE_RATIO,
    SITUATION_DISADVANTAGE_RATIO,
    STRENGTH_AMMO_WEIGHT,
    STRENGTH_ATTACK_WEIGHT,
    STRENGTH_HP_WEIGHT,
    TEAM_BLUE,
    TEAM_RED,
)
from core.units import Unit


def threat_score(target: Unit, reference: Unit | None = None) -> float:
    """计算目标威胁值。基础威胁 × (血量因子 + 射程因子)，距离越近越高。"""
    base = BASE_THREAT_SCORE.get(target.unit_type, 30)
    hp_factor = 0.5 + 0.3 * target.hp_ratio
    range_factor = 0.2 * min(1.0, target.attack_range / 200.0)
    score = base * (hp_factor + range_factor)
    if reference and not reference.is_destroyed:
        dist = reference.distance_to(target)
        if dist < 200:
            score *= (1.0 + (200 - dist) / 200)
    return round(score, 1)


def priority_targets(enemies: list[Unit], friendly_units: list[Unit]) -> list[Unit]:
    """按威胁值从高到低排序。"""
    alive = [e for e in enemies if not e.is_destroyed]
    if not alive:
        return []
    alive_friends = [u for u in friendly_units if not u.is_destroyed]
    ref = alive_friends[0] if alive_friends else None
    return sorted(alive, key=lambda e: threat_score(e, ref), reverse=True)


def team_strength(units: list[Unit]) -> float:
    """计算阵营总战力。"""
    alive = [u for u in units if not u.is_destroyed]
    if not alive:
        return 0.0
    return round(
        sum(u.attack_power for u in alive) * STRENGTH_ATTACK_WEIGHT
        + sum(u.hp for u in alive) * STRENGTH_HP_WEIGHT
        + sum(u.ammo for u in alive) * STRENGTH_AMMO_WEIGHT * 10,
        1,
    )


def situation_label(red_strength: float, blue_strength: float, team: str) -> str:
    """优势 / 均势 / 劣势。"""
    if team == TEAM_RED:
        ratio = red_strength / max(blue_strength, 1)
    else:
        ratio = blue_strength / max(red_strength, 1)
    if ratio >= SITUATION_ADVANTAGE_RATIO:
        return "优势"
    if ratio <= SITUATION_DISADVANTAGE_RATIO:
        return "劣势"
    return "均势"


def tactics_label(situation: str) -> str:
    return {"优势": "进攻", "均势": "协同推进", "劣势": "保守推进"}.get(situation, "待命")
