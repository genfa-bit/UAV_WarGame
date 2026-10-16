"""回放界面（进度条、播放条、历史行、快捷键）的 QML 回归测试。"""

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

import pytest
from PySide6.QtCore import (QCoreApplication, QEvent, QMetaObject, QObject, QPointF,
                            QSettings, Qt, QUrl)
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from ui import qt_models
from ui.qt_app import create_engine


def settle(app):
    for _ in range(8):
        app.processEvents()
        QTest.qWait(3)


def _wait(app, predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    assert predicate(), "QML 未达到预期状态"


def _visual_items(item, name, found):
    """Repeater 委托的 QObject 父链挂在 Repeater 自己身上，findChild 找不到，
    所以沿视觉树收集。"""
    if item.objectName() == name:
        found.append(item)
    for child in item.childItems():
        _visual_items(child, name, found)
    return found


def history_replay_buttons(root):
    return _visual_items(root.contentItem(), "historyReplayButton", [])


def visual_texts(item, collected=None):
    collected = [] if collected is None else collected
    text = item.property("text")
    if isinstance(text, str):
        collected.append(text)
    for child in item.childItems():
        visual_texts(child, collected)
    return collected


def _click(app, root, item):
    assert item is not None and item.isVisible() and item.isEnabled()
    position = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
    assert 0 <= position.x() <= root.width()
    assert 0 <= position.y() <= root.height()
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier, position.toPoint())
    settle(app)


@contextmanager
def _running_ui(tmp_path, monkeypatch):
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
    try:
        yield app, root, model
    finally:
        model._timer.stop()
        root.close()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert not errors, "\n".join(errors)


@pytest.fixture
def replay_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    with _running_ui(tmp_path, monkeypatch) as context:
        yield context


LEGACY_RUN_ID = "20200101T000000000000Z-legacy"


