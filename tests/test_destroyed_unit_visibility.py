"""单位残骸显示开关测试。"""

from core.battlefield import Battlefield
from core.simulator import Simulator
from core.units import ScoutDrone, StrikeDrone


def test_show_wrecks_defaults_true():
    bf = Battlefield(800, 600)
    sim = Simulator(bf, [])
    assert sim.show_wrecks is True


def test_show_wrecks_toggle():
    bf = Battlefield(800, 600)
    sim = Simulator(bf, [])
    sim.show_wrecks = False
    assert sim.show_wrecks is False
    sim.show_wrecks = True
    assert sim.show_wrecks is True


def test_destroyed_unit_not_in_active_units():
    bf = Battlefield(800, 600)
    unit = ScoutDrone(id="R-1", name="红-侦察无人机", team="red", x=50, y=50, hp=0)
    sim = Simulator(bf, [unit])

    active = sim.active_units()
    assert len(active) == 0


def test_destroyed_unit_still_in_units_list():
    bf = Battlefield(800, 600)
    unit = ScoutDrone(id="R-1", name="红-侦察无人机", team="red", x=50, y=50, hp=0)
    sim = Simulator(bf, [unit])

    assert len(sim.units) == 1
    assert sim.units[0].is_destroyed


def test_wreck_filter_excludes_destroyed_when_false():
    bf = Battlefield(800, 600)
    alive = ScoutDrone(id="R-1", name="红-侦察无人机", team="red", x=50, y=50)
    dead = StrikeDrone(id="B-1", name="蓝-打击无人机", team="blue", x=100, y=100, hp=0)
    sim = Simulator(bf, [alive, dead])

    sim.show_wrecks = False
    visible = [u for u in sim.units if not u.is_destroyed]
    assert len(visible) == 1
    assert visible[0].id == "R-1"


def test_wreck_filter_includes_destroyed_when_true():
    bf = Battlefield(800, 600)
    alive = ScoutDrone(id="R-1", name="红-侦察无人机", team="red", x=50, y=50)
    dead = StrikeDrone(id="B-1", name="蓝-打击无人机", team="blue", x=100, y=100, hp=0)
    sim = Simulator(bf, [alive, dead])

    sim.show_wrecks = True
    visible = sim.units
    assert len(visible) == 2
