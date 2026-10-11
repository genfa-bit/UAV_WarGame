"""Exercise timing and structured-record controls through the rendered QML UI."""

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import pytest
from PySide6.QtCore import (Q_ARG, QCoreApplication, QEvent, QMetaObject, QObject,
                            QPointF, QSettings, Qt, QUrl)
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from ui import qt_models
from ui.qt_app import create_engine


def _wait(app, predicate, timeout=1.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    assert predicate(), "QML did not reach the expected state"


def _click(app, root, item):
    assert item is not None and item.isVisible() and item.isEnabled()
    position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    assert 0 <= position.x() <= root.width()
    assert 0 <= position.y() <= root.height()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position.toPoint())
    app.processEvents()


def _visual_texts(item):
    texts = [str(item.property("text"))]
    for child in item.childItems():
        texts.extend(_visual_texts(child))
    return texts


@pytest.fixture
def timing_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    monkeypatch.setattr(qt_models, "QSettings", lambda *_: QSettings(
        str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    app, engine, model = create_engine(show_first_help=False)
    assert engine.rootObjects(), "QML failed to load"
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(error.toString() for error in warnings))
    root = engine.rootObjects()[0]
    root.show()
    QTest.qWait(25)
    yield app, root, model
    model._timer.stop()
    root.close()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not errors, "\n".join(errors)


def test_timing_fields_apply_from_deployment_and_paused(timing_ui):
    app, root, model = timing_ui
    dialog = root.findChild(QObject, "timingDialog")
    duration = root.findChild(QQuickItem, "stepDurationField")
    limit = root.findChild(QQuickItem, "maxStepsField")
    apply_button = root.findChild(QQuickItem, "applyTimingButton")
    _click(app, root, root.findChild(QQuickItem, "timingButton"))
    _wait(app, lambda: dialog.property("visible"))
    duration.setProperty("text", "0.5")
    limit.setProperty("text", "40")
    _click(app, root, apply_button)
    _wait(app, lambda: not dialog.property("visible"))
    assert model.snapshot["timing"]["step_duration_seconds"] == 0.5
    assert model.snapshot["timing"]["max_steps"] == 40

    model.startSimulation()
    model.togglePause()
    model.stepSimulation()
    assert model.snapshot["statistics"]["elapsed_seconds"] == 0.5
    _click(app, root, root.findChild(QQuickItem, "timingButton"))
    _wait(app, lambda: dialog.property("visible"))
    duration.setProperty("text", "1.25")
    limit.setProperty("text", "80")
    _click(app, root, apply_button)
    _wait(app, lambda: not dialog.property("visible"))
    model.stepSimulation()
    assert model.snapshot["statistics"]["elapsed_seconds"] == 1.75
    assert model.snapshot["timing"]["max_steps"] == 80


def test_timing_invalid_input_and_running_are_guarded(timing_ui):
    app, root, model = timing_ui
    dialog = root.findChild(QObject, "timingDialog")
    duration = root.findChild(QQuickItem, "stepDurationField")
    limit = root.findChild(QQuickItem, "maxStepsField")
    apply_button = root.findChild(QQuickItem, "applyTimingButton")
    original = dict(model.snapshot["timing"])
    _click(app, root, root.findChild(QQuickItem, "timingButton"))
    _wait(app, lambda: dialog.property("visible"))
    duration.setProperty("text", "0")
    limit.setProperty("text", "10")
    _click(app, root, apply_button)
    assert dialog.property("visible")
    assert dialog.property("validationError")
    assert model.snapshot["timing"] == original
    QMetaObject.invokeMethod(dialog, "close", Qt.DirectConnection)
    model.startSimulation()
    model._timer.stop()
    _click(app, root, root.findChild(QQuickItem, "timingButton"))
    _wait(app, lambda: dialog.property("visible"))
    assert not apply_button.isEnabled()
    assert not duration.isEnabled()
    assert not limit.isEnabled()
    assert any("请先暂停" in str(child.property("text")) for child in dialog.findChildren(QObject))


def test_records_filter_uses_structured_category_and_exports_all(timing_ui, tmp_path):
    app, root, model = timing_ui
    model.startSimulation()
    model.togglePause()
    simulator = model.controller.simulator
    # Deliberately identical text prefixes: only the structured category is authoritative.
    for index in range(205):
        simulator.record_event("sharing" if index % 2 else "scout", "same message", target_id=f"target-{index}")
    model.refresh()
    _click(app, root, root.findChild(QQuickItem, "recordsButton"))
    dialog = root.findChild(QObject, "recordsDialog")
    _wait(app, lambda: dialog.property("visible"))
    records_list = root.findChild(QQuickItem, "recordsList")
    assert records_list.property("count") == 200
    selector = root.findChild(QQuickItem, "recordCategorySelector")
    selector.setProperty("currentIndex", 2)
    assert QMetaObject.invokeMethod(selector, "activated", Qt.DirectConnection,
                                   Q_ARG(int, 2))
    _wait(app, lambda: root.property("recordFilter") == "sharing")
    records = model.snapshot["recording"]["records"]
    assert records_list.property("count") == sum(record["category"] == "sharing" for record in records)
    assert model.snapshot["recording"]["record_count"] > 200
    assert any("最近 200 条" in str(child.property("text")) for child in dialog.findChildren(QObject))
    _click(app, root, root.findChild(QQuickItem, "exportRecordsButton"))
    export_dialog = root.findChild(QObject, "exportRecordsDialog")
    _wait(app, lambda: export_dialog.property("visible"))
    export_path = tmp_path / "sharing.json"
    export_dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(export_path)))
    assert QMetaObject.invokeMethod(export_dialog, "accepted", Qt.DirectConnection)
    _wait(app, export_path.exists)
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert len(exported["records"]) == 102
    assert all(record["category"] == "sharing" for record in exported["records"])
    QMetaObject.invokeMethod(export_dialog, "close", Qt.DirectConnection)