@pytest.fixture
def legacy_replay_ui(tmp_path, monkeypatch):
    """历史列表在首次快照时就缓存，旧记录必须在窗口创建前落盘。"""
    runs = tmp_path / "user-data" / "runs"
    runs.mkdir(parents=True)
    legacy = {
        "schema_version": 2,
        "run_id": LEGACY_RUN_ID,
        "scene_name": "旧记录",
        "finished": True,
        "statistics": {"time_step": 12, "elapsed_seconds": 2.4, "winner": "red",
                       "red_remaining": 1, "blue_remaining": 0},
        "records": [],
    }
    (runs / f"{LEGACY_RUN_ID}.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("UAV_WARGAME_DATA_DIR", str(tmp_path / "user-data"))
    with _running_ui(tmp_path, monkeypatch) as context:
        yield context


def journal_files(model):
    return {path.name: path.read_bytes()
            for path in model.controller.recording_directory.glob("*.json")}


def finish_run(app, model, max_steps=40, duration=0.2):
    """跑完一局；QTimer 停掉后手动推进，避免测试依赖真实时钟。"""
    model.setTiming(duration, max_steps)
    model.startSimulation()
    model._timer.stop()
    while model.controller.game_state == "running":
        model.controller.advance()
    model.refresh()
    settle(app)
    assert model.snapshot["game_state"] == "finished"


def start_replay(app, root, model, max_steps=40):
    finish_run(app, model, max_steps=max_steps)
    QMetaObject.invokeMethod(root.findChild(QObject, "resultsDialog"), "close",
                             Qt.DirectConnection)
    settle(app)
    model.replayCurrentRun()
    settle(app)
    assert model.snapshot["replay"]["active"]
    assert model.snapshot["game_state"] == "replay_paused"


def test_results_dialog_replays_the_run_that_just_finished(replay_ui):
    app, root, model = replay_ui
    finish_run(app, model)
    dialog = root.findChild(QObject, "resultsDialog")
    _wait(app, lambda: dialog.property("visible"))
    runs_before = sorted(journal_files(model))
    assert runs_before

    _click(app, root, root.findChild(QQuickItem, "resultReplayButton"))

    _wait(app, lambda: model.snapshot["replay"]["active"])
    assert not dialog.property("visible")
    assert root.property("replayMode") is True
    assert model.snapshot["game_state"] == "replay_paused"
    assert model.snapshot["state_label"] == "回放暂停"
    assert model.snapshot["replay"]["cursor"] == model.snapshot["replay"]["max_step"]
    # 实时运行的按钮让位给回放条，速度档位两边共用。
    assert not root.findChild(QQuickItem, "startSimulationButton").isVisible()
    assert not root.findChild(QQuickItem, "pauseSimulationButton").isVisible()
    assert root.findChild(QQuickItem, "replayPlayButton").isVisible()
    assert root.findChild(QQuickItem, "replaySlider").isVisible()
    assert sorted(journal_files(model)) == runs_before


def test_replay_bar_play_pause_step_and_slider(replay_ui):
    app, root, model = replay_ui
    start_replay(app, root, model)
    slider = root.findChild(QQuickItem, "replaySlider")
    max_step = model.snapshot["replay"]["max_step"]
    assert slider.property("to") == max_step
    assert slider.property("value") == max_step

    # 拖动时间轴只走 onMoved，避免定时器推游标时回灌控制器。
    slider.setProperty("value", 3)
    assert QMetaObject.invokeMethod(slider, "moved", Qt.DirectConnection)
    _wait(app, lambda: model.snapshot["replay"]["cursor"] == 3)
    assert "第 3" in root.findChild(QQuickItem, "replaySliderLabel").property("text")

    play = root.findChild(QQuickItem, "replayPlayButton")
    assert play.property("text") == "播放"
    _click(app, root, play)
    _wait(app, lambda: model.snapshot["replay"]["playing"])
    assert model.snapshot["game_state"] == "replay"
    _wait(app, lambda: model.snapshot["replay"]["cursor"] > 3, timeout=2.5)

    _click(app, root, play)
    _wait(app, lambda: not model.snapshot["replay"]["playing"])
    assert model.snapshot["game_state"] == "replay_paused"
    cursor = model.snapshot["replay"]["cursor"]

    _click(app, root, root.findChild(QQuickItem, "replayStepForwardButton"))
    assert model.snapshot["replay"]["cursor"] == cursor + 1
    _click(app, root, root.findChild(QQuickItem, "replayStepBackButton"))
    assert model.snapshot["replay"]["cursor"] == cursor
    # 滑块跟着游标走：拖动写 value 后绑定不能被断开。
    _wait(app, lambda: slider.property("value") == model.snapshot["replay"]["cursor"])
    assert model.snapshot["recording"]["record_count"] == \
        len(model.controller._replay.records_up_to(cursor))

    _click(app, root, root.findChild(QQuickItem, "exitReplayButton"))
    _wait(app, lambda: not model.snapshot["replay"]["active"])
    assert model.snapshot["game_state"] == "deployment"


def test_history_row_replay_button_starts_a_replay(replay_ui):
    app, root, model = replay_ui
    finish_run(app, model, max_steps=12)
    QMetaObject.invokeMethod(root.findChild(QObject, "resultsDialog"), "close",
                             Qt.DirectConnection)
    _click(app, root, root.findChild(QQuickItem, "recordsButton"))
    dialog = root.findChild(QObject, "recordsDialog")
    _wait(app, lambda: dialog.property("visible"))

    buttons = history_replay_buttons(root)
    assert len(buttons) == 1
    _click(app, root, buttons[0])

    _wait(app, lambda: model.snapshot["replay"]["active"])
    assert not dialog.property("visible")
    assert model.snapshot["replay"]["run_id"] == model.controller._run_id


def test_legacy_history_row_is_disabled_with_an_explanation(legacy_replay_ui):
    app, root, model = legacy_replay_ui
    _click(app, root, root.findChild(QQuickItem, "recordsButton"))
    dialog = root.findChild(QObject, "recordsDialog")
    _wait(app, lambda: dialog.property("visible"))

    history = model.snapshot["recording"]["history"]
    assert [row["run_id"] for row in history] == [LEGACY_RUN_ID]
    buttons = history_replay_buttons(root)
    assert len(buttons) == 1
    assert not buttons[0].isEnabled()
    assert any("旧版本" in text for text in visual_texts(root.contentItem()))
    assert not model.snapshot["replay"]["active"]


def test_replay_shortcuts_step_seek_and_leave_replay(replay_ui):
    app, root, model = replay_ui
    # 退出回放应回到运行前的那份部署，所以先取部署态坐标。
    deployment = {row["id"]: (row["x"], row["y"]) for row in model.snapshot["units"]}
    start_replay(app, root, model)
    model.seekReplay(5)
    settle(app)

    QTest.keyClick(root, Qt.Key_Right)
    settle(app)
    assert model.snapshot["replay"]["cursor"] == 6
    QTest.keyClick(root, Qt.Key_Left)
    settle(app)
    assert model.snapshot["replay"]["cursor"] == 5

    QTest.keyClick(root, Qt.Key_Space)
    settle(app)
    assert model.snapshot["replay"]["playing"]
    QTest.keyClick(root, Qt.Key_Space)
    settle(app)
    assert model.snapshot["game_state"] == "replay_paused"

    QTest.keyClick(root, Qt.Key_Escape)
    settle(app)
    assert not root.property("replayMode")
    assert not model.snapshot["replay"]["active"]
    assert model.snapshot["game_state"] == "deployment"
    assert {row["id"]: (row["x"], row["y"]) for row in model.snapshot["units"]} == deployment


def test_toolbar_load_replay_dialog_feeds_a_record_file(replay_ui):
    app, root, model = replay_ui
    model.startSimulation()
    model.togglePause()
    settle(app)
    path = Path(model.controller._record_save_path)
    assert path.exists()
    button = root.findChild(QQuickItem, "loadReplayButton")
    assert button.isVisible() and button.isEnabled()

    dialog = root.findChild(QObject, "loadReplayDialog")
    dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, "accepted", Qt.DirectConnection)

    _wait(app, lambda: model.snapshot["replay"]["active"])
    assert model.snapshot["game_state"] == "replay_paused"
    # 回放中不再提供“载入回放…”。
    assert not button.isVisible()


