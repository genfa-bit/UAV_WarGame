"""Map imagery and camera integration through real Qt pointer events."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from ui import qt_models
from ui.qt_app import create_engine


def settle(app, predicate=lambda: True):
    deadline = time.monotonic() + 2
    for _ in range(8):
        app.processEvents()
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.fixture
def map_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    monkeypatch.setattr(qt_models, "QSettings", lambda *_: QSettings(
        str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    app, engine, model = create_engine(show_first_help=False)
    assert engine.rootObjects()
    root = engine.rootObjects()[0]
    root.resize(1280, 720)
    settle(app)
    viewport = root.findChild(QQuickItem, "mapViewport")
    layer = root.findChild(QQuickItem, "battlefieldLayer")
    assert viewport and layer
    yield app, root, model, viewport, layer
    model._timer.stop()
    root.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def wheel(app, root, viewport, delta=120):
    position = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2))
    event = QWheelEvent(position, position, QPoint(), QPoint(0, delta),
                        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QCoreApplication.sendEvent(root, event)
    settle(app)
    return position


@pytest.mark.parametrize("scene", ["standard", "obstacles", "valley", "river_city"])
def test_each_imagery_scene_loads_a_local_background(map_ui, scene):
    app, root, model, viewport, layer = map_ui
    model.loadScenario(scene)
    image = root.findChild(QObject, "terrainImage")
    assert image
    settle(app, lambda: bool(image.property("imageReady")))
    source = image.property("source").toString()
    assert "assets/maps/terrain_" in source
    assert model.snapshot["map"]["visual"]["landmarks"]
    assert not root.grabWindow().isNull()


def test_background_choice_is_deployment_only_and_survives_loading(map_ui, tmp_path):
    app, root, model, viewport, layer = map_ui
    model.setMapStyle("valley")
    assert model.snapshot["map"]["style"] == "valley"
    path = tmp_path / "地图 背景.json"
    assert model.controller.save_map(path).ok
    model.setMapStyle("tactical")
    assert model.controller.load_map(path).ok
    model.refresh()
    assert model.snapshot["map"]["style"] == "valley"
    model.startSimulation()
    model.togglePause()
    model.setMapStyle("river")
    assert model.snapshot["map"]["style"] == "valley"


def test_wheel_zoom_preserves_center_world_coordinate_and_fit_restores_view(map_ui):
    app, root, model, viewport, layer = map_ui
    position = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2))

    def world_point():
        local = layer.mapFromScene(position)
        scale = viewport.property("scaleFactor")
        return local.x() / scale, local.y() / scale

    before = world_point()
    wheel(app, root, viewport, 480)
    assert viewport.property("zoomLevel") > 1
    assert world_point() == pytest.approx(before, abs=1)
    for _ in range(12):
        wheel(app, root, viewport, 480)
    assert viewport.property("zoomLevel") <= 4
    button = root.findChild(QQuickItem, "mapFit")
    assert button
    center = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, center)
    settle(app)
    assert viewport.property("zoomLevel") == pytest.approx(1)
    assert viewport.property("panX") == pytest.approx(0)
    assert viewport.property("panY") == pytest.approx(0)


def test_zoomed_mouse_deployment_uses_the_displayed_world_coordinate(map_ui):
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    settle(app)
    wheel(app, root, viewport, 480)
    scale = viewport.property("scaleFactor")
    position = layer.mapToScene(QPointF(350 * scale, 260 * scale)).toPoint()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position)
    settle(app, lambda: len(model.snapshot["units"]) == 1)
    placed = model.snapshot["units"][0]
    assert placed["x"] == pytest.approx(350, abs=2)
    assert placed["y"] == pytest.approx(260, abs=2)


def test_middle_drag_pans_without_editing_deployment(map_ui):
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    settle(app)
    wheel(app, root, viewport, 960)
    before = (viewport.property("panX"), viewport.property("panY"))
    start = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2)).toPoint()
    QTest.mousePress(root, Qt.MiddleButton, Qt.NoModifier, start)
    QTest.mouseMove(root, start + QPoint(55, 30))
    QTest.mouseRelease(root, Qt.MiddleButton, Qt.NoModifier, start + QPoint(55, 30))
    settle(app)
    after = (viewport.property("panX"), viewport.property("panY"))
    assert after != before
    assert model.snapshot["units"] == []
    assert model.snapshot["map"]["obstacles"] == []


def test_runtime_unit_click_after_zoom_selects_the_visible_unit(map_ui):
    app, root, model, viewport, layer = map_ui
    model.loadScenario("valley")
    model.startSimulation()
    model.togglePause()
    # The center-facing ground unit is accessible when viewing its half of the map.
    target = model.snapshot["units"][2]
    wheel(app, root, viewport, 480)
    overview = root.findChild(QQuickItem, "mapOverview")
    # Move the camera to the red half through the overview's actual click area.
    position = overview.mapToScene(QPointF(overview.width() * 0.2,
                                          21 + (overview.height() - 25) * 0.5)).toPoint()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position)
    settle(app)
    scale = viewport.property("scaleFactor")
    point = layer.mapToScene(QPointF(target["x"] * scale, target["y"] * scale)).toPoint()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
    settle(app, lambda: model.selectedUnitId == target["id"])
    assert model.selectedUnit["id"] == target["id"]
    assert model.snapshot["statistics"]["time_step"] == 0


def pan_value(viewport):
    return viewport.property("panX"), viewport.property("panY")


def drag_left(app, root, start, offset=QPoint(45, 28), hold_ms=0):
    """按下左键后拖动。hold_ms=0 表示按下立即移动（不等待）。"""
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
    if hold_ms:
        QTest.qWait(hold_ms)
    QTest.mouseMove(root, start + offset)
    settle(app)
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, start + offset)
    settle(app)


def test_left_drag_pans_immediately_in_runtime_without_selecting_unit(map_ui):
    """运行态在单位上按下并立即拖动：无需先按住，逐步跟随光标且不选中单位。"""
    app, root, model, viewport, layer = map_ui
    model.loadScenario("valley")
    model.startSimulation()
    model.togglePause()
    target = model.snapshot["units"][2]
    wheel(app, root, viewport, 480)
    overview = root.findChild(QQuickItem, "mapOverview")
    position = overview.mapToScene(QPointF(overview.width() * 0.2,
                                          21 + (overview.height() - 25) * 0.5)).toPoint()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position)
    settle(app)
    scale = viewport.property("scaleFactor")
    point = layer.mapToScene(QPointF(target["x"] * scale, target["y"] * scale)).toPoint()
    # 先确认取样点确实落在该单位上
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
    settle(app, lambda: model.selectedUnitId == target["id"])
    model.selectUnit("")
    settle(app, lambda: model.selectedUnitId == "")
    before = pan_value(viewport)
    # 向左拖动：小地图定位把 panX 推到边界，向右已无空间，向左才有增量可比对
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, point)
    for step in range(1, 4):
        QTest.mouseMove(root, point + QPoint(-15 * step, 9 * step))
        settle(app)
        pan = pan_value(viewport)
        assert pan[0] - before[0] == pytest.approx(-15 * step, abs=1), f"第 {step} 步未跟随光标：{pan}"
        assert pan[1] - before[1] == pytest.approx(9 * step, abs=1), f"第 {step} 步未跟随光标：{pan}"
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, point + QPoint(-45, 27))
    settle(app)
    assert model.selectedUnitId == ""


def test_left_drag_pans_immediately_in_deployment_without_editing(map_ui):
    """部署态在空白处按下（未选障碍类型）立即拖动即平移，不放置单位。"""
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    assert model.snapshot["deployment"]["selected_obstacle_type"] == ""
    settle(app)
    wheel(app, root, viewport, 960)
    scale = viewport.property("scaleFactor")
    start = layer.mapToScene(QPointF(300 * scale, 240 * scale)).toPoint()
    before = pan_value(viewport)
    drag_left(app, root, start)
    assert pan_value(viewport) != before
    assert model.snapshot["units"] == []
    assert model.snapshot["map"]["obstacles"] == []
    message = model.snapshot["message"]
    assert "正在创建" not in message and "已部署" not in message


def test_left_drag_pan_tracks_every_move_step(map_ui):
    """平移增量必须等于光标位移：逐步推进时每一步都要跟上，不能停一步跳一步。"""
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    settle(app)
    wheel(app, root, viewport, 960)
    start = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2)).toPoint()
    step = QPoint(12, 9)
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
    before = pan_value(viewport)
    travelled = QPoint()
    for index in range(5):
        travelled += step
        QTest.mouseMove(root, start + travelled)
        settle(app)
        pan = pan_value(viewport)
        assert pan[0] - before[0] == pytest.approx(travelled.x(), abs=1), (
            f"第 {index + 1} 步未跟随光标：{pan}")
        assert pan[1] - before[1] == pytest.approx(travelled.y(), abs=1), (
            f"第 {index + 1} 步未跟随光标：{pan}")
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, start + travelled)
    settle(app)
    assert model.snapshot["units"] == [] and model.snapshot["map"]["obstacles"] == []


def test_left_hold_then_drag_pans_instead_of_creating_obstacle(map_ui):
    """选了障碍类型时按下已经开始拉框创建：需先按住不动再拖动才改判为平移。"""
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    model.selectObstacleType("building")
    settle(app)
    wheel(app, root, viewport, 960)
    start = viewport.mapToScene(QPointF(viewport.width() / 2, viewport.height() / 2)).toPoint()
    before = pan_value(viewport)
    drag_left(app, root, start, hold_ms=420)
    assert pan_value(viewport) != before
    assert model.snapshot["map"]["obstacles"] == []
    message = model.snapshot["message"]
    assert "正在创建" not in message and "已创建" not in message and "过小" not in message


def test_quick_left_click_still_places_unit(map_ui):
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    model.selectUnitType("scout_drone")
    settle(app)
    wheel(app, root, viewport, 480)
    scale = viewport.property("scaleFactor")
    point = layer.mapToScene(QPointF(350 * scale, 260 * scale)).toPoint()
    before = pan_value(viewport)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point)
    settle(app, lambda: len(model.snapshot["units"]) == 1)
    assert pan_value(viewport) == before


def test_hold_release_without_moving_still_places_unit(map_ui):
    """按住不动再松开仍然是点击放置，不能被平移判定吞掉。"""
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    model.selectUnitType("scout_drone")
    settle(app)
    wheel(app, root, viewport, 480)
    scale = viewport.property("scaleFactor")
    point = layer.mapToScene(QPointF(350 * scale, 260 * scale)).toPoint()
    before = pan_value(viewport)
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, point)
    QTest.qWait(420)
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, point)
    settle(app, lambda: len(model.snapshot["units"]) == 1)
    assert pan_value(viewport) == before


def test_left_drag_still_edits_when_map_fits_the_window(map_ui):
    """适应地图时没有可平移空间，左键拖动仍应完成部署编辑。"""
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    model.selectObstacleType("building")
    settle(app)
    assert viewport.property("zoomLevel") == pytest.approx(1)
    scale = viewport.property("scaleFactor")
    start = layer.mapToScene(QPointF(260 * scale, 200 * scale)).toPoint()
    end = layer.mapToScene(QPointF(430 * scale, 320 * scale)).toPoint()
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(root, end)
    settle(app)
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, end)
    settle(app, lambda: len(model.snapshot["map"]["obstacles"]) == 1)
    assert pan_value(viewport) == (0.0, 0.0)


def test_left_drag_without_hold_still_creates_obstacle(map_ui):
    app, root, model, viewport, layer = map_ui
    model.loadScenario("custom")
    model.selectObstacleType("building")
    settle(app)
    wheel(app, root, viewport, 480)
    scale = viewport.property("scaleFactor")
    start = layer.mapToScene(QPointF(260 * scale, 200 * scale)).toPoint()
    end = layer.mapToScene(QPointF(430 * scale, 320 * scale)).toPoint()
    before = pan_value(viewport)
    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(root, end)
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, end)
    settle(app, lambda: len(model.snapshot["map"]["obstacles"]) == 1)
    assert pan_value(viewport) == before


@pytest.mark.parametrize("size", [(920, 540), (1280, 720)])
def test_map_navigation_and_overview_fit_compact_windows(map_ui, size):
    app, root, model, viewport, layer = map_ui
    root.resize(*size)
    settle(app)
    for name in ("mapZoomIn", "mapZoomOut", "mapFit", "mapOverview"):
        item = root.findChild(QQuickItem, name)
        assert item and item.isVisible()
        origin = item.mapToScene(QPointF())
        assert origin.x() >= 0 and origin.y() >= 0
        assert origin.x() + item.width() <= root.width() + 1
        assert origin.y() + item.height() <= root.height() + 1
