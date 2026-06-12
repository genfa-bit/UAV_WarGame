"""PySide6 application bootstrap."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from core.controller import SimulationController
from ui.qt_models import SimulationViewModel


QML_PATH = Path(__file__).resolve().parent / "qml" / "Main.qml"


def create_engine(
    controller: SimulationController | None = None,
) -> tuple[QGuiApplication, QQmlApplicationEngine, SimulationViewModel]:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    app.setApplicationName("无人装备战争游戏仿真系统")
    app.setOrganizationName("UAV WarGame")

    engine = QQmlApplicationEngine()
    view_model = SimulationViewModel(controller)
    engine.rootContext().setContextProperty("viewModel", view_model)
    engine.rootContext().setContextProperty("unitListModel", view_model.unitModel)
    engine.load(QUrl.fromLocalFile(str(QML_PATH)))
    return app, engine, view_model


def run() -> int:
    app, engine, view_model = create_engine()
    if not engine.rootObjects():
        return 1
    engine._view_model = view_model
    return app.exec()
