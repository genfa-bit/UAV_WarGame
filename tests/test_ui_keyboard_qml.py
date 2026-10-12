"""Keyboard behavior across native controls, modal dialogs, and the map."""

import os
from copy import deepcopy

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPointF, QSettings, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from ui import qt_models
from ui.qt_app import create_engine


def settle(app):
    for _ in range(8):
        app.processEvents()
        QTest.qWait(3)


def click(app, root, item):
    assert item and item.isVisible() and item.isEnabled()
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point.toPoint())
    settle(app)


@pytest.fixture
def keyboard_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    monkeypatch.setattr(qt_models, "QSettings", lambda *_: QSettings(
        str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    app, engine, model = create_engine(show_first_help=False)
    assert engine.rootObjects(), "QML failed to load"
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(error.toString() for error in warnings))
    root = engine.rootObjects()[0]
    root.resize(1280, 720)
    root.show()
    root.requestActivate()
    settle(app)
    yield app, root, model
    model._timer.stop()
    root.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not errors, "\n".join(errors)


def pause_new_run(app, model):
    model.startSimulation()
    model.togglePause()
    settle(app)
    assert model.snapshot["game_state"] == "paused"


def battle_statistics(model):
    # Pause/resume adds a legitimate lifecycle record without advancing battle.
    return {key: value for key, value in model.snapshot["statistics"].items()
            if key != "record_count"}


def test_focused_step_button_space_advances_once_and_remains_paused(keyboard_ui):
    app, root, model = keyboard_ui
    pause_new_run(app, model)
    button = root.findChild(QQuickItem, "stepSimulationButton")
    assert button is not None
    button.forceActiveFocus(Qt.TabFocusReason)
    settle(app)
    assert button.hasActiveFocus()

    QTest.keyClick(root, Qt.Key_Space)
    settle(app)

    assert model.snapshot["statistics"]["time_step"] == 1
    assert model.snapshot["game_state"] == "paused"
    assert not model._timer.isActive()


@pytest.mark.parametrize("button_name,dialog_name", [
    ("timingButton", "timingDialog"),
    ("recordsButton", "recordsDialog"),
])
def test_focused_top_button_space_only_opens_its_dialog(keyboard_ui, button_name, dialog_name):
    app, root, model = keyboard_ui
    pause_new_run(app, model)
    button = root.findChild(QQuickItem, button_name)
    button.forceActiveFocus(Qt.TabFocusReason)
    settle(app)
    assert button.hasActiveFocus()
    before = deepcopy(battle_statistics(model))

    QTest.keyClick(root, Qt.Key_Space)
    settle(app)

    assert root.findChild(QObject, dialog_name).property("visible")
    assert model.snapshot["game_state"] == "paused"
    assert battle_statistics(model) == before
    assert not model._timer.isActive()


@pytest.mark.parametrize("previous_action", ["timingButton", "recordsButton", "sidebar"])
def test_map_click_restores_space_shortcut_after_control_focus(keyboard_ui, previous_action):
    app, root, model = keyboard_ui
    pause_new_run(app, model)
    if previous_action == "sidebar":
        button = next(item for item in root.findChildren(QQuickItem)
                      if item.isVisible() and "残骸" in str(item.property("text") or "")
                      and item.metaObject().indexOfSignal("clicked()") >= 0)
        click(app, root, button)
    else:
        click(app, root, root.findChild(QQuickItem, previous_action))
        dialog_name = "timingDialog" if previous_action == "timingButton" else "recordsDialog"
        assert root.findChild(QObject, dialog_name).property("visible")
        QTest.keyClick(root, Qt.Key_Escape)
        settle(app)
        assert not root.findChild(QObject, dialog_name).property("visible")
    target = deepcopy(model.snapshot["units"][0])
    before = deepcopy(battle_statistics(model))
    viewport = root.findChild(QQuickItem, "mapViewport")
    layer = root.findChild(QQuickItem, "battlefieldLayer")
    scale = viewport.property("scaleFactor")
    point = layer.mapToScene(QPointF(target["x"] * scale, target["y"] * scale))

    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, point.toPoint())
    settle(app)
    assert model.selectedUnitId == target["id"]
    assert battle_statistics(model) == before
    QTest.keyClick(root, Qt.Key_Space)
    model._timer.stop()
    settle(app)
    assert model.snapshot["game_state"] == "running"
    assert not root.property("dialogActive")
    assert battle_statistics(model) == before
    QTest.keyClick(root, Qt.Key_Space)
    settle(app)
    assert model.snapshot["game_state"] == "paused"
    assert battle_statistics(model) == before
    assert model.selectedUnitId == target["id"]


@pytest.mark.parametrize("state", ["deployment", "paused"])
def test_numeric_field_input_does_not_trigger_main_shortcuts(keyboard_ui, state):
    app, root, model = keyboard_ui
    if state == "paused":
        pause_new_run(app, model)
    click(app, root, root.findChild(QQuickItem, "timingButton"))
    field = root.findChild(QQuickItem, "stepDurationField")
    field.forceActiveFocus(Qt.TabFocusReason)
    settle(app)
    before = deepcopy({key: model.snapshot[key] for key in (
        "game_state", "statistics", "deployment", "speed_label", "units", "timing")})

    QTest.keyClick(root, Qt.Key_A, Qt.ControlModifier)
    for key in (Qt.Key_1, Qt.Key_Period, Qt.Key_2, Qt.Key_5):
        QTest.keyClick(root, key)
    settle(app)
    assert field.property("text") == "1.25"
    for key in (Qt.Key_Space, Qt.Key_S, Qt.Key_F, Qt.Key_R, Qt.Key_T, Qt.Key_Return):
        QTest.keyClick(root, key)
        settle(app)
        assert {name: model.snapshot[name] for name in before} == before
        assert root.findChild(QObject, "timingDialog").property("visible")
