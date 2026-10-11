"""QML integration checks for results, selection and compact window layouts."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import pytest
from PySide6.QtCore import (QCoreApplication, QEvent, QMetaObject, QObject,
                            QPointF, QSettings, Qt)
from PySide6.QtQuick import QQuickItem

from ui import qt_models
from ui.qt_app import create_engine


def _wait_for(app, predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "QML did not reach the expected state"


def _variant(value):
    return value.toVariant() if hasattr(value, "toVariant") else value


@pytest.fixture
def qml_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    monkeypatch.setattr(qt_models, "QSettings", lambda *_: QSettings(
        str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    app, engine, model = create_engine(show_first_help=False)
    assert engine.rootObjects(), "QML failed to load"
    root = engine.rootObjects()[0]
    root.show()
    for _ in range(8):
        app.processEvents()
    yield app, root, model
    model._timer.stop()
    root.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _finish_run(model, winner, cause):
    simulator = model.controller.simulator
    losing_teams = ["blue"] if winner == "red" else ["red"] if winner == "blue" else ["red", "blue"]
    for team in losing_teams:
        if cause == "base":
            base = simulator.battlefield.base_obj(team)
            base.take_damage(base.hp)
        else:
            for unit in simulator.units:
                if unit.team == team:
                    unit.take_damage(unit.hp)
    # The real simulator determines the winner and the controller finishes the run.
    model.stepSimulation()
    assert simulator.winner == winner
    assert model.snapshot["game_state"] == "finished"


@pytest.mark.parametrize("winner", ["red", "blue", "draw"])
@pytest.mark.parametrize("cause", ["units", "base"])
def test_real_battle_result_opens_once_and_reopens_for_next_run(qml_workflow, winner, cause):
    app, root, model = qml_workflow
    dialog = root.findChild(QObject, "resultsDialog")
    assert dialog is not None
    assert not dialog.property("visible")
    model.startSimulation()
    model.togglePause()

    _finish_run(model, winner, cause)
    _wait_for(app, lambda: bool(dialog.property("visible")))

    stats = _variant(dialog.property("stats"))
    assert stats["winner"] == winner
    assert stats["time_step"] == 1
    winner_text = {"red": "红方获胜", "blue": "蓝方获胜", "draw": "双方平局"}[winner]
    assert any(child.property("text") == winner_text for child in dialog.findChildren(QObject))
    assert root.property("resultPresented")
    assert not model._timer.isActive()

    assert QMetaObject.invokeMethod(dialog, "returnToMap", Qt.DirectConnection)
    _wait_for(app, lambda: not dialog.property("visible"))
    model.refresh()
    for _ in range(6):
        app.processEvents()
    assert not dialog.property("visible")
    assert model.snapshot["game_state"] == "finished"

    model.restartSimulation()
    model.togglePause()
    _wait_for(app, lambda: not root.property("resultPresented"))
    _finish_run(model, winner, cause)
    _wait_for(app, lambda: bool(dialog.property("visible")))
    assert _variant(dialog.property("stats"))["winner"] == winner


def test_selected_unit_details_follow_live_model_and_clear_selection(qml_workflow):
    app, root, model = qml_workflow
    controls = root.findChild(QQuickItem, "workflowControls")
    details = root.findChild(QQuickItem, "unitDetails")
    assert controls is not None and controls.isVisible()
    assert details is not None
    model.startSimulation()
    model.togglePause()
    first = model.snapshot["units"][0]
    model.pointerPress(1, first["x"], first["y"])
    _wait_for(app, lambda: bool(details.property("hasUnit")))
    assert _variant(details.property("unit"))["id"] == first["id"]
    assert root.property("selectedUnitId") == first["id"]
    live_unit = next(unit for unit in model.controller.simulator.units if unit.id == first["id"])
    live_unit.hp -= 9
    live_unit.ammo -= 1

    model.stepSimulation()
    _wait_for(app, lambda: _variant(details.property("unit"))["hp"] == live_unit.hp)

    shown = _variant(details.property("unit"))
    assert shown["ammo"] == live_unit.ammo
    assert shown["x"] == live_unit.x
    assert shown["y"] == live_unit.y
    assert shown["engagement"] == live_unit.engagement_state.phase_name
    assert controls.isVisible()
    assert QMetaObject.invokeMethod(details, "clearSelection", Qt.DirectConnection)
    _wait_for(app, lambda: not details.property("hasUnit"))
    assert model.selectedUnitId == ""


def _assert_item_inside_window(item, root):
    origin = item.mapToScene(QPointF(0, 0))
    assert item.width() > 0 and item.height() > 0
    assert origin.x() >= -1
    assert origin.y() >= -1
    assert origin.x() + item.width() <= root.width() + 1
    assert origin.y() + item.height() <= root.height() + 1


def _visual_children(item):
    children = []
    for child in item.childItems():
        children.append(child)
        children.extend(_visual_children(child))
    return children


@pytest.mark.parametrize("size", [(1280, 720), (920, 540)])
def test_scene_selector_controls_and_result_fit_common_window_sizes(qml_workflow, size):
    app, root, model = qml_workflow
    root.setWidth(size[0])
    root.setHeight(size[1])
    for _ in range(10):
        app.processEvents()
    assert (root.width(), root.height()) == size
    controls = root.findChild(QQuickItem, "workflowControls")
    selector = root.findChild(QQuickItem, "scenarioSelector")
    assert controls is not None and controls.isVisible()
    assert selector is not None and selector.isVisible()
    _assert_item_inside_window(controls, root)
    _assert_item_inside_window(selector, root)
    # Check actual clickable rectangles as well as their surrounding footer.
    buttons = [item for item in _visual_children(controls)
               if item.metaObject().indexOfSignal("clicked()") >= 0 and item.isVisible()]
    assert len(buttons) >= 8
    for button in buttons:
        _assert_item_inside_window(button, root)

    model.startSimulation()
    model.togglePause()
    _finish_run(model, "draw", "base")
    dialog = root.findChild(QObject, "resultsDialog")
    _wait_for(app, lambda: bool(dialog.property("visible")))
    assert dialog.property("width") <= root.width() - 40
    assert dialog.property("height") <= root.height() - 40
    assert dialog.property("x") >= 0 and dialog.property("y") >= 0
    assert dialog.property("x") + dialog.property("width") <= root.width()
    assert dialog.property("y") + dialog.property("height") <= root.height()
