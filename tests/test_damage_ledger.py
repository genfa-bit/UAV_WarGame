"""伤害账本（DamageLedger）单元测试。

账本是 HTCS 火力纪律与 BDA 的数据基础：排队时登记期望伤害、结算时替换
为实际伤害、查询时给出“还差多少效果”。这里覆盖预约/结算/饱和/清理四组
语义，不涉及 Simulator。
"""

from __future__ import annotations

from core.damage_ledger import DamageLedger, Reservation


def test_reserve_accumulates_per_target():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.reserve("r2", "t1", 20)
    assert ledger.reserved("t1") == 50
    assert ledger.reserved_by("r1", "t1") == 30
    assert ledger.pending_count("t1") == 2
    assert ledger.pending_count() == 2


def test_reserve_ignores_non_positive_expected_damage():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 0)
    ledger.reserve("r1", "t1", -5)
    assert ledger.pending_count() == 0
    assert ledger.reserved("t1") == 0


def test_reserve_records_step_and_ids():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 12, step=7)
    assert ledger.snapshot()["t1"]["pending"] == 1.0
    assert isinstance(ledger.snapshot(), dict)


def test_settle_returns_the_matching_reservation_value():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.reserve("r2", "t1", 20)
    released = ledger.settle("r1", "t1", 27)
    assert released == 30
    assert ledger.reserved("t1") == 20
    assert ledger.applied("t1") == 27


def test_settle_accumulates_applied_damage_and_hit_count():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.reserve("r2", "t1", 20)
    ledger.settle("r1", "t1", 25)
    ledger.settle("r2", "t1", 18)
    assert ledger.applied("t1") == 43
    assert ledger.settled_shots("t1") == 2
    assert ledger.pending_count("t1") == 0


def test_settle_pops_most_recent_reservation_for_same_pair():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 10, step=1)
    ledger.reserve("r1", "t1", 40, step=2)
    assert ledger.settle("r1", "t1", 1) == 40
    assert ledger.reserved_by("r1", "t1") == 10


def test_settle_without_reservation_only_counts_damage():
    ledger = DamageLedger()
    released = ledger.settle("r9", "t1", 15)
    assert released == 0.0
    assert ledger.applied("t1") == 15
    assert ledger.settled_shots("t1") == 1


def test_settle_miss_without_reservation_is_a_no_op():
    ledger = DamageLedger()
    assert ledger.settle("r9", "t1", 0) == 0.0
    assert ledger.applied("t1") == 0
    assert ledger.settled_shots("t1") == 0


def test_settle_miss_still_releases_the_reservation():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 25)
    assert ledger.settle("r1", "t1", 0) == 25
    assert ledger.reserved("t1") == 0
    assert ledger.applied("t1") == 0


def test_remaining_need_subtracts_reserved_damage():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 40)
    assert ledger.remaining_need("t1", 100) == 60
    assert ledger.remaining_need("t1", 100, desired_effect=0.5) == 10


def test_remaining_need_is_never_negative():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 500)
    assert ledger.remaining_need("t1", 100) == 0


def test_remaining_need_uses_current_hp_not_applied_history():
    # 目标血量已经扣减过实际伤害，账本不能再重复扣一次。
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.settle("r1", "t1", 30)
    assert ledger.applied("t1") == 30
    assert ledger.remaining_need("t1", 70) == 70


def test_remaining_need_has_a_one_point_floor():
    ledger = DamageLedger()
    assert ledger.remaining_need("t1", 0) == 1.0


def test_is_saturated_respects_ratio():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 100)
    assert ledger.is_saturated("t1", 100) is True
    assert ledger.is_saturated("t1", 100, ratio=2.0) is False
    ledger.reserve("r2", "t1", 120)
    assert ledger.is_saturated("t1", 100, ratio=2.0) is True


def test_would_overkill_allows_the_first_finisher():
    # 账本为空时必须允许第一发收掉残血目标。
    ledger = DamageLedger()
    assert ledger.would_overkill("t1", 5, 34) is False


def test_would_overkill_blocks_a_crossing_shot():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 10)
    # 已有 10 点预约，再加 34 点会越过 5 点血阈值。
    assert ledger.would_overkill("t1", 5, 34) is True


def test_would_overkill_allows_a_shot_that_still_fits():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 10)
    assert ledger.would_overkill("t1", 100, 10) is False


def test_would_overkill_respects_the_ratio():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 100)
    assert ledger.would_overkill("t1", 100, 10) is True
    assert ledger.would_overkill(
        "t1", 100, 10, ratio=2.0) is False


def test_clear_target_drops_reservations_and_history():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.reserve("r2", "t2", 10)
    ledger.settle("r1", "t1", 30)
    ledger.clear_target("t1")
    assert ledger.reserved("t1") == 0
    assert ledger.applied("t1") == 0
    assert ledger.settled_shots("t1") == 0
    assert ledger.reserved("t2") == 10


def test_prune_keeps_only_active_targets():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.reserve("r2", "t2", 10)
    ledger.settle("r1", "t1", 30)
    ledger.prune({"t2"})
    assert ledger.reserved("t1") == 0
    assert ledger.applied("t1") == 0
    assert ledger.reserved("t2") == 10


def test_reset_clears_everything():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.settle("r1", "t1", 30)
    ledger.reset()
    assert ledger.snapshot() == {}


def test_snapshot_reports_reserved_applied_and_pending():
    ledger = DamageLedger()
    ledger.reserve("r1", "t1", 30)
    ledger.reserve("r2", "t1", 20)
    ledger.settle("r1", "t1", 26)
    snapshot = ledger.snapshot()
    assert snapshot["t1"] == {"reserved": 20.0, "applied": 26.0,
                              "pending": 1.0}


def test_reservation_dataclass_defaults():
    entry = Reservation("r1", "t1", 15.0)
    assert entry.step == 0
    assert entry.expected == 15.0