def test_deployment_replay_returns_to_the_layout_being_edited(replay_ui):
    """刚启动或刚返回部署时也能看回放，退出后要回到编辑中的布局。"""
    app, root, model = replay_ui
    finish_run(app, model, max_steps=12)
    QMetaObject.invokeMethod(root.findChild(QObject, "resultsDialog"), "close",
                             Qt.DirectConnection)
    model.resetSimulation()
    settle(app)
    assert model.snapshot["game_state"] == "deployment"
    path = Path(model.controller._record_save_path)
    assert path.exists()

    button = root.findChild(QQuickItem, "loadReplayButton")
    assert button.isVisible() and button.isEnabled()
    # 部署行多出这个按钮后，窄窗口里也要留在可视区内。
    root.setWidth(920)
    root.setHeight(540)
    QTest.qWait(25)
    corner = button.mapToScene(QPointF(button.width(), button.height()))
    assert corner.x() <= root.width() and corner.y() <= root.height()

    # 返回部署后继续改布局：这份编辑不是上一局开跑前的 _run_deployment。
    moved = model.controller.deployment.deploy_units[0]
    moved.x = min(model.controller.battlefield.width - 5, moved.x + 40)
    model.refresh()
    settle(app)
    edited = {row["id"]: (row["x"], row["y"]) for row in model.snapshot["units"]}

    dialog = root.findChild(QObject, "loadReplayDialog")
    dialog.setProperty("selectedFile", QUrl.fromLocalFile(str(path)))
    assert QMetaObject.invokeMethod(dialog, "accepted", Qt.DirectConnection)
    _wait(app, lambda: model.snapshot["replay"]["active"])
    assert model.snapshot["game_state"] == "replay_paused"
    assert not button.isVisible()

    QTest.keyClick(root, Qt.Key_Escape)
    settle(app)
    assert not root.property("replayMode")
    assert model.snapshot["game_state"] == "deployment"
    assert {row["id"]: (row["x"], row["y"]) for row in model.snapshot["units"]} == edited


@pytest.mark.parametrize("size", [(920, 540), (1440, 900)])
def test_replay_bar_stays_clickable_at_every_window_size(replay_ui, size):
    app, root, model = replay_ui
    root.setWidth(size[0])
    root.setHeight(size[1])
    QTest.qWait(25)
    finish_run(app, model, max_steps=12)
    QMetaObject.invokeMethod(root.findChild(QObject, "resultsDialog"), "close",
                             Qt.DirectConnection)
    model.replayCurrentRun()
    settle(app)

    for name in ("replayPlayButton", "replayStepBackButton", "replayStepForwardButton",
                 "exitReplayButton"):
        item = root.findChild(QQuickItem, name)
        center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        assert 0 <= center.x() <= root.width() and 0 <= center.y() <= root.height()
        assert item.isVisible() and item.isEnabled()
    slider = root.findChild(QQuickItem, "replaySlider")
    assert slider.isVisible() and slider.property("to") == model.snapshot["replay"]["max_step"]
    assert not root.grabWindow().isNull()
