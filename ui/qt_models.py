"""Qt models and view model for the QML frontend."""

from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QTimer,
    QSettings,
    QUrl,
    Signal,
    Slot,
)

from core.controller import SimulationController


class UnitListModel(QAbstractListModel):
    """Stable unit rows so QML delegates can animate position changes."""

    UnitIdRole = Qt.UserRole + 1
    UnitNameRole = Qt.UserRole + 2
    TeamRole = Qt.UserRole + 3
    UnitTypeRole = Qt.UserRole + 4
    DomainRole = Qt.UserRole + 5
    WorldXRole = Qt.UserRole + 6
    WorldYRole = Qt.UserRole + 7
    HpRole = Qt.UserRole + 8
    MaxHpRole = Qt.UserRole + 9
    AmmoRole = Qt.UserRole + 10
    MaxAmmoRole = Qt.UserRole + 11
    StatusRole = Qt.UserRole + 12
    DetectRangeRole = Qt.UserRole + 13
    AttackRangeRole = Qt.UserRole + 14
    DestroyedRole = Qt.UserRole + 15
    EngagementRole = Qt.UserRole + 16

    _ROLE_NAMES = {
        UnitIdRole: QByteArray(b"unitId"),
        UnitNameRole: QByteArray(b"unitName"),
        TeamRole: QByteArray(b"team"),
        UnitTypeRole: QByteArray(b"unitType"),
        DomainRole: QByteArray(b"domain"),
        WorldXRole: QByteArray(b"worldX"),
        WorldYRole: QByteArray(b"worldY"),
        HpRole: QByteArray(b"hp"),
        MaxHpRole: QByteArray(b"maxHp"),
        AmmoRole: QByteArray(b"ammo"),
        MaxAmmoRole: QByteArray(b"maxAmmo"),
        StatusRole: QByteArray(b"status"),
        DetectRangeRole: QByteArray(b"detectRange"),
        AttackRangeRole: QByteArray(b"attackRange"),
        DestroyedRole: QByteArray(b"destroyed"),
        EngagementRole: QByteArray(b"engagement"),
    }

    _ROLE_KEYS = {
        UnitIdRole: "id",
        UnitNameRole: "name",
        TeamRole: "team",
        UnitTypeRole: "unit_type",
        DomainRole: "domain",
        WorldXRole: "x",
        WorldYRole: "y",
        HpRole: "hp",
        MaxHpRole: "max_hp",
        AmmoRole: "ammo",
        MaxAmmoRole: "max_ammo",
        StatusRole: "status",
        DetectRangeRole: "detect_range",
        AttackRangeRole: "attack_range",
        DestroyedRole: "destroyed",
        EngagementRole: "engagement",
    }

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._rows: list[dict] = []

    def roleNames(self) -> dict[int, QByteArray]:
        return self._ROLE_NAMES

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        key = self._ROLE_KEYS.get(role)
        return self._rows[index.row()].get(key) if key else None

    def set_rows(self, rows: list[dict]) -> None:
        old_ids = [row["id"] for row in self._rows]
        new_ids = [row["id"] for row in rows]
        if old_ids != new_ids:
            self.beginResetModel()
            self._rows = [dict(row) for row in rows]
            self.endResetModel()
            return
        for index, row in enumerate(rows):
            roles = [role for role, key in self._ROLE_KEYS.items()
                     if self._rows[index].get(key) != row.get(key)]
            self._rows[index] = dict(row)
            if roles:
                model_index = self.index(index, 0)
                self.dataChanged.emit(model_index, model_index, roles)


