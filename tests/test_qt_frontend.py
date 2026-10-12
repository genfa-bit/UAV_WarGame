import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtQuick import QQuickItem

from ui.qt_app import create_engine


def _visual_items(item):
    result = []
    for child in item.childItems():
        result.append(child)
        result.extend(_visual_items(child))
    return result


def test_qml_frontend_loads_and_renders_all_units():
    app, engine, view_model = create_engine()
    app.processEvents()

    assert engine.rootObjects()
    assert view_model.unitModel.rowCount() == len(view_model.snapshot["units"])

    root = engine.rootObjects()[0]
    repeater = root.findChild(QQuickItem, "unitRepeater")
    assert repeater is not None
    assert repeater.property("count") == len(view_model.snapshot["units"])
    delegates = [
        item for item in repeater.parentItem().childItems()
        if item.objectName().startswith("unit-")
    ]
    assert len(delegates) == len(view_model.snapshot["units"])
    assert len({round(item.x()) for item in delegates}) > 2


def test_qml_unit_obstacle_and_base_icons_render():
    app, engine, view_model = create_engine()
    root = engine.rootObjects()[0]
    root.show()
    for _ in range(30):
        app.processEvents()

    repeater = root.findChild(QQuickItem, "unitRepeater")
    items = _visual_items(repeater.parentItem())
    unit_icons = [
        item for item in items if item.objectName().startswith("unitIcon-")
    ]
    obstacle_icons = [
        item for item in items if item.objectName().startswith("obstacleIcon-")
    ]
    base_icons = [
        item for item in items if item.objectName().startswith("baseIcon-")
    ]

    assert len(unit_icons) == len(view_model.snapshot["units"])
    assert len(obstacle_icons) == len(view_model.snapshot["map"]["obstacles"])
    assert len(base_icons) == 2
    assert all(item.property("paintedWidth") > 0 for item in unit_icons)
    assert all(item.property("paintedWidth") > 0 for item in obstacle_icons)
    assert all(item.property("paintedWidth") > 0 for item in base_icons)
    # Map glyphs shrink at the fitted scale so dense deployments stay readable.
    # They remain visible and keep a bounded size when the camera zooms in.
    fitted_widths = [item.width() for item in unit_icons]
    assert all(20 <= width <= 45 for width in fitted_widths)
    viewport = root.findChild(QQuickItem, "mapViewport")
    viewport.setProperty("zoomLevel", 3.0)
    app.processEvents()
    assert all(
        fitted <= icon.width() <= 45
        for fitted, icon in zip(fitted_widths, unit_icons)
    )
    base_backdrops = [
        item for item in items if item.objectName().startswith("baseBackdrop-")
    ]
    assert len(base_backdrops) == 2
    assert all(item.property("outlineWidth") == 0 for item in base_backdrops)


def test_attack_canvas_caches_event_for_short_animation():
    app, engine, view_model = create_engine()
    root = engine.rootObjects()[0]
    attack_canvas = root.findChild(QQuickItem, "attackCanvas")
    units = {unit["id"]: unit for unit in view_model.snapshot["units"]}
    attacker = units["R-MV-1"]
    target = units["B-MV-1"]
    view_model._snapshot["attack_events"] = [{
        "event_id": "test-missile",
        "attacker_id": attacker["id"],
        "target_id": target["id"],
        "start": [attacker["x"], attacker["y"]],
        "end": [target["x"], target["y"]],
        "damage": 34,
        "target_hp": 56,
        "target_destroyed": False,
        "critical": False,
        "miss": False,
        "life": 8,
    }]
    view_model.snapshotChanged.emit()
    app.processEvents()

    assert len(attack_canvas.property("displayedEvents").toVariant()) == 1

    started = time.monotonic()
    while time.monotonic() - started < 0.22:
        app.processEvents()
        time.sleep(0.01)

    assert len(attack_canvas.property("displayedEvents").toVariant()) == 1

    while time.monotonic() - started < 0.62:
        app.processEvents()
        time.sleep(0.01)

    assert attack_canvas.property("displayedEvents").toVariant() == []

    view_model._snapshot["attack_events"] = []
    view_model.snapshotChanged.emit()
    app.processEvents()
    view_model._snapshot["attack_events"] = [{
        "event_id": "test-missile",
        "attacker_id": attacker["id"],
        "target_id": target["id"],
        "attacker_team": attacker["team"],
        "attacker_type": attacker["unit_type"],
        "start": [attacker["x"], attacker["y"]],
        "end": [target["x"], target["y"]],
        "damage": 20,
        "target_hp": 36,
        "target_destroyed": False,
        "critical": False,
        "miss": False,
        "life": 8,
    }]
    view_model.snapshotChanged.emit()
    app.processEvents()

    assert len(attack_canvas.property("displayedEvents").toVariant()) == 1
