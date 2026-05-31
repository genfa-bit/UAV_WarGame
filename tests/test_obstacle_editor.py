"""障碍物编辑功能测试。"""

from core.battlefield import Battlefield, Obstacle
from core.obstacle_editor import MapEditor


def _battlefield():
    return Battlefield(800, 600, obstacles=[
        Obstacle(100, 100, 80, 60, name="测试障碍物", type="building"),
    ])


def _units():
    from core.units import ScoutDrone, StrikeDrone
    return [
        ScoutDrone(id="R-1", name="红-侦察", team="red", x=50, y=50),
        StrikeDrone(id="B-1", name="蓝-打击", team="blue", x=700, y=100),
    ]


# ── 障碍物创建 ──

def test_create_obstacle():
    bf = _battlefield()
    editor = MapEditor(bf)
    initial = len(bf.obstacles)

    editor.start_create_obstacle(200, 200)
    editor.update_create_obstacle(350, 300)
    result = editor.finish_create_obstacle(350, 300, "building")

    assert result is not None
    assert len(bf.obstacles) == initial + 1


def test_create_obstacle_too_small():
    bf = _battlefield()
    editor = MapEditor(bf)
    initial = len(bf.obstacles)

    editor.start_create_obstacle(200, 200)
    result = editor.finish_create_obstacle(205, 205, "building")

    assert result is None
    assert len(bf.obstacles) == initial


def test_create_obstacle_overlap():
    bf = _battlefield()
    editor = MapEditor(bf)
    initial = len(bf.obstacles)

    # 尝试在已有障碍物上创建
    editor.start_create_obstacle(100, 100)
    result = editor.finish_create_obstacle(180, 160, "building")

    assert result is None
    assert len(bf.obstacles) == initial


# ── 命中检测 ──

def test_hit_obstacle():
    bf = _battlefield()
    editor = MapEditor(bf)

    idx = editor.hit_obstacle(140, 130)
    assert idx == 0


def test_hit_obstacle_miss():
    bf = _battlefield()
    editor = MapEditor(bf)

    idx = editor.hit_obstacle(50, 50)
    assert idx is None


def test_hit_unit():
    bf = _battlefield()
    editor = MapEditor(bf)
    units = _units()

    idx = editor.hit_unit(50, 50, units)
    assert idx == 0


def test_hit_unit_miss():
    bf = _battlefield()
    editor = MapEditor(bf)
    units = _units()

    idx = editor.hit_unit(400, 300, units)
    assert idx is None


def test_hit_base():
    bf = Battlefield(800, 600, red_base=(80, 300), blue_base=(720, 300))
    editor = MapEditor(bf)

    assert editor.hit_base(80, 300) == "red"
    assert editor.hit_base(720, 300) == "blue"
    assert editor.hit_base(400, 300) is None


# ── 障碍物拖拽 ──

def test_drag_obstacle():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_obstacle(0, 100, 100)
    editor.update_drag_obstacle(200, 200)
    assert editor.finish_drag_obstacle()

    obs = bf.obstacles[0]
    assert obs.x == 200
    assert obs.y == 200


def test_drag_obstacle_clamped():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_obstacle(0, 100, 100)
    editor.update_drag_obstacle(-50, -50)
    editor.finish_drag_obstacle()

    obs = bf.obstacles[0]
    assert obs.x == 0
    assert obs.y == 0


def test_drag_obstacle_overlap():
    bf = Battlefield(800, 600, obstacles=[
        Obstacle(100, 100, 80, 60, name="A", type="building"),
        Obstacle(300, 300, 80, 60, name="B", type="building"),
    ])
    editor = MapEditor(bf)

    editor.start_drag_obstacle(0, 100, 100)
    editor.update_drag_obstacle(300, 300)
    ok = editor.finish_drag_obstacle()
    assert not ok  # 与障碍物B重叠


# ── 障碍物删除 ──

def test_delete_obstacle():
    bf = _battlefield()
    editor = MapEditor(bf)
    initial = len(bf.obstacles)

    ok = editor.delete_obstacle(0)
    assert ok
    assert len(bf.obstacles) == initial - 1


def test_delete_selected():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_drag_obstacle(0, 100, 100)  # 选中
    editor.finish_drag_obstacle()
    assert editor.delete_selected()
    assert editor.state.selected_obs_idx is None


# ── Resize ──

def test_hit_resize_handle():
    bf = _battlefield()
    editor = MapEditor(bf)
    editor.state.selected_obs_idx = 0
    obs = bf.obstacles[0]

    # 右下角把手区域
    assert editor.hit_resize_handle(obs.x + obs.width, obs.y + obs.height)
    # 中间区域不是
    assert not editor.hit_resize_handle(obs.x + obs.width // 2, obs.y + obs.height // 2)


def test_start_resize():
    bf = _battlefield()
    editor = MapEditor(bf)
    editor.state.selected_obs_idx = 0

    editor.start_resize()
    assert editor.state.resizing


def test_resize_obstacle():
    bf = _battlefield()
    editor = MapEditor(bf)
    obs = bf.obstacles[0]
    editor.state.selected_obs_idx = 0

    editor.start_resize()
    editor.update_resize(obs.x + 150, obs.y + 100)
    assert editor.finish_resize()

    resized = bf.obstacles[0]
    assert resized.width == 150
    assert resized.height == 100


def test_resize_min_size():
    bf = _battlefield()
    editor = MapEditor(bf)
    editor.state.selected_obs_idx = 0

    editor.start_resize()
    editor.update_resize(bf.obstacles[0].x + 5, bf.obstacles[0].y + 5)
    editor.finish_resize()

    resized = bf.obstacles[0]
    assert resized.width >= 12
    assert resized.height >= 12


# ── 预览矩形 ──

def test_preview_rect():
    bf = _battlefield()
    editor = MapEditor(bf)

    assert editor.preview_rect is None
    editor.start_create_obstacle(100, 100)
    editor.update_create_obstacle(200, 200)

    rect = editor.preview_rect
    assert rect is not None
    assert rect[2] > 0
    assert rect[3] > 0


# ── 重叠检测 ──

def test_check_unit_overlap():
    bf = _battlefield()
    editor = MapEditor(bf)
    units = _units()

    # 太近
    assert editor.check_unit_overlap(52, 52, units)
    # 足够远
    assert not editor.check_unit_overlap(400, 300, units)


def test_check_unit_in_obstacle():
    bf = _battlefield()
    editor = MapEditor(bf)

    assert editor.check_unit_in_obstacle(140, 130, "ground")
    assert not editor.check_unit_in_obstacle(140, 130, "air")


def test_check_obstacle_overlap():
    bf = _battlefield()
    editor = MapEditor(bf)

    # 与已有障碍物重叠
    assert editor.check_obstacle_overlap((120, 120, 40, 40))
    # 不重叠
    assert not editor.check_obstacle_overlap((300, 300, 40, 40))
    # 排除自身
    assert not editor.check_obstacle_overlap((100, 100, 80, 60), exclude_idx=0)


def test_cancel_clears_state():
    bf = _battlefield()
    editor = MapEditor(bf)

    editor.start_create_obstacle(100, 100)
    editor.cancel()

    assert not editor.state.creating
    assert editor.preview_rect is None
    assert not editor.state.is_active