class SimulationViewModel(QObject):
    """Expose controller commands and snapshots to QML."""

    snapshotChanged = Signal()
    selectionChanged = Signal()
    helpChanged = Signal()

    def __init__(
        self,
        controller: SimulationController | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.controller = controller or SimulationController()
        self._snapshot: dict = {}
        self._selected_unit_id = ""
        self._selected_unit = {}
        self._settings = QSettings("UAV_WarGame", "preferences")
        self._first_run = not self._settings.value("help_seen", False, type=bool)
        self._unit_model = UnitListModel(self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._refresh()

    @Property("QVariantMap", notify=snapshotChanged)
    def snapshot(self) -> dict:
        return self._snapshot

    @Property(QObject, constant=True)
    def unitModel(self) -> QObject:
        return self._unit_model

    @Property(str, notify=selectionChanged)
    def selectedUnitId(self) -> str:
        return self._selected_unit_id

    @Property("QVariantMap", notify=selectionChanged)
    def selectedUnit(self) -> dict:
        return self._selected_unit

    @Property(bool, notify=helpChanged)
    def firstRun(self) -> bool:
        return self._first_run

    @Property(QUrl, constant=True)
    def userScenarioUrl(self) -> QUrl:
        from core.map_persistence import user_scenario_dir
        return QUrl.fromLocalFile(str(user_scenario_dir()))

    @Property(QUrl, constant=True)
    def recordingDirectoryUrl(self) -> QUrl:
        return QUrl.fromLocalFile(str(self.controller.recording_directory))

    @Slot()
    def dismissHelp(self) -> None:
        self._first_run = False
        self._settings.setValue("help_seen", True)
        self.helpChanged.emit()

    @Slot(str)
    def selectUnit(self, unit_id: str) -> None:
        self._selected_unit_id = unit_id
        self._update_selection()

    @Slot(int)
    def setSpeed(self, index: int) -> None:
        self.controller.set_speed(index)
        self._refresh()

    @Slot(float, int)
    def setTiming(self, duration: float, max_steps: int) -> None:
        self.controller.set_timing(duration, max_steps)
        self._refresh()

    @Slot(str)
    def loadScenario(self, scenario_id: str) -> None:
        result = self.controller.select_scene(scenario_id)
        if result.ok:
            self._selected_unit_id = ""
        self._refresh()

    @Slot(str)
    def setMapStyle(self, style: str) -> None:
        self.controller.set_map_style(style)
        self._refresh()

    @Slot()
    def restartSimulation(self) -> None:
        result = self.controller.restart()
        if result.ok:
            self._selected_unit_id = ""
        self._refresh()

    def _local_path(self, url: QUrl) -> str | None:
        path = url.toLocalFile()
        if not path:
            self.controller.last_message = "请选择本机上的文件"
            self._refresh()
            return None
        return path

    @Slot(QUrl)
    def loadMapFromUrl(self, url: QUrl) -> None:
        path = self._local_path(url)
        if path:
            result = self.controller.load_map(path)
            if result.ok:
                self._selected_unit_id = ""
            self._refresh()

    @Slot(QUrl)
    def saveMapToUrl(self, url: QUrl) -> None:
        path = self._local_path(url)
        if path:
            self.controller.save_map(path)
            self._refresh()

    @Slot(QUrl)
    def exportResultToUrl(self, url: QUrl) -> None:
        path = self._local_path(url)
        if path:
            self.controller.export_result(path)
            self._refresh()

    @Slot(QUrl, str)
    def exportRecordsToUrl(self, url: QUrl, category: str = "all") -> None:
        path = self._local_path(url)
        if path:
            self.controller.export_records(path, category)
            self._refresh()

    @Slot()
    def flushRecords(self) -> None:
        self.controller.flush_records()

    @Slot()
    def startSimulation(self) -> None:
        self.controller.start()
        self._refresh()

    @Slot()
    def togglePause(self) -> None:
        self.controller.toggle_pause()
        self._refresh()

    @Slot()
    def stepSimulation(self) -> None:
        self.controller.step()
        self._refresh()

    @Slot()
    def resetSimulation(self) -> None:
        self.controller.reset()
        self._selected_unit_id = ""
        self._refresh()

    @Slot()
    def cycleSpeed(self) -> None:
        self.controller.cycle_speed()
        self._refresh()

    @Slot()
    def toggleWrecks(self) -> None:
        self.controller.toggle_wrecks()
        self._refresh()

    @Slot()
    def toggleTeam(self) -> None:
        self.controller.toggle_team()
        self._refresh()

    @Slot(str)
    def selectUnitType(self, unit_type: str) -> None:
        self.controller.select_unit_type(unit_type)
        self._refresh()

    @Slot(str)
    def selectObstacleType(self, obstacle_type: str) -> None:
        self.controller.select_obstacle_type(obstacle_type)
        self._refresh()

    @Slot(float, float)
    def placeAt(self, x: float, y: float) -> None:
        self.controller.place_at(x, y)
        self._refresh()

    @Slot(int, float, float, result=bool)
    def pointerPress(self, button: int, x: float, y: float) -> bool:
        """返回按下后是否开始了部署编辑手势（拉框、拖拽、缩放）。"""
        if self.controller.game_state != "deployment":
            if button == 1:
                candidates = [row for row in self._snapshot["units"]
                              if (not row["destroyed"] or self._snapshot["show_wrecks"])
                              and (row["x"] - x) ** 2 + (row["y"] - y) ** 2 <= 24 ** 2]
                candidates.sort(key=lambda row: (row["x"] - x) ** 2 + (row["y"] - y) ** 2)
                self.selectUnit(candidates[0]["id"] if candidates else "")
            return False
        self.controller.pointer_press(button, x, y)
        self._refresh()
        return self.controller.editor_active

    @Slot(float, float)
    def pointerMove(self, x: float, y: float) -> None:
        self.controller.pointer_move(x, y)
        self._refresh()

    @Slot(int, float, float)
    def pointerRelease(self, button: int, x: float, y: float) -> None:
        self.controller.pointer_release(button, x, y)
        self._refresh()

    @Slot()
    def cancelPointer(self) -> None:
        self.controller.pointer_cancel()
        self._refresh()

    @Slot()
    def undoDeployment(self) -> None:
        self.controller.undo()
        self._refresh()

    @Slot()
    def clearDeployment(self) -> None:
        self.controller.clear_deployment()
        self._refresh()

    @Slot()
    def deleteSelected(self) -> None:
        self.controller.delete_selected()
        self._refresh()

    @Slot()
    def saveMap(self) -> None:
        self.controller.save_map()
        self._refresh()

    @Slot()
    def loadMap(self) -> None:
        self.controller.load_map()
        self._refresh()

    @Slot()
    def refresh(self) -> None:
        self._refresh()

    def _advance(self) -> None:
        # Bound each fast-compute batch so Qt can process pause/reset and repaint.
        deadline = perf_counter() + 0.012
        for _ in range(24 if self.controller.speed_interval_ms == 0 else 1):
            self.controller.advance()
            if self.controller.game_state != "running" or perf_counter() >= deadline:
                break
        self._refresh()

    def _update_selection(self) -> None:
        selected = next((row for row in self._snapshot.get("units", [])
                         if row["id"] == self._selected_unit_id), {})
        if not selected:
            self._selected_unit_id = ""
        self._selected_unit = dict(selected)
        self.selectionChanged.emit()

    def _refresh(self) -> None:
        self._snapshot = self.controller.snapshot()
        self._unit_model.set_rows(self._snapshot["units"])
        self._update_selection()
        interval = int(self._snapshot["speed_interval_ms"]) or 33
        self._timer.setInterval(interval)
        if self._snapshot["game_state"] == "running":
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.snapshotChanged.emit()
