"""同步结算下的伤害账本（Damage Ledger）。

RDMA v2 的过杀惩罚只在“下一次分配”时起作用：同一帧里多个单位可以同时
把攻击排进队列，命中后又不会取消已经排队的意图，因此仍会出现整轮集火
打在一个只剩 10 HP 的目标上。HTCS 在**排队时刻**登记每发攻击的期望
伤害，后续单位看到账本已经覆盖目标效果时就会主动停火；结算后再把期望
值替换为实际伤害。

账本只记录“已经排队但尚未结算”的期望伤害，不直接修改单位或目标状态：
- ``reserved``：未来仍可能命中的期望伤害；
- ``applied``：已经结算的实际伤害（用于 BDA 与再攻击判断）；
- 记划需求由 ``remaining_need`` 计算，已经打掉的血量体现在目标当前
  ``hp`` 上，不会与 ``applied`` 重复扣减。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Reservation:
    """一次已排队攻击的期望伤害登记。"""

    attacker_id: str
    target_id: str
    expected: float
    step: int = 0


class DamageLedger:
    """按 (攻击者, 目标) 登记并结算期望伤害。"""

    def __init__(self) -> None:
        self._reservations: list[Reservation] = []
        self._applied: dict[str, float] = {}
        self._settled_shots: dict[str, int] = {}

    # ── 排队时刻 ────────────────────────────────────────────────
    def reserve(self, attacker_id: str, target_id: str, expected: float,
                step: int = 0) -> None:
        """登记一发已经排队的攻击。期望伤害 <= 0 时不登记。"""
        value = float(expected)
        if value <= 0.0:
            return
        self._reservations.append(
            Reservation(attacker_id, target_id, value, step))

    def settle(self, attacker_id: str, target_id: str,
               actual_damage: float) -> float:
        """结算一发攻击，返回被释放的期望值。

        同一 (攻击者, 目标) 可能有多发在途攻击，取最近登记的一条，保证
        每发攻击恰好释放一条预约。未登记过的攻击只累计实际伤害。
        """
        index = None
        for cursor in range(len(self._reservations) - 1, -1, -1):
            entry = self._reservations[cursor]
            if (entry.attacker_id == attacker_id
                    and entry.target_id == target_id):
                index = cursor
                break
        expected = 0.0
        if index is not None:
            expected = self._reservations.pop(index).expected
        damage = max(0.0, float(actual_damage))
        if damage > 0.0:
            self._applied[target_id] = (
                self._applied.get(target_id, 0.0) + damage)
            self._settled_shots[target_id] = (
                self._settled_shots.get(target_id, 0) + 1)
        elif index is None:
            return 0.0
        return expected

    # ── 查询 ────────────────────────────────────────────────────
    def reserved(self, target_id: str) -> float:
        return sum(entry.expected for entry in self._reservations
                   if entry.target_id == target_id)

    def reserved_by(self, attacker_id: str, target_id: str) -> float:
        return sum(entry.expected for entry in self._reservations
                   if entry.attacker_id == attacker_id
                   and entry.target_id == target_id)

    def applied(self, target_id: str) -> float:
        return self._applied.get(target_id, 0.0)

    def settled_shots(self, target_id: str) -> int:
        return self._settled_shots.get(target_id, 0)

    def pending_count(self, target_id: str | None = None) -> int:
        if target_id is None:
            return len(self._reservations)
        return sum(1 for entry in self._reservations
                   if entry.target_id == target_id)

    def remaining_need(self, target_id: str, hp: float,
                       desired_effect: float = 1.0) -> float:
        """目标仍需多少期望伤害才能达到效果阈值。"""
        threshold = max(1.0, float(hp) * float(desired_effect))
        return max(0.0, threshold - self.reserved(target_id))

    def is_saturated(self, target_id: str, hp: float,
                     desired_effect: float = 1.0,
                     ratio: float = 1.0) -> bool:
        """在途期望伤害是否已经达到阈值倍数（火力纪律停火条件）。"""
        threshold = max(1.0, float(hp) * float(desired_effect))
        return self.reserved(target_id) >= max(1.0, threshold * ratio)

    def would_overkill(self, target_id: str, hp: float, incoming: float,
                       desired_effect: float = 1.0,
                       ratio: float = 1.0) -> bool:
        """本发攻击是否会在已有预约之上造成过杀（交叉射击纪律）。

        与 ``is_saturated`` 的区别：后者只看**已经登记**的预约，因此每个
        排队单位都认为“账本还没满”，同一帧仍会把多发病害压到同一目标。
        这里把当前准备排队的这一发也算进去：

        - 账本没有任何预约时返回 False —— 总要有第一发去收掉残血目标，
          否则低血量目标会永远无人补刀；
        - 已有预约时，``已预约 + 本发`` 超过阈值即视为过杀，由调用方
          停火等待本帧结算。
        """
        reserved = self.reserved(target_id)
        if reserved <= 0.0:
            return False
        threshold = max(1.0, float(hp) * float(desired_effect))
        return reserved + max(0.0, float(incoming)) > max(
            1.0, threshold * float(ratio))

    # ── 清理 ────────────────────────────────────────────────────
    def clear_target(self, target_id: str) -> None:
        """目标被摧毁或离开战场后清空其预约与累计伤害。"""
        self._reservations = [entry for entry in self._reservations
                              if entry.target_id != target_id]
        self._applied.pop(target_id, None)
        self._settled_shots.pop(target_id, None)

    def prune(self, active_target_ids: set[str]) -> None:
        """丢弃指向已不在场的目标的预约。"""
        self._reservations = [entry for entry in self._reservations
                              if entry.target_id in active_target_ids]
        for target_id in set(self._applied) - active_target_ids:
            self._applied.pop(target_id, None)
            self._settled_shots.pop(target_id, None)

    def reset(self) -> None:
        self._reservations.clear()
        self._applied.clear()
        self._settled_shots.clear()

    def snapshot(self) -> dict[str, dict[str, float]]:
        """返回按目标汇总的只读快照，供记录与测试。"""
        targets = ({entry.target_id for entry in self._reservations}
                   | set(self._applied))
        return {
            target_id: {
                "reserved": self.reserved(target_id),
                "applied": self.applied(target_id),
                "pending": float(self.pending_count(target_id)),
            }
            for target_id in sorted(targets)
        }
