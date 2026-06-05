"""Shared target pool with communication delay support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from core.units import Unit


@dataclass
class TargetSighting:
    """A target known by one team, with last-seen step and available step."""
    target: Unit
    last_seen_step: int
    available_step: int = 0  # 信息何时对所有单位可用


class TargetPool:
    """Stores detected targets. values() only returns targets whose
    availability delay has expired."""

    def __init__(self) -> None:
        self._records: dict[str, TargetSighting] = {}

    def __contains__(self, target_id: str) -> bool:
        return target_id in self._records

    def __getitem__(self, target_id: str) -> Unit:
        return self._records[target_id].target

    def __setitem__(self, target_id: str, target: Unit | TargetSighting) -> None:
        if isinstance(target, TargetSighting):
            self._records[target_id] = target
        else:
            self._records[target_id] = TargetSighting(target=target, last_seen_step=0)

    def __delitem__(self, target_id: str) -> None:
        del self._records[target_id]

    def __len__(self) -> int:
        return len(self._records)

    def keys(self) -> Iterable[str]:
        return self._records.keys()

    def values(self) -> list[Unit]:
        """全部已记录目标（不含延迟过滤，向后兼容）。"""
        return [r.target for r in self._records.values()]

    def values_available(self, current_step: int) -> list[Unit]:
        """仅返回延迟已过的目标（大多单位可见）。"""
        return [r.target for r in self._records.values()
                if r.available_step <= current_step]

    def items(self) -> Iterator[tuple[str, Unit]]:
        for target_id, record in self._records.items():
            yield target_id, record.target

    def records(self) -> Iterable[TargetSighting]:
        return self._records.values()

    def sight(self, target: Unit, step: int, available_step: int | None = None) -> bool:
        """Add or refresh a target. available_step controls comm delay."""
        is_new = target.id not in self._records
        avail = available_step if available_step is not None else step
        self._records[target.id] = TargetSighting(
            target=target, last_seen_step=step, available_step=avail)
        return is_new

    def last_seen_step(self, target_id: str) -> int | None:
        record = self._records.get(target_id)
        return record.last_seen_step if record else None

    def cleanup(self, current_step: int, timeout_steps: int) -> list[tuple[str, Unit, str]]:
        removed: list[tuple[str, Unit, str]] = []
        for target_id, record in list(self._records.items()):
            if record.target.is_destroyed:
                removed.append((target_id, record.target, "destroyed"))
                del self._records[target_id]
            elif current_step - record.last_seen_step > timeout_steps:
                removed.append((target_id, record.target, "stale"))
                del self._records[target_id]
        return removed
