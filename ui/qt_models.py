"""Qt models and view model for the QML frontend."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Property,
    Qt,
    QTimer,
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
        self._rows = [dict(row) for row in rows]
        if self._rows:
            top = self.index(0, 0)
            bottom = self.index(len(self._rows) - 1, 0)
            self.dataChanged.emit(top, bottom, list(self._ROLE_NAMES))


class SimulationViewModel(QObject):
    """Expose controller commands and snapshots to QML."""

    snapshotChanged = Signal()

    def __init__(
        self,
        controller: SimulationController | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self.controller = controller or SimulationController()
        self._snapshot: dict = {}
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

    @Slot(int, float, float)
    def pointerPress(self, button: int, x: float, y: float) -> None:
        self.controller.pointer_press(button, x, y)
        self._refresh()

    @Slot(float, float)
    def pointerMove(self, x: float, y: float) -> None:
        self.controller.pointer_move(x, y)
        self._refresh()

    @Slot(int, float, float)
    def pointerRelease(self, button: int, x: float, y: float) -> None:
        self.controller.pointer_release(button, x, y)
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
        self.controller.advance()
        self._refresh()

    def _refresh(self) -> None:
        self._snapshot = self.controller.snapshot()
        self._unit_model.set_rows(self._snapshot["units"])
        interval = max(1, int(self._snapshot["speed_interval_ms"]))
        self._timer.setInterval(interval)
        if self._snapshot["game_state"] == "running":
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.snapshotChanged.emit()
