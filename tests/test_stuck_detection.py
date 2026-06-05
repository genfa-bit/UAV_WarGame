"""路径异常检测系统测试。"""

from core.behavior import BehaviorManager


def test_stuck_detection_triggers_after_threshold():
    mgr = BehaviorManager()
    # Same position for 6 frames should trigger stuck
    for i in range(6):
        result = mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)
    # After 6 frames with no movement, counter = 6, which >= 6
    assert mgr._stuck_counters.get("u1", 0) >= 6


def test_stuck_resets_on_large_movement():
    mgr = BehaviorManager()
    for _ in range(5):
        mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)
    # Move significantly
    result = mgr.update_stuck("u1", 200.0, 200.0, 6, 3.0)
    assert mgr._stuck_counters["u1"] == 0


def test_stuck_small_movement_still_counts():
    mgr = BehaviorManager()
    mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)  # init
    mgr.update_stuck("u1", 101.0, 100.0, 6, 3.0)  # small move, counter++
    assert mgr._stuck_counters.get("u1", 0) >= 1


def test_clear_stuck_resets():
    mgr = BehaviorManager()
    for _ in range(5):
        mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)
    mgr.clear_stuck("u1")
    assert mgr._stuck_counters["u1"] == 0
