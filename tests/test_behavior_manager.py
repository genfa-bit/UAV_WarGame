"""行为决策管理器测试。"""

from core.behavior import Behavior, BehaviorManager
from core.units import ScoutDrone, StrikeDrone, MissileVehicle


def test_behavior_priority_attack_highest():
    mgr = BehaviorManager()
    executed = []

    candidates = [
        (Behavior.PATROL, lambda: executed.append("patrol")),
        (Behavior.ATTACK, lambda: executed.append("attack")),
        (Behavior.EVADE, lambda: executed.append("evade")),
        (Behavior.SCOUT, lambda: executed.append("scout")),
    ]
    result = mgr.resolve("u1", candidates)
    assert result == Behavior.ATTACK
    assert executed == ["attack"]


def test_behavior_only_patrol_when_no_candidates():
    mgr = BehaviorManager()
    result = mgr.resolve("u1", [])
    assert result == Behavior.PATROL


def test_current_behavior_defaults_patrol():
    mgr = BehaviorManager()
    assert mgr.current_behavior("nonexistent") == Behavior.PATROL


def test_stuck_detection_triggers():
    mgr = BehaviorManager()
    # 首次调用初始化位置，counter=0
    mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)
    # 接下来 5 次：counter 从 1 递增到 5，不触发
    for _ in range(5):
        assert mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0) is False
    # 第 7 次（counter 达到 6 >= threshold=6），触发卡死
    assert mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0) is True


def test_stuck_clears_on_movement():
    mgr = BehaviorManager()
    for _ in range(5):
        mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)
    # move enough to reset counter
    mgr.update_stuck("u1", 110.0, 100.0, 6, 3.0)
    assert mgr._stuck_counters.get("u1", 0) == 0


def test_clear_stuck():
    mgr = BehaviorManager()
    for _ in range(5):
        mgr.update_stuck("u1", 100.0, 100.0, 6, 3.0)
    mgr.clear_stuck("u1")
    assert mgr._stuck_counters["u1"] == 0


def test_target_lock():
    mgr = BehaviorManager()
    mgr.lock_target("u1", "enemy1", 5)
    assert mgr.is_locked("u1", "enemy1")
    assert not mgr.is_locked("u1", "enemy2")


def test_target_lock_expires():
    mgr = BehaviorManager()
    mgr.lock_target("u1", "enemy1", 2)
    assert mgr.is_locked("u1", "enemy1")
    mgr.tick_target_locks()
    assert mgr.is_locked("u1", "enemy1")  # remaining=1
    mgr.tick_target_locks()
    assert not mgr.is_locked("u1", "enemy1")  # removed