@pytest.mark.parametrize("size", [(920, 540), (1280, 720), (1440, 900)])
def test_timing_and_records_dialogs_fit_and_remain_clickable(timing_ui, size):
    app, root, model = timing_ui
    root.setWidth(size[0])
    root.setHeight(size[1])
    QTest.qWait(25)
    model.startSimulation()
    model.togglePause()
    model.stepSimulation()
    for button_name, dialog_name, action_name in (
        ("timingButton", "timingDialog", "applyTimingButton"),
        ("recordsButton", "recordsDialog", "exportRecordsButton"),
    ):
        _click(app, root, root.findChild(QQuickItem, button_name))
        dialog = root.findChild(QObject, dialog_name)
        _wait(app, lambda: dialog.property("visible"))
        assert dialog.property("x") >= 0 and dialog.property("y") >= 0
        assert dialog.property("x") + dialog.property("width") <= root.width()
        assert dialog.property("y") + dialog.property("height") <= root.height()
        action = root.findChild(QQuickItem, action_name)
        center = action.mapToScene(QPointF(action.width() / 2, action.height() / 2))
        assert 0 <= center.x() <= root.width() and 0 <= center.y() <= root.height()
        assert action.isVisible() and action.isEnabled()
        assert not root.grabWindow().isNull()
        QMetaObject.invokeMethod(dialog, "close", Qt.DirectConnection)
        _wait(app, lambda: not dialog.property("visible"))


def test_results_and_selected_wreck_expose_destruction_time(timing_ui):
    app, root, model = timing_ui
    model.setTiming(0.5, 50)
    model.startSimulation()
    model.togglePause()
    losing = [unit for unit in model.controller.simulator.units if unit.team == "blue"]
    for unit in losing:
        unit.take_damage(unit.hp)
    model.stepSimulation()
    dialog = root.findChild(QObject, "resultsDialog")
    _wait(app, lambda: dialog.property("visible"))
    assert any("0.50 秒" in str(child.property("text")) for child in dialog.findChildren(QObject))
    destroyed = dialog.property("destroyedUnits")
    if hasattr(destroyed, "toVariant"):
        destroyed = destroyed.toVariant()
    assert len(destroyed) == len(losing)
    _wait(app, lambda: any("第 1 步" in text for text in _visual_texts(dialog.property("contentItem"))))
    _click(app, root, root.findChild(QQuickItem, "resultRecordsButton"))
    records = root.findChild(QObject, "recordsDialog")
    _wait(app, lambda: records.property("visible"))
    QMetaObject.invokeMethod(records, "close", Qt.DirectConnection)
    _wait(app, lambda: not records.property("visible"))
    unit = next(row for row in model.snapshot["units"] if row["id"] == losing[0].id)
    model.pointerPress(1, unit["x"], unit["y"])
    details = root.findChild(QQuickItem, "unitDestructionTime")
    _wait(app, lambda: details.isVisible())
    assert "第 1 步" in details.property("text")
    assert "0.50 秒" in details.property("text")
