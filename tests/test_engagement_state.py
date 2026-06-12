"""测试简化交战状态机 —— 第十阶段新增。"""

from core.engagement import EngagementPhase, EngagementState


def test_initial_state_is_search():
    es = EngagementState(reaction_delay=5, attack_cooldown=10)
    assert es.phase == EngagementPhase.SEARCH
    assert not es.can_attack


def test_on_target_spotted_transitions_to_reacting():
    es = EngagementState(reaction_delay=5, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    assert es.phase == EngagementPhase.REACTING
    assert es.current_target_id == "enemy_1"
    assert not es.can_attack


def test_reaction_progress_completes_to_attack():
    es = EngagementState(reaction_delay=3, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    for _ in range(3):
        es.tick()
    assert es.phase == EngagementPhase.ATTACK
    assert es.can_attack


def test_can_attack_true_after_reaction():
    es = EngagementState(reaction_delay=2, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    assert not es.can_attack
    es.tick()
    assert not es.can_attack
    es.tick()
    assert es.can_attack


def test_on_target_lost_during_reacting_resets():
    es = EngagementState(reaction_delay=5, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    es.tick()
    es.on_target_lost()
    assert es.phase == EngagementPhase.SEARCH
    assert es.current_target_id is None
    assert not es.can_attack


def test_attack_transitions_to_cooldown():
    es = EngagementState(reaction_delay=1, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    es.tick()
    assert es.phase == EngagementPhase.ATTACK
    es.on_attack_executed()
    assert es.phase == EngagementPhase.COOLDOWN
    assert not es.can_attack


def test_cooldown_completes_to_search():
    es = EngagementState(reaction_delay=1, attack_cooldown=3)
    es.on_target_spotted("enemy_1")
    es.tick()
    es.on_attack_executed()
    for _ in range(3):
        es.tick()
    assert es.phase == EngagementPhase.SEARCH
    assert es.current_target_id is None


def test_new_target_during_reacting_does_not_reset():
    """新目标出现不重置反应进度，避免多目标乒乓导致永不攻击。"""
    es = EngagementState(reaction_delay=5, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    es.tick()
    es.tick()
    # progress = 2，新目标出现应被忽略
    es.on_target_spotted("enemy_2")
    assert es.phase == EngagementPhase.REACTING
    assert es.current_target_id == "enemy_1"
    assert es.reaction_progress == 2


def test_zero_reaction_delay_goes_directly_to_attack():
    es = EngagementState(reaction_delay=0, attack_cooldown=10)
    es.on_target_spotted("enemy_1")
    assert es.phase == EngagementPhase.ATTACK
    assert es.can_attack


def test_phase_names():
    es = EngagementState(reaction_delay=5, attack_cooldown=10)
    assert es.phase_name == "搜索"
    es.on_target_spotted("e1")
    assert es.phase_name == "反应"
