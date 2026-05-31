"""基地拖动功能测试。"""

from core.battlefield import Battlefield
from core.obstacle_editor import MapEditor


def _battlefield():
    return Battlefield(800, 600, red_base=(80, 300), blue_base=(720, 300))


def test_hit_red_base():
    bf = _battlefield()
    editor = MapEditor(bf)
    assert editor.hit_base(80, 300) == "red"


def test_hit_blue_base():
    bf = _battlefield()
    editor = MapEditor(bf)
    assert editor.hit_base(720, 300) == "blue"


def test_hit_base_miss():
    bf = _battlefield()
    editor = MapEditor(bf)
    assert editor.hit_base(400, 300) is None


def test_drag_red_base():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_base("red")
    editor.update_drag_base(150, 250)
    editor.finish_drag_base()

    assert bf.red_base == (150, 250)


def test_drag_blue_base():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_base("blue")
    editor.update_drag_base(600, 350)
    editor.finish_drag_base()

    assert bf.blue_base == (600, 350)


def test_drag_base_clamped():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_base("red")
    editor.update_drag_base(-50, 700)
    editor.finish_drag_base()

    assert bf.red_base[0] == 0
    assert bf.red_base[1] == 600


def test_finish_drag_base_clears_state():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_base("red")
    editor.finish_drag_base()

    assert editor.state.dragging_base is None
