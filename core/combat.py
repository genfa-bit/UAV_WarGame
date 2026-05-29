"""战斗结算系统。"""

from __future__ import annotations

from dataclasses import dataclass

from config import STATUS_ATTACK
from core.units import Unit


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
    life: int = 8


class CombatSystem:
    """封装攻击范围、弹药消耗和伤害结算。"""

    def can_attack(self, attacker: Unit, target: Unit) -> bool:
        return attacker.can_attack(target)

    def attack(self, attacker: Unit, target: Unit) -> AttackEvent | None:
        """执行一次抽象化攻击。"""
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
