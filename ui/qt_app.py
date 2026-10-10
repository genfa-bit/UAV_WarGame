"""PySide6 application bootstrap."""

from __future__ import annotations

import os
import sys
import json
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl, QObject, QCoreApplication, QEvent, QMetaObject
from PySide6.QtGui import QGuiApplication, QFontDatabase, QFont
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from core.controller import SimulationController
from ui.qt_models import SimulationViewModel


QML_PATH = Path(__file__).resolve().parent / "qml" / "Main.qml"


def create_engine(
    controller: SimulationController | None = None,
    *, show_first_help: bool = True,
) -> tuple[QGuiApplication, QQmlApplicationEngine, SimulationViewModel]:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName("无人装备战争游戏仿真系统")
    app.setOrganizationName("UAV WarGame")
    # The offscreen plugin has no system font database on Windows.
    if os.name == "nt" and not QFontDatabase.families():
        font_directory = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "consola.ttf", "segoeui.ttf"):
            QFontDatabase.addApplicationFont(str(font_directory / filename))
    app.setFont(QFont("Microsoft YaHei"))

    engine = QQmlApplicationEngine()
    view_model = SimulationViewModel(controller)
    if not show_first_help:
        view_model._first_run = False
    engine.rootContext().setContextProperty("viewModel", view_model)
    engine.rootContext().setContextProperty("unitListModel", view_model.unitModel)
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    return app, engine, view_model


def run() -> int:
    smoke = "--smoke-test" in sys.argv
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app, engine, view_model = create_engine(show_first_help=not smoke)
    if not engine.rootObjects():
        return 1
    engine._view_model = view_model
    if smoke:
        return _verify_delivery(app, engine, view_model)
    return app.exec()


def _verify_delivery(app, engine, view_model) -> int:
    """Exercise packaged resources and a file round trip without a live desktop."""
    report_path = None
    if "--smoke-report" in sys.argv:
        index = sys.argv.index("--smoke-report")
        if index + 1 < len(sys.argv):
            report_path = Path(sys.argv[index + 1])
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False)),
              "checks": [], "scene_ids": []}
    root = engine.rootObjects()[0]

    def render():
        for _ in range(12):
            app.processEvents()
            time.sleep(0.01)
        frame = root.grabWindow()
        assert not frame.isNull(), "QML window did not render"
        return frame

    try:
        with tempfile.TemporaryDirectory(prefix="uav-delivery-") as directory:
            temporary = Path(directory)
            controller = view_model.controller
            root.setWidth(1280)
            root.setHeight(720)
            for scene in controller.available_scenarios():
                assert controller.select_scene(scene["id"]).ok
                view_model.refresh()
                scene_frame = render()
                if controller.snapshot()["map"]["style"] != "tactical":
                    terrain_image = root.findChild(QObject, "terrainImage")
                    assert terrain_image and terrain_image.property("imageReady"), "Terrain image failed to load"
                report["scene_ids"].append(scene["id"])
                if report_path and scene["id"] in ("standard", "obstacles", "custom", "valley", "river_city"):
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    scene_frame.save(str(report_path.with_name(f"map-{scene['id']}-1280x720.png")))
            assert controller.select_scene("valley").ok
            view_model.refresh()
            viewport = root.findChild(QObject, "mapViewport")
            overview = root.findChild(QObject, "mapOverview")
            assert viewport and overview and overview.property("visible"), "Map navigation is unavailable"
            viewport.setProperty("zoomLevel", 2.5)
            zoom_frame = render()
            assert viewport.property("scaleFactor") > viewport.property("fitScale")
            if report_path:
                zoom_frame.save(str(report_path.with_name("map-zoom-1280x720.png")))
            assert QMetaObject.invokeMethod(viewport, "resetView")
            render()
            assert viewport.property("zoomLevel") == 1
            report["checks"].append("terrain_assets_zoom_and_overview")
            assert controller.select_scene("standard").ok
            saved = temporary / "round-trip.json"
            assert controller.save_map(saved).ok
            before = controller.snapshot()["units"]
            before_style = controller.snapshot()["map"]["style"]
            assert controller.load_map(saved).ok
            assert controller.snapshot()["units"] == before
            assert controller.snapshot()["map"]["style"] == before_style
            report["checks"].append("five_scenes_and_persistent_round_trip")
            view_model.refresh()
            for width, height in ((920, 540), (1366, 768), (1280, 720)):
                root.setWidth(width)
                root.setHeight(height)
                deployment_frame = render()
                if report_path:
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    deployment_frame.save(str(report_path.with_name(f"deployment-{width}x{height}.png")))
            view_model.startSimulation()
            view_model.togglePause()
            view_model.stepSimulation()
            assert controller.simulator.time_step == 1
            view_model.selectUnit(view_model.snapshot["units"][0]["id"])
            assert view_model.selectedUnit
            if report_path:
                render().save(str(report_path.with_name("unit-details-1280x720.png")))
            report["checks"].append("start_pause_step_and_unit_details")
            for unit in controller.simulator.units:
                if unit.team == "blue":
                    unit.hp = 0
            view_model.stepSimulation()
            assert view_model.snapshot["game_state"] == "finished"
            assert view_model.snapshot["statistics"]["winner"] == "red"
            assert controller.export_result(temporary / "result.json").ok
            result_frame = render()
            result_dialog = root.findChild(QObject, "resultsDialog")
            assert result_dialog and result_dialog.property("visible"), "Automatic results did not open"
            if report_path:
                result_frame.save(str(report_path.with_name("results-1280x720.png")))
            report["checks"].append("automatic_result_and_export")
            view_model.restartSimulation()
            assert controller.game_state == "running"
            controller.simulator.max_steps = 1
            view_model.stepSimulation()
            assert view_model.snapshot["statistics"]["finish_reason"] == "step_limit"
            limit_frame = render()
            assert result_dialog.property("visible")
            reason_label = root.findChild(QObject, "finishReasonLabel")
            assert reason_label and "时间步上限" in reason_label.property("text")
            if report_path:
                limit_frame.save(str(report_path.with_name("step-limit-1280x720.png")))
            report["checks"].append("bounded_completion_with_visible_draw_reason")
            view_model.resetSimulation()
            assert controller.game_state == "deployment"
            view_model._timer.stop()
            report["checks"].append("restart_and_edit_original_deployment")
            report["ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        view_model._timer.stop()
        root.close()
        if report_path:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return 0 if report["ok"] else 2
