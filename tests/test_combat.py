from config import STATUS_DESTROYED
from core.combat import CombatSystem
from core.units import GroundVehicle, ScoutDrone, StrikeDrone


def test_attack_reduces_target_hp():
    attacker = ScoutDrone(id="u1", name="红无人机", team="red", x=0, y=0)
    target = GroundVehicle(id="u2", name="蓝无人车", team="blue", x=20, y=0)

    CombatSystem().attack(attacker, target)

    assert target.hp == target.max_hp - attacker.attack_power


def test_attack_consumes_ammo():
    attacker = ScoutDrone(id="u1", name="红无人机", team="red", x=0, y=0)
    target = GroundVehicle(id="u2", name="蓝无人车", team="blue", x=20, y=0)

    CombatSystem().attack(attacker, target)

    assert attacker.ammo == 5


def test_target_destroyed_when_hp_zero():
    attacker = GroundVehicle(id="u1", name="红无人车", team="red", x=0, y=0, attack_power=200)
    target = ScoutDrone(id="u2", name="蓝无人机", team="blue", x=20, y=0)

    CombatSystem().attack(attacker, target)

    assert target.status == STATUS_DESTROYED
    assert target.is_destroyed


def test_out_of_range_cannot_attack():
    attacker = ScoutDrone(id="u1", name="红无人机", team="red", x=0, y=0)
    target = GroundVehicle(id="u2", name="蓝无人车", team="blue", x=500, y=0)

    event = CombatSystem().attack(attacker, target)

    assert event is None
    assert attacker.ammo == 6


def test_zero_ammo_cannot_attack():
    attacker = ScoutDrone(id="u1", name="红无人机", team="red", x=0, y=0, ammo=0)
    target = GroundVehicle(id="u2", name="蓝无人车", team="blue", x=20, y=0)

    event = CombatSystem().attack(attacker, target)

    assert event is None
    assert target.hp == target.max_hp


def test_destroyed_unit_cannot_attack():
    attacker = ScoutDrone(id="u1", name="红无人机", team="red", x=0, y=0, hp=0)
    target = GroundVehicle(id="u2", name="蓝无人车", team="blue", x=20, y=0)

    event = CombatSystem().attack(attacker, target)

    assert event is None
    assert target.hp == target.max_hp


def test_can_attack_air_flag_is_enforced():
    attacker = GroundVehicle(id="u1", name="红无人车", team="red", x=0, y=0, can_attack_air=False)
    target = ScoutDrone(id="u2", name="蓝无人机", team="blue", x=20, y=0)

    event = CombatSystem().attack(attacker, target)

    assert event is None
    assert attacker.ammo == 10


def test_can_attack_ground_flag_is_enforced():
    attacker = StrikeDrone(id="u1", name="红打击无人机", team="red", x=0, y=0, can_attack_ground=False)
    target = GroundVehicle(id="u2", name="蓝无人车", team="blue", x=20, y=0)

    event = CombatSystem().attack(attacker, target)

    assert event is None
    assert attacker.ammo == 7
