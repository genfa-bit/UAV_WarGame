pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs

ApplicationWindow {
    id: root
    width: Math.min(1440, Screen.desktopAvailableWidth)
    height: Math.min(900, Screen.desktopAvailableHeight)
    minimumWidth: 920
    minimumHeight: 540
    visible: true
    color: "#08111f"
    title: "无人装备战争游戏仿真系统"

    property var snap: viewModel.snapshot
    readonly property bool deploymentMode: snap.game_state === "deployment"
    readonly property color redColor: "#ff5d73"
    readonly property color blueColor: "#4ca6ff"
    readonly property color accentColor: "#54e1c2"
    readonly property color panelColor: "#101d2e"
    readonly property color cardColor: "#14243a"
    readonly property color mutedColor: "#8da2ba"
    readonly property string selectedUnitId: viewModel.selectedUnitId
    property bool resultPresented: false
    property string logFilter: "all"
    property string recordFilter: "all"
    readonly property var timing: root.snap.timing || ({step_duration_seconds: 0.22, max_steps: 2000, editable: root.deploymentMode || root.snap.game_state === "paused"})
    readonly property var recording: root.snap.recording || ({records: [], history: [], record_count: 0, has_run: false})
    property bool showAllRanges: false
    property bool showMapGrid: true
    property bool showMapLandmarks: true
    readonly property var mapVisual: root.snap.map.visual || ({})
    readonly property string mapStyle: root.snap.map.style || "tactical"
    property var pendingAction: null
    property string pendingTitle: "确认操作"
    property string pendingMessage: ""
    readonly property bool dialogActive: confirmationDialog.visible || resultsDialog.visible
        || helpDialog.visible || loadMapDialog.visible || saveMapDialog.visible || exportDialog.visible
        || timingDialog.visible || recordsDialog.visible || exportRecordsDialog.visible

    function secondsLabel(value) {
        return Number(value || 0).toFixed(2) + " 秒"
    }

    function filteredRecords() {
        const records = root.recording.records || []
        if (root.recordFilter === "all") return records
        return records.filter(function(record) { return record.category === root.recordFilter })
    }

    function recordCategoryLabel(category) {
        const labels = { scout: "侦察", sharing: "共享", destroyed: "摧毁",
            tactical: "战术", result: "结果", settings: "设置", lifecycle: "运行", combat: "交战" }
        return labels[category] || category
    }

    function confirmAction(title, message, action) {
        pendingTitle = title
        pendingMessage = message
        pendingAction = action
        confirmationDialog.open()
    }

    function selectScenario(index) {
        const scenarios = root.snap.scenarios || []
        if (index < 0 || index >= scenarios.length) return
        const scenario = scenarios[index]
        if (scenario.id === root.snap.scene_id) return
        confirmAction("切换场景", "切换到“" + scenario.name
                      + "”会替换当前地图和部署。未保存的编辑将丢失。", function() {
            viewModel.loadScenario(scenario.id)
        })
    }

    function scenarioIndex() {
        const scenarios = root.snap.scenarios || []
        for (let i = 0; i < scenarios.length; ++i)
            if (scenarios[i].id === root.snap.scene_id) return i
        return -1
    }

    function requestLoadMap() {
        confirmAction("载入地图", "载入文件会替换当前地图和部署。请先保存需要保留的编辑。",
                      function() { loadMapDialog.open() })
    }

    function requestReset() {
        confirmAction("返回部署", "结束本局并返回部署编辑？本局运行结果会被重置。",
                      function() { viewModel.resetSimulation() })
    }

    function filteredLogs() {
        const logs = root.snap.logs || []
        if (logFilter === "all") return logs
        return logs.filter(function(line) {
            if (root.logFilter === "scout")
                return line.indexOf("[Scout]") === 0 || line.indexOf("[TargetPool]") === 0
            if (root.logFilter === "attack") return line.indexOf("[Attack]") === 0
            if (root.logFilter === "destroyed") return line.indexOf("[Destroyed]") === 0
            return line.indexOf("[Attack]") !== 0 && line.indexOf("[Destroyed]") !== 0
                && line.indexOf("[Scout]") !== 0 && line.indexOf("[TargetPool]") !== 0
        })
    }

    function unitShortName(unitType) {
        if (unitType === "scout_drone") return "侦"
        if (unitType === "strike_drone") return "击"
        if (unitType === "ground_vehicle") return "战"
        if (unitType === "missile_vehicle") return "导"
        return "指"
    }

    function unitStatusLabel(status) {
        const labels = {
            "Idle": "待命", "Move": "机动", "Patrol": "巡逻", "Attack": "攻击",
            "Evade": "规避", "Destroyed": "已摧毁", "Scout": "侦察",
            "Retreat": "撤退", "Resupply": "补给", "Support": "支援"
        }
        return labels[status] || status
    }

    function stateColor(state) {
        if (state === "running") return accentColor
        if (state === "paused") return "#ffca64"
        if (state === "finished") return redColor
        return blueColor
    }

    function obstacleColor(type) {
        if (type === "mountain") return "#40584d"
        if (type === "building") return "#46536a"
        if (type === "restricted") return "#693e4e"
        return "#435267"
    }

    function alphaColor(source, alpha) {
        return Qt.rgba(source.r, source.g, source.b, alpha)
    }

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function unitById(unitId) {
        const units = root.snap.units || []
        for (let i = 0; i < units.length; ++i) {
            if (units[i].id === unitId)
                return units[i]
        }
        return null
    }

    component AppButton: Rectangle {
        id: button
        property string text: ""
        property color tone: root.accentColor
        property bool selected: false
        signal clicked()
        Accessible.role: Accessible.Button
        Accessible.name: text

        implicitHeight: 38
        implicitWidth: 110
        radius: 8
        opacity: enabled ? 1 : 0.42
        color: selected ? root.alphaColor(tone, 0.24)
                        : mouseArea.containsMouse ? "#203653" : "#182a42"
        border.width: selected ? 1.5 : 1
        border.color: selected ? tone : "#2b4260"

        Text {
            anchors.centerIn: parent
            text: button.text
            color: button.selected ? button.tone : "#dce8f6"
            font.family: "Microsoft YaHei"
            font.pixelSize: 13
            font.bold: button.selected
        }

        MouseArea {
            id: mouseArea
            anchors.fill: parent
            hoverEnabled: true
            enabled: button.enabled
            cursorShape: Qt.PointingHandCursor
            onClicked: button.clicked()
        }
    }

    component SectionTitle: Text {
        color: "#ecf5ff"
        font.family: "Microsoft YaHei"
        font.pixelSize: 13
        font.bold: true
        font.letterSpacing: 1
    }

    component StatPair: Rectangle {
        property string label: ""
        property string redValue: "0"
        property string blueValue: "0"

        implicitHeight: 72
        radius: 10
        color: "#13243a"
        border.color: "#263d5a"

        Column {
            anchors.fill: parent
            anchors.margins: 9
            spacing: 5

            Text {
                width: parent.width
                text: label
                color: root.mutedColor
                font.family: "Microsoft YaHei"
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
            }

            Row {
                width: parent.width
                height: 31

                Text {
                    width: parent.width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    text: redValue
                    color: root.redColor
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 17
                    font.bold: true
                    minimumPixelSize: 10
                    fontSizeMode: Text.Fit
                    horizontalAlignment: Text.AlignHCenter
                }

                Text {
                    width: parent.width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    text: blueValue
                    color: root.blueColor
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 17
                    font.bold: true
                    minimumPixelSize: 10
                    fontSizeMode: Text.Fit
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }
    }

    background: Rectangle {
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#0b1728" }
            GradientStop { position: 1.0; color: "#07101c" }
        }
    }

    header: Rectangle {
        height: root.height < 700 ? 62 : 72
        color: "#0c192a"
        border.color: "#1d334e"

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            spacing: 18

            Column {
                Layout.alignment: Qt.AlignVCenter
                spacing: 2

                Text {
                    text: "UAV WARGAME"
                    color: root.accentColor
                    font.family: "Segoe UI"
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 3
                }

                Text {
                    text: "无人装备战争游戏仿真系统"
                    color: "#f1f7ff"
                    font.family: "Microsoft YaHei"
                    font.pixelSize: root.width < 1100 ? 18 : 22
                    font.bold: true
                }
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                implicitWidth: 114
                implicitHeight: 36
                radius: 18
                color: root.alphaColor(root.stateColor(root.snap.game_state), 0.15)
                border.color: root.stateColor(root.snap.game_state)

                Row {
                    anchors.centerIn: parent
                    spacing: 8

                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        color: root.stateColor(root.snap.game_state)
                    }

                    Text {
                        text: root.snap.state_label
                        color: "#eaf4ff"
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 13
                        font.bold: true
                    }
                }
            }

            Rectangle {
                implicitWidth: root.width < 1100 ? 152 : 170
                implicitHeight: 44
                radius: 8
                color: "#13243a"
                border.color: "#263f5e"

                Column {
                    anchors.centerIn: parent
                    spacing: 1

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "累计 " + root.secondsLabel(root.snap.statistics.elapsed_seconds)
                        color: root.mutedColor
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 10
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.snap.statistics.time_step + " / " + (root.snap.statistics.max_steps || 2000)
                        color: "#ffffff"
                        font.family: "Consolas"
                        font.pixelSize: root.width < 1100 ? 15 : 18
                        font.bold: true
                    }
                }
            }
            AppButton {
                objectName: "timingButton"
                Layout.preferredWidth: 84
                text: "时间设置"
                onClicked: timingDialog.open()
            }
            AppButton {
                objectName: "recordsButton"
                Layout.preferredWidth: 84
                text: "运行记录"
                onClicked: recordsDialog.open()
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12

        Rectangle {
            id: battlefieldCard
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 500
            radius: 14
            color: "#0d1a2a"
            border.color: "#203955"
            clip: true

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 42
                color: "#112238"

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14

                    Text {
                        Layout.fillWidth: true
                        text: "战场态势  /  " + (root.mapVisual.title || "战术地图")
                        color: "#cfe0f2"
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 13
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    Text {
                        text: root.deploymentMode
                              ? root.snap.deployment.selected_label + " · "
                                + (root.snap.deployment.selected_team === "red" ? "红方" : "蓝方")
                              : "速度 " + root.snap.speed_label
                        color: root.deploymentMode
                               ? (root.snap.deployment.selected_team === "red"
                                  ? root.redColor : root.blueColor)
                               : root.accentColor
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 12
                    }
                }
            }

            Rectangle {
                id: mapToolbar
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.topMargin: 42
                height: 36
                color: "#0f2033"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 6
                    AppButton {
                        objectName: "mapZoomOut"
                        Layout.preferredWidth: 28
                        height: 26
                        text: "−"
                        enabled: battlefieldViewport.zoomLevel > 1.001
                        onClicked: battlefieldViewport.zoomAt(battlefieldViewport.zoomLevel / 1.25,
                                                              battlefieldViewport.width / 2, battlefieldViewport.height / 2)
                    }
                    Text {
                        Layout.preferredWidth: 38
                        text: Math.round(battlefieldViewport.zoomLevel * 100) + "%"
                        color: "#cfe0f2"
                        font.family: "Consolas"
                        font.pixelSize: 11
                        horizontalAlignment: Text.AlignHCenter
                    }
                    AppButton {
                        objectName: "mapZoomIn"
                        Layout.preferredWidth: 28
                        height: 26
                        text: "+"
                        enabled: battlefieldViewport.zoomLevel < 3.999
                        onClicked: battlefieldViewport.zoomAt(battlefieldViewport.zoomLevel * 1.25,
                                                              battlefieldViewport.width / 2, battlefieldViewport.height / 2)
                    }
                    AppButton {
                        objectName: "mapFit"
                        Layout.preferredWidth: 74
                        height: 26
                        text: "适应地图"
                        onClicked: battlefieldViewport.resetView()
                    }
                    Item { Layout.fillWidth: true }
                    AppButton {
                        Layout.preferredWidth: 64
                        height: 26
                        text: "全部范围"
                        selected: root.showAllRanges
                        onClicked: { root.showAllRanges = !root.showAllRanges; battleCanvas.requestPaint() }
                    }
                    AppButton {
                        Layout.preferredWidth: 46
                        height: 26
                        text: "网格"
                        selected: root.showMapGrid
                        onClicked: root.showMapGrid = !root.showMapGrid
                    }
                    AppButton {
                        Layout.preferredWidth: 46
                        height: 26
                        text: "地标"
                        selected: root.showMapLandmarks
                        onClicked: root.showMapLandmarks = !root.showMapLandmarks
                    }
                }
            }

            Item {
                id: battlefieldViewport
                objectName: "mapViewport"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: mapToolbar.bottom
                anchors.bottom: messageBar.top
                anchors.margins: 14
                clip: true
                property real zoomLevel: 1
                property real panX: 0
                property real panY: 0
                readonly property real fitScale: Math.min(
                    width / root.snap.map.width,
                    height / root.snap.map.height
                )
                readonly property real scaleFactor: fitScale * zoomLevel
                readonly property real offsetX: (width - root.snap.map.width * scaleFactor) / 2 + panX
                readonly property real offsetY: (height - root.snap.map.height * scaleFactor) / 2 + panY
                readonly property string sceneKey: root.snap.scene_id + ":" + root.snap.map.width + ":" + root.snap.map.height
                readonly property real visibleWorldX: root.clamp(-offsetX / scaleFactor, 0, root.snap.map.width)
                readonly property real visibleWorldY: root.clamp(-offsetY / scaleFactor, 0, root.snap.map.height)
                readonly property real visibleWorldWidth: root.clamp((width - offsetX) / scaleFactor, 0, root.snap.map.width) - visibleWorldX
                readonly property real visibleWorldHeight: root.clamp((height - offsetY) / scaleFactor, 0, root.snap.map.height) - visibleWorldY

                function constrainPan() {
                    const xLimit = Math.max(0, (root.snap.map.width * scaleFactor - width) / 2)
                    const yLimit = Math.max(0, (root.snap.map.height * scaleFactor - height) / 2)
                    panX = root.clamp(panX, -xLimit, xLimit)
                    panY = root.clamp(panY, -yLimit, yLimit)
                }
                function resetView() {
                    zoomLevel = 1
                    panX = 0
                    panY = 0
                }
                function zoomAt(factor, anchorX, anchorY) {
                    const worldX = (anchorX - offsetX) / scaleFactor
                    const worldY = (anchorY - offsetY) / scaleFactor
                    zoomLevel = root.clamp(factor, 1, 4)
                    panX = anchorX - worldX * scaleFactor - (width - root.snap.map.width * scaleFactor) / 2
                    panY = anchorY - worldY * scaleFactor - (height - root.snap.map.height * scaleFactor) / 2
                    constrainPan()
                }
                function centerOn(worldX, worldY) {
                    panX = (root.snap.map.width / 2 - worldX) * scaleFactor
                    panY = (root.snap.map.height / 2 - worldY) * scaleFactor
                    constrainPan()
                }
                onSceneKeyChanged: resetView()
                onWidthChanged: constrainPan()
                onHeightChanged: constrainPan()

                Item {
                    id: battlefield
                    objectName: "battlefieldLayer"
                    width: root.snap.map.width * battlefieldViewport.scaleFactor
                    height: root.snap.map.height * battlefieldViewport.scaleFactor
                    x: battlefieldViewport.offsetX
                    y: battlefieldViewport.offsetY
                    clip: true

                    TerrainLayer {
                        objectName: "terrainLayer"
                        anchors.fill: parent
                        worldWidth: root.snap.map.width
                        worldHeight: root.snap.map.height
                        mapStyle: root.mapStyle
                        visual: root.mapVisual
                        showGrid: root.showMapGrid
                        showLandmarks: root.showMapLandmarks
                        z: 0
                    }

                    Canvas {
                        id: battleCanvas
                        anchors.fill: parent
                        z: 1

                        onPaint: {
                            const ctx = getContext("2d")
                            const sx = width / root.snap.map.width
                            const sy = height / root.snap.map.height
                            ctx.clearRect(0, 0, width, height)

                            for (let i = 0; i < root.snap.units.length; ++i) {
                                const unit = root.snap.units[i]
                                if (unit.destroyed) continue
                                if (!root.showAllRanges && unit.id !== root.selectedUnitId) continue
                                ctx.beginPath()
                                ctx.arc(unit.x * sx, unit.y * sy,
                                        unit.detect_range * sx, 0, Math.PI * 2)
                                ctx.strokeStyle = unit.team === "red"
                                                  ? "rgba(255,93,115,0.42)"
                                                  : "rgba(76,166,255,0.42)"
                                ctx.lineWidth = 1
                                ctx.stroke()
                                if (unit.id === root.selectedUnitId) {
                                    ctx.beginPath()
                                    ctx.arc(unit.x * sx, unit.y * sy,
                                            unit.attack_range * sx, 0, Math.PI * 2)
                                    ctx.strokeStyle = "#ffd166"
                                    ctx.lineWidth = 2
                                    ctx.setLineDash([6, 5])
                                    ctx.stroke()
                                    ctx.setLineDash([])
                                }
                            }

                            const preview = root.snap.map.preview
                            if (preview.visible) {
                                ctx.fillStyle = "rgba(255,209,102,0.22)"
                                ctx.strokeStyle = "#ffd166"
                                ctx.lineWidth = 2
                                ctx.fillRect(preview.x * sx, preview.y * sy,
                                             preview.width * sx, preview.height * sy)
                                ctx.strokeRect(preview.x * sx, preview.y * sy,
                                               preview.width * sx, preview.height * sy)
                            }
                        }
                    }

                    Repeater {
                        id: obstacleRepeater
                        objectName: "obstacleRepeater"
                        model: root.snap.map.obstacles

                        delegate: Item {
                            id: obstacleItem
                            required property var modelData
                            readonly property string obstacleType: modelData.type
                            readonly property url iconSource:
                                "../assets/obstacle_icons/" + obstacleType + ".png"
                            readonly property url panelSource: obstacleType === "mountain"
                                ? "../assets/obstacle_icons/panel_polygon.png"
                                : (obstacleType === "restricted"
                                    ? "../assets/obstacle_icons/panel_clipped.png"
                                    : "../assets/obstacle_icons/panel_rect.png")
                            readonly property color accentColor: obstacleType === "restricted"
                                ? "#ff6b72" : (obstacleType === "mountain" ? "#b7c596" : "#75b7d8")

                            objectName: "obstacle-" + modelData.index
                            x: modelData.x * battlefieldViewport.scaleFactor
                            y: modelData.y * battlefieldViewport.scaleFactor
                            width: Math.max(20, modelData.width * battlefieldViewport.scaleFactor)
                            height: Math.max(20, modelData.height * battlefieldViewport.scaleFactor)
                            z: 2

                            Image {
                                anchors.fill: parent
                                source: obstacleItem.panelSource
                                visible: root.mapStyle === "tactical"
                                fillMode: Image.Stretch
                                opacity: 0.5
                                smooth: true
                            }

                            Rectangle {
                                anchors.fill: parent
                                color: root.mapStyle === "tactical" ? "transparent"
                                    : root.alphaColor(obstacleItem.accentColor, 0.13)
                                border.width: obstacleItem.modelData.selected ? 3 : 1
                                border.color: obstacleItem.modelData.selected
                                              ? "#ffd166" : obstacleItem.accentColor
                            }

                            Image {
                                id: obstacleIcon
                                objectName: "obstacleIcon-" + obstacleItem.modelData.index
                                anchors.centerIn: parent
                                width: obstacleItem.obstacleType === "restricted"
                                       ? parent.width * 0.88 : parent.width * 1.22
                                height: obstacleItem.obstacleType === "restricted"
                                        ? parent.height * 0.88 : parent.height * 1.22
                                source: obstacleItem.iconSource
                                visible: root.mapStyle === "tactical"
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                mipmap: true
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.margins: 5
                                width: obstacleLabel.implicitWidth + 12
                                height: obstacleLabel.implicitHeight + 6
                                radius: 5
                                color: "#c90a1522"
                                border.color: "#566f88"

                                Text {
                                    id: obstacleLabel
                                    anchors.centerIn: parent
                                    text: obstacleItem.modelData.name
                                    color: "#e3edf7"
                                    font.family: "Microsoft YaHei"
                                    font.pixelSize: 10
                                    font.bold: true
                                }
                            }
                        }
                    }

                    Repeater {
                        id: baseRepeater
                        objectName: "baseRepeater"
                        model: [root.snap.map.red_base, root.snap.map.blue_base]

                        delegate: Item {
                            id: baseItem
                            required property var modelData
                            readonly property color teamColor:
                                modelData.team === "red" ? root.redColor : root.blueColor
                            readonly property real glyphSize: root.mapStyle === "tactical"
                                ? 62 : root.clamp(72 * battlefieldViewport.scaleFactor, 30, 62)

                            x: modelData.x * battlefieldViewport.scaleFactor - width / 2
                            y: modelData.y * battlefieldViewport.scaleFactor - glyphSize / 2
                            width: 76
                            height: 82
                            z: 3
                            opacity: modelData.destroyed ? 0.4 : 1

                            Rectangle {
                                objectName: "baseBackdrop-" + baseItem.modelData.team
                                property real outlineWidth: 0
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: baseItem.glyphSize
                                height: width
                                radius: width / 2
                                color: root.alphaColor(baseItem.teamColor, 0.18)
                                border.width: outlineWidth
                            }

                            Image {
                                objectName: "baseIcon-" + baseItem.modelData.team
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: (baseItem.glyphSize - height) / 2
                                width: baseItem.glyphSize * 0.87
                                height: width
                                source: "../assets/unit_icons/base_station.png"
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                mipmap: true
                            }

                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: baseItem.glyphSize + 1
                                width: Math.max(30, baseItem.glyphSize * 0.94)
                                height: 5
                                radius: 2
                                color: "#263348"

                                Rectangle {
                                    width: parent.width * Math.max(
                                        0, baseItem.modelData.hp / baseItem.modelData.max_hp)
                                    height: parent.height
                                    radius: 2
                                    color: baseItem.teamColor
                                }
                            }

                            Text {
                                anchors.top: parent.top
                                anchors.topMargin: baseItem.glyphSize + 8
                                width: parent.width
                                text: baseItem.modelData.team === "red" ? "红方基地" : "蓝方基地"
                                color: baseItem.teamColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 9
                                horizontalAlignment: Text.AlignHCenter
                            }
                        }
                    }

                    Canvas {
                        id: attackCanvas
                        objectName: "attackCanvas"
                        anchors.fill: parent
                        z: 4
                        property var eventStartTimes: ({})
                        property var knownEventIds: ({})
                        property var latestEventIds: ({})
                        property var displayedEvents: []
                        property int flightDuration: 180
                        property int trailDuration: 360
                        property int feedbackDuration: 140
                        property int animationDuration: flightDuration + trailDuration

                        function syncEvents(events) {
                            const now = Date.now()
                            const merged = []
                            const seen = {}
                            const incoming = {}
                            for (let i = 0; i < displayedEvents.length; ++i) {
                                const oldEvent = displayedEvents[i]
                                const started = eventStartTimes[oldEvent.event_id]
                                if (started !== undefined
                                    && now - started < animationDuration) {
                                    merged.push(oldEvent)
                                    seen[oldEvent.event_id] = true
                                }
                            }
                            for (let j = 0; j < events.length; ++j) {
                                const newEvent = events[j]
                                incoming[newEvent.event_id] = true
                                if (!knownEventIds[newEvent.event_id]) {
                                    eventStartTimes[newEvent.event_id] = now
                                    knownEventIds[newEvent.event_id] = true
                                    merged.push(newEvent)
                                }
                            }
                            for (const eventId in knownEventIds) {
                                if (!incoming[eventId] && !seen[eventId]) {
                                    delete knownEventIds[eventId]
                                    delete eventStartTimes[eventId]
                                }
                            }
                            latestEventIds = incoming
                            displayedEvents = merged
                            requestPaint()
                        }

                        function pruneEvents() {
                            const now = Date.now()
                            const active = []
                            for (let i = 0; i < displayedEvents.length; ++i) {
                                const event = displayedEvents[i]
                                const started = eventStartTimes[event.event_id]
                                if (started !== undefined
                                    && now - started < animationDuration) {
                                    active.push(event)
                                } else {
                                    delete eventStartTimes[event.event_id]
                                    if (!latestEventIds[event.event_id])
                                        delete knownEventIds[event.event_id]
                                }
                            }
                            displayedEvents = active
                        }

                        function eventAge(event, now) {
                            const key = event.event_id
                            if (eventStartTimes[key] === undefined)
                                eventStartTimes[key] = now
                            return Math.max(0, now - eventStartTimes[key])
                        }

                        function pointOnLine(startX, startY, endX, endY, progress) {
                            return {
                                x: startX + (endX - startX) * progress,
                                y: startY + (endY - startY) * progress
                            }
                        }

                        function pointOnCurve(startX, startY, controlX, controlY,
                                              endX, endY, progress) {
                            const inv = 1 - progress
                            return {
                                x: inv * inv * startX
                                   + 2 * inv * progress * controlX
                                   + progress * progress * endX,
                                y: inv * inv * startY
                                   + 2 * inv * progress * controlY
                                   + progress * progress * endY
                            }
                        }

                        function drawPulseLine(ctx, startX, startY, endX, endY,
                                               outerWidth, innerWidth,
                                               color, brightColor) {
                            ctx.strokeStyle = color
                            ctx.lineWidth = outerWidth
                            ctx.beginPath()
                            ctx.moveTo(startX, startY)
                            ctx.lineTo(endX, endY)
                            ctx.stroke()

                            ctx.strokeStyle = brightColor
                            ctx.lineWidth = innerWidth
                            ctx.beginPath()
                            ctx.moveTo(startX, startY)
                            ctx.lineTo(endX, endY)
                            ctx.stroke()
                        }

                        function drawFeedback(ctx, event, endX, endY, age,
                                              normalX, normalY,
                                              color, brightColor) {
                            const feedbackAge = age - flightDuration
                            if (feedbackAge < 0 || feedbackAge > feedbackDuration)
                                return
                            const phase = feedbackAge / feedbackDuration
                            const alpha = 1 - phase
                            ctx.save()
                            ctx.globalAlpha = alpha
                            ctx.lineCap = "round"

                            if (event.miss) {
                                const evadeColor = "#9cf5e6"
                                const shift = 2 + phase * 5
                                const tangentX = -normalY
                                const tangentY = normalX
                                ctx.strokeStyle = evadeColor
                                ctx.lineWidth = 2.2
                                for (let side of [-1, 1]) {
                                    const centerX = endX + normalX * shift * side
                                    const centerY = endY + normalY * shift * side
                                    ctx.beginPath()
                                    ctx.moveTo(centerX - tangentX * 4 - normalX * 2,
                                               centerY - tangentY * 4 - normalY * 2)
                                    ctx.lineTo(centerX + tangentX * 4 + normalX * 2,
                                               centerY + tangentY * 4 + normalY * 2)
                                    ctx.stroke()
                                }
                            } else {
                                const radius = 3 + phase * 7
                                ctx.strokeStyle = color
                                ctx.lineWidth = 2
                                ctx.beginPath()
                                ctx.arc(endX, endY, radius, 0, Math.PI * 2)
                                ctx.stroke()
                                const arm = 5.5 * (1 - phase * 0.35)
                                ctx.strokeStyle = brightColor
                                ctx.lineWidth = 2.4
                                ctx.beginPath()
                                ctx.moveTo(endX - arm, endY)
                                ctx.lineTo(endX + arm, endY)
                                ctx.moveTo(endX, endY - arm)
                                ctx.lineTo(endX, endY + arm)
                                ctx.stroke()
                            }
                            ctx.restore()
                        }

                        onPaint: {
                            const ctx = getContext("2d")
                            const events = displayedEvents
                            const now = Date.now()
                            ctx.clearRect(0, 0, width, height)

                            for (let i = 0; i < events.length; ++i) {
                                const event = events[i]
                                const age = eventAge(event, now)
                                if (age >= animationDuration)
                                    continue
                                const progress = root.clamp(
                                    age / flightDuration, 0, 1)
                                const trailFade = age <= flightDuration
                                                  ? 1
                                                  : 1 - (age - flightDuration)
                                                    / trailDuration

                                const attacker = root.unitById(event.attacker_id)
                                if (!attacker && !event.attacker_type)
                                    continue
                                const unitType = event.attacker_type
                                                 || attacker.unit_type
                                const attackerTeam = event.attacker_team
                                                     || attacker.team
                                const teamColor = attackerTeam === "red"
                                                  ? root.redColor : root.blueColor
                                const brightColor = attackerTeam === "red"
                                                    ? "#ffb0bd" : "#b7ddff"
                                const color = teamColor
                                const fadeIn = Math.min(1, age / 28)
                                const missAlpha = event.miss ? 0.68 : 1
                                ctx.globalAlpha = root.clamp(
                                    fadeIn * trailFade * missAlpha, 0, 1)

                                let startX = event.start[0] * battlefieldViewport.scaleFactor
                                let startY = event.start[1] * battlefieldViewport.scaleFactor
                                let endX = event.end[0] * battlefieldViewport.scaleFactor
                                let endY = event.end[1] * battlefieldViewport.scaleFactor
                                let dx = endX - startX
                                let dy = endY - startY
                                let distance = Math.sqrt(dx * dx + dy * dy)
                                if (distance < 1)
                                    continue
                                const ux = dx / distance
                                const uy = dy / distance
                                const normalX = -uy
                                const normalY = ux

                                let reciprocal = false
                                let sameDirectionBefore = 0
                                for (let j = 0; j < events.length; ++j) {
                                    if (j < i
                                            && events[j].attacker_id === event.attacker_id
                                            && events[j].target_id === event.target_id)
                                        sameDirectionBefore += 1
                                    if (events[j].attacker_id === event.target_id
                                        && events[j].target_id === event.attacker_id)
                                        reciprocal = true
                                }
                                const laneOffset = (reciprocal ? 6 : 0)
                                                   + sameDirectionBefore * 3
                                startX += normalX * laneOffset
                                startY += normalY * laneOffset
                                endX += normalX * laneOffset
                                endY += normalY * laneOffset

                                const targetIsBase = String(event.target_id).endsWith("_base")
                                const sourceRadius = 22
                                const targetRadius = targetIsBase ? 30 : 22
                                startX += ux * sourceRadius
                                startY += uy * sourceRadius
                                endX -= ux * targetRadius
                                endY -= uy * targetRadius

                                ctx.strokeStyle = color
                                ctx.fillStyle = color
                                ctx.lineCap = "round"

                                if (unitType === "missile_vehicle") {
                                    const adjustedDx = endX - startX
                                    const adjustedDy = endY - startY
                                    const adjustedDistance = Math.sqrt(
                                        adjustedDx * adjustedDx + adjustedDy * adjustedDy)
                                    const arcHeight = root.clamp(
                                        adjustedDistance * 0.18, 24, 90)
                                    const controlX = (startX + endX) / 2
                                    const controlY = (startY + endY) / 2 - arcHeight
                                    const tailProgress = Math.max(0, progress - 0.42)
                                    const steps = Math.max(
                                        3, Math.ceil((progress - tailProgress) * 28))
                                    let previous = pointOnCurve(
                                        startX, startY, controlX, controlY,
                                        endX, endY, tailProgress)
                                    for (let step = 1; step <= steps; ++step) {
                                        const t = tailProgress
                                                  + (progress - tailProgress)
                                                  * step / steps
                                        const point = pointOnCurve(
                                            startX, startY, controlX, controlY, endX, endY, t)
                                        drawPulseLine(
                                            ctx, previous.x, previous.y, point.x, point.y,
                                            6, 2.4, color, brightColor)
                                        previous = point
                                    }
                                    const head = pointOnCurve(
                                        startX, startY, controlX, controlY, endX, endY, progress)
                                    const ahead = pointOnCurve(
                                        startX, startY, controlX, controlY, endX, endY,
                                        Math.min(1, progress + 0.02))
                                    const angle = Math.atan2(ahead.y - head.y, ahead.x - head.x)
                                    if (age <= flightDuration) {
                                        ctx.save()
                                        ctx.translate(head.x, head.y)
                                        ctx.rotate(angle)
                                        ctx.fillStyle = brightColor
                                        ctx.beginPath()
                                        ctx.moveTo(8, 0)
                                        ctx.lineTo(0, -4.5)
                                        ctx.lineTo(-6, 0)
                                        ctx.lineTo(0, 4.5)
                                        ctx.closePath()
                                        ctx.fill()
                                        ctx.restore()
                                    }
                                } else {
                                    const head = pointOnLine(
                                        startX, startY, endX, endY, progress)
                                    if (unitType === "strike_drone") {
                                        for (let side of [-2.2, 2.2]) {
                                            drawPulseLine(
                                                ctx,
                                                startX + normalX * side,
                                                startY + normalY * side,
                                                head.x + normalX * side,
                                                head.y + normalY * side,
                                                3.8, 1.5, color, brightColor)
                                        }
                                        if (age <= flightDuration) {
                                            drawPulseLine(
                                                ctx,
                                                head.x - ux * 8, head.y - uy * 8,
                                                head.x + ux * 2, head.y + uy * 2,
                                                5.4, 2.6, color, brightColor)
                                        }
                                    } else if (unitType === "ground_vehicle") {
                                        const tail = pointOnLine(
                                            startX, startY, endX, endY,
                                            Math.max(0, progress - 0.22))
                                        drawPulseLine(
                                            ctx, tail.x, tail.y, head.x, head.y,
                                            7, 3.2, color, brightColor)
                                    } else {
                                        drawPulseLine(
                                            ctx, startX, startY, head.x, head.y,
                                            3.2, 1.4, color, brightColor)
                                        if (age <= flightDuration) {
                                            ctx.fillStyle = brightColor
                                            ctx.beginPath()
                                            ctx.arc(head.x, head.y, 3, 0, Math.PI * 2)
                                            ctx.fill()
                                        }
                                    }
                                }

                                drawFeedback(
                                    ctx, event, endX, endY, age,
                                    normalX, normalY, color, brightColor)
                            }

                            ctx.globalAlpha = 1
                        }
                    }

                    Timer {
                        interval: 33
                        repeat: true
                        running: attackCanvas.displayedEvents.length > 0
                        onTriggered: {
                            attackCanvas.pruneEvents()
                            attackCanvas.requestPaint()
                        }
                    }

                    Repeater {
                        id: unitRepeater
                        objectName: "unitRepeater"
                        model: unitListModel

                        delegate: Item {
                            id: unitDelegate
                            objectName: "unit-" + unitId
                            required property string unitId
                            required property string unitName
                            required property string team
                            required property string unitType
                            required property string domain
                            required property real worldX
                            required property real worldY
                            required property int hp
                            required property int maxHp
                            required property int ammo
                            required property int maxAmmo
                            required property string status
                            required property real detectRange
                            required property real attackRange
                            required property bool destroyed
                            required property string engagement
                            readonly property real glyphSize: root.mapStyle === "tactical"
                                ? 52 : root.clamp(52 * battlefieldViewport.scaleFactor, 24, 52)
                            readonly property bool showDetails: root.mapStyle === "tactical"
                                || battlefieldViewport.zoomLevel >= 1.7
                                || root.selectedUnitId === unitId || unitHitTarget.containsMouse
                            property real displayedWorldX: worldX
                            property real displayedWorldY: worldY

                            width: 88
                            height: 88
                            x: displayedWorldX * battlefieldViewport.scaleFactor - width / 2
                            y: displayedWorldY * battlefieldViewport.scaleFactor - glyphSize / 2
                            visible: root.snap.show_wrecks || !destroyed
                            opacity: destroyed ? 0.42 : 1
                            z: root.selectedUnitId === unitId || unitHitTarget.containsMouse ? 6 : 5

                            Behavior on displayedWorldX {
                                enabled: !root.deploymentMode
                                NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
                            }
                            Behavior on displayedWorldY {
                                enabled: !root.deploymentMode
                                NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
                            }

                            Rectangle {
                                id: unitShape
                                width: unitDelegate.glyphSize
                                height: width
                                radius: width / 2
                                anchors.horizontalCenter: parent.horizontalCenter
                                color: root.alphaColor(
                                    unitDelegate.team === "red" ? root.redColor : root.blueColor,
                                    unitDelegate.destroyed ? 0.08 : 0.18)
                                border.width: root.selectedUnitId === unitDelegate.unitId ? 2 : 0
                                border.color: "#ffd166"

                                Image {
                                    id: unitIcon
                                    objectName: "unitIcon-" + unitDelegate.unitId
                                    anchors.centerIn: parent
                                    width: parent.width * 0.85
                                    height: width
                                    source: "../assets/unit_icons/"
                                            + unitDelegate.unitType + ".png"
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    mipmap: true
                                }
                            }

                            Rectangle {
                                anchors.top: unitShape.bottom
                                anchors.topMargin: 4
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: unitDelegate.glyphSize + 4
                                height: 4
                                radius: 2
                                color: "#3a1e29"

                                Rectangle {
                                    width: parent.width * Math.max(0, unitDelegate.hp / unitDelegate.maxHp)
                                    height: parent.height
                                    radius: 2
                                    color: unitDelegate.hp / unitDelegate.maxHp < 0.3
                                           ? root.redColor : root.accentColor
                                }
                            }

                            Text {
                                anchors.top: unitShape.bottom
                                anchors.topMargin: 11
                                visible: unitDelegate.showDetails
                                width: parent.width
                                text: unitDelegate.unitName
                                color: "#dce8f6"
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 10
                                elide: Text.ElideRight
                                horizontalAlignment: Text.AlignHCenter
                            }

                            Text {
                                anchors.top: unitShape.bottom
                                anchors.topMargin: 27
                                visible: unitDelegate.showDetails
                                width: parent.width
                                text: root.unitStatusLabel(unitDelegate.status) + " · " + unitDelegate.engagement
                                color: root.mutedColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 8
                                horizontalAlignment: Text.AlignHCenter
                            }

                            MouseArea {
                                id: unitHitTarget
                                objectName: "selectUnit-" + unitDelegate.unitId
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: -4
                                width: Math.max(32, unitDelegate.glyphSize + 8)
                                height: width
                                hoverEnabled: true
                                enabled: !root.deploymentMode
                                cursorShape: Qt.PointingHandCursor
                                onClicked: viewModel.selectUnit(unitDelegate.unitId)
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        z: 4.5
                        enabled: !root.deploymentMode
                        onClicked: function(mouse) {
                            viewModel.pointerPress(1, mouse.x / battlefieldViewport.scaleFactor,
                                                   mouse.y / battlefieldViewport.scaleFactor)
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        z: 10
                        enabled: root.deploymentMode
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        hoverEnabled: true
                        cursorShape: root.deploymentMode ? Qt.CrossCursor : Qt.ArrowCursor

                        onPressed: function(mouse) {
                            const button = mouse.button === Qt.RightButton ? 3 : 1
                            viewModel.pointerPress(
                                button,
                                mouse.x / battlefieldViewport.scaleFactor,
                                mouse.y / battlefieldViewport.scaleFactor
                            )
                        }
                        onPositionChanged: function(mouse) {
                            if (pressed) {
                                viewModel.pointerMove(
                                    mouse.x / battlefieldViewport.scaleFactor,
                                    mouse.y / battlefieldViewport.scaleFactor
                                )
                            }
                        }
                        onReleased: function(mouse) {
                            const button = mouse.button === Qt.RightButton ? 3 : 1
                            viewModel.pointerRelease(
                                button,
                                mouse.x / battlefieldViewport.scaleFactor,
                                mouse.y / battlefieldViewport.scaleFactor
                            )
                        }
                    }
                }

                MouseArea {
                    id: mapNavigation
                    objectName: "mapNavigation"
                    anchors.fill: parent
                    z: 20
                    acceptedButtons: Qt.MiddleButton
                    preventStealing: true
                    hoverEnabled: true
                    property real lastX: 0
                    property real lastY: 0
                    cursorShape: pressed ? Qt.ClosedHandCursor
                        : root.deploymentMode ? Qt.CrossCursor : Qt.ArrowCursor
                    onPressed: function(mouse) {
                        lastX = mouse.x
                        lastY = mouse.y
                    }
                    onPositionChanged: function(mouse) {
                        if (!pressed) return
                        battlefieldViewport.panX += mouse.x - lastX
                        battlefieldViewport.panY += mouse.y - lastY
                        lastX = mouse.x
                        lastY = mouse.y
                        battlefieldViewport.constrainPan()
                    }
                    onWheel: function(wheel) {
                        const delta = wheel.angleDelta.y || wheel.pixelDelta.y
                        if (delta !== 0) battlefieldViewport.zoomAt(
                            battlefieldViewport.zoomLevel * Math.pow(1.15, delta / 120), wheel.x, wheel.y)
                        wheel.accepted = true
                    }
                }

                Rectangle {
                    anchors.top: parent.top
                    anchors.right: parent.right
                    anchors.margins: 7
                    width: 34
                    height: 42
                    radius: 6
                    color: "#b8091924"
                    border.color: "#507185"
                    z: 30
                    Text {
                        anchors.centerIn: parent
                        text: "N\n↑"
                        color: "#d7eee6"
                        font.family: "Consolas"
                        font.pixelSize: 13
                        horizontalAlignment: Text.AlignHCenter
                    }
                }

                MapOverview {
                    objectName: "mapOverview"
                    anchors.bottom: parent.bottom
                    anchors.right: parent.right
                    anchors.margins: 7
                    width: root.width < 1100 ? 116 : 148
                    height: root.width < 1100 ? 99 : 121
                    z: 30
                    worldWidth: root.snap.map.width
                    worldHeight: root.snap.map.height
                    visual: root.mapVisual
                    units: root.snap.units || []
                    visibleX: battlefieldViewport.visibleWorldX
                    visibleY: battlefieldViewport.visibleWorldY
                    visibleWidth: battlefieldViewport.visibleWorldWidth
                    visibleHeight: battlefieldViewport.visibleWorldHeight
                    onCenterRequested: function(worldX, worldY) { battlefieldViewport.centerOn(worldX, worldY) }
                }
            }

            Rectangle {
                id: messageBar
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 12
                height: 38
                radius: 8
                color: "#13243a"
                border.color: "#294461"

                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    verticalAlignment: Text.AlignVCenter
                    text: root.snap.message
                    color: "#b9cadc"
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 12
                    elide: Text.ElideRight
                }
            }
        }

        Rectangle {
            id: sidePanel
            Layout.preferredWidth: root.width < 1300 ? 320 : 370
            Layout.minimumWidth: 300
            Layout.fillHeight: true
            radius: 14
            color: root.panelColor
            border.color: "#203955"

            ScrollView {
                id: sideScroll
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                contentWidth: availableWidth

                Column {
                    width: sideScroll.availableWidth
                    spacing: 12

                    Loader {
                        width: parent.width
                        sourceComponent: root.deploymentMode ? deploymentControls : runtimeControls
                    }

                    UnitDetails {
                        objectName: "unitDetails"
                        width: parent.width
                        visible: !root.deploymentMode
                        unit: viewModel.selectedUnit
                        onClearSelection: viewModel.selectUnit("")
                    }

                    Rectangle {
                        width: parent.width
                        height: 1
                        color: "#263d5a"
                    }

                    SectionTitle {
                        text: "战场统计"
                    }

                    GridLayout {
                        width: parent.width
                        columns: 2
                        columnSpacing: 8
                        rowSpacing: 8

                        StatPair {
                            Layout.fillWidth: true
                            label: "剩余单位"
                            redValue: String(root.snap.statistics.red_remaining)
                            blueValue: String(root.snap.statistics.blue_remaining)
                        }
                        StatPair {
                            Layout.fillWidth: true
                            label: "战斗力"
                            redValue: String(root.snap.statistics.red_strength)
                            blueValue: String(root.snap.statistics.blue_strength)
                        }
                        StatPair {
                            Layout.fillWidth: true
                            label: "击毁"
                            redValue: String(root.snap.statistics.red_kills)
                            blueValue: String(root.snap.statistics.blue_kills)
                        }
                        StatPair {
                            Layout.fillWidth: true
                            label: "累计伤害"
                            redValue: String(root.snap.statistics.red_damage)
                            blueValue: String(root.snap.statistics.blue_damage)
                        }
                        StatPair {
                            Layout.fillWidth: true
                            label: "发现目标"
                            redValue: String(root.snap.statistics.red_detected)
                            blueValue: String(root.snap.statistics.blue_detected)
                        }
                        StatPair {
                            Layout.fillWidth: true
                            label: "命中次数"
                            redValue: String(root.snap.statistics.red_hits)
                            blueValue: String(root.snap.statistics.blue_hits)
                        }
                        Rectangle {
                            Layout.columnSpan: 2
                            Layout.fillWidth: true
                            Layout.preferredHeight: 86
                            radius: 10
                            color: "#13243a"
                            border.color: "#263d5a"

                            Column {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 7

                                Text {
                                    width: parent.width
                                    text: "基地耐久"
                                    color: root.mutedColor
                                    font.family: "Microsoft YaHei"
                                    font.pixelSize: 11
                                    horizontalAlignment: Text.AlignHCenter
                                }

                                Row {
                                    width: parent.width
                                    height: 42
                                    spacing: 10

                                    Column {
                                        width: (parent.width - parent.spacing * 2 - 1) / 2
                                        spacing: 2

                                        Text {
                                            width: parent.width
                                            text: "红方基地"
                                            color: root.redColor
                                            font.family: "Microsoft YaHei"
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                        }
                                        Text {
                                            width: parent.width
                                            text: root.snap.statistics.red_base_hp
                                                  + " / " + root.snap.statistics.red_base_max
                                            color: root.redColor
                                            font.family: "Consolas"
                                            font.pixelSize: 19
                                            font.bold: true
                                            minimumPixelSize: 12
                                            fontSizeMode: Text.Fit
                                            horizontalAlignment: Text.AlignHCenter
                                        }
                                    }

                                    Rectangle {
                                        width: 1
                                        height: 36
                                        anchors.verticalCenter: parent.verticalCenter
                                        color: "#314964"
                                    }

                                    Column {
                                        width: (parent.width - parent.spacing * 2 - 1) / 2
                                        spacing: 2

                                        Text {
                                            width: parent.width
                                            text: "蓝方基地"
                                            color: root.blueColor
                                            font.family: "Microsoft YaHei"
                                            font.pixelSize: 10
                                            horizontalAlignment: Text.AlignHCenter
                                        }
                                        Text {
                                            width: parent.width
                                            text: root.snap.statistics.blue_base_hp
                                                  + " / " + root.snap.statistics.blue_base_max
                                            color: root.blueColor
                                            font.family: "Consolas"
                                            font.pixelSize: 19
                                            font.bold: true
                                            minimumPixelSize: 12
                                            fontSizeMode: Text.Fit
                                            horizontalAlignment: Text.AlignHCenter
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Rectangle {
                        width: parent.width
                        height: 108
                        radius: 10
                        color: root.cardColor
                        border.color: "#263d5a"

                        Column {
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 6

                            Text {
                                text: "态势研判"
                                color: root.mutedColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 11
                            }
                            Text {
                                text: "红方  " + root.snap.statistics.red_situation
                                      + " · " + root.snap.statistics.red_tactics
                                color: root.redColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 13
                            }
                            Text {
                                text: "蓝方  " + root.snap.statistics.blue_situation
                                      + " · " + root.snap.statistics.blue_tactics
                                color: root.blueColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 13
                            }
                            Text {
                                text: "集火  " + root.snap.statistics.red_focus
                                      + " / " + root.snap.statistics.blue_focus
                                color: "#c7d6e6"
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                width: parent.width
                            }
                        }
                    }

                    SectionTitle {
                        text: "实时日志"
                    }

                    ComboBox {
                        id: logCategory
                        objectName: "logCategorySelector"
                        width: parent.width
                        textRole: "label"
                        model: [
                            { label: "全部事件", value: "all" },
                            { label: "侦察与目标共享", value: "scout" },
                            { label: "攻击与命中", value: "attack" },
                            { label: "摧毁事件", value: "destroyed" },
                            { label: "战术、状态与结果", value: "state" }
                        ]
                        onActivated: root.logFilter = model[currentIndex].value
                        palette.button: "#182a42"
                        palette.buttonText: "#dce8f6"
                        palette.base: "#13243a"
                        palette.text: "#dce8f6"
                    }

                    Rectangle {
                        width: parent.width
                        height: 200
                        radius: 10
                        color: "#0b1726"
                        border.color: "#263d5a"
                        clip: true

                        ListView {
                            id: logView
                            anchors.fill: parent
                            anchors.margins: 9
                            spacing: 6
                            clip: true
                            model: root.filteredLogs()
                            ScrollBar.vertical: ScrollBar { }
                            onCountChanged: positionViewAtEnd()

                            Text {
                                width: parent.width
                                visible: logView.count === 0
                                text: root.deploymentMode ? "等待开始仿真" : "暂无此类事件"
                                color: root.mutedColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 11
                            }

                            delegate: Text {
                                required property string modelData
                                width: logView.width - 12
                                text: modelData
                                color: modelData.indexOf("[Attack]") === 0 ? "#ffd166"
                                    : modelData.indexOf("[Destroyed]") === 0 ? root.redColor : "#9fb4c9"
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "Enter 开始 · Space 暂停 · S 单步 · F 变速 · F1 帮助"
                        color: "#71879e"
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }

    Component {
        id: deploymentControls

        Column {
            width: parent ? parent.width : 320
            spacing: 10

            SectionTitle { text: "场景与地图" }

            ComboBox {
                id: scenarioSelector
                objectName: "scenarioSelector"
                width: parent.width
                model: root.snap.scenarios || []
                textRole: "name"
                displayText: root.snap.scene_name || root.snap.current_scenario || "选择场景"
                currentIndex: root.scenarioIndex()
                onActivated: {
                    root.selectScenario(currentIndex)
                    currentIndex = Qt.binding(function() { return root.scenarioIndex() })
                }
                palette.button: "#182a42"
                palette.buttonText: "#dce8f6"
                palette.base: "#13243a"
                palette.text: "#dce8f6"
            }

            Text {
                width: parent.width
                text: "单位模式左键放置；障碍模式左键拖拽绘制。左键选中障碍后 Delete 删除；右键直接删除对象。\n滚轮缩放 · 中键拖动地图 · 总览点击定位"
                color: root.mutedColor
                font.family: "Microsoft YaHei"
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }

            Row {
                width: parent.width
                spacing: 8
                AppButton { width: (parent.width - 8) / 2; text: "载入地图…"; onClicked: root.requestLoadMap() }
                AppButton { width: (parent.width - 8) / 2; text: "保存地图"; onClicked: viewModel.saveMap() }
            }
            AppButton { width: parent.width; text: "地图另存为…"; onClicked: saveMapDialog.open() }

            Row {
                width: parent.width
                spacing: 6
                Repeater {
                    model: [
                        { style: "tactical", label: "战术" },
                        { style: "valley", label: "山谷" },
                        { style: "river", label: "河谷" }
                    ]
                    delegate: AppButton {
                        required property var modelData
                        width: (parent.width - 12) / 3
                        text: modelData.label
                        selected: root.mapStyle === modelData.style
                        onClicked: viewModel.setMapStyle(modelData.style)
                    }
                }
            }

            SectionTitle { text: "部署控制" }

            Row {
                width: parent.width
                spacing: 8

                AppButton {
                    width: (parent.width - 8) / 2
                    text: "当前：红方"
                    tone: root.redColor
                    selected: root.snap.deployment.selected_team === "red"
                    onClicked: {
                        if (root.snap.deployment.selected_team !== "red")
                            viewModel.toggleTeam()
                    }
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: "当前：蓝方"
                    tone: root.blueColor
                    selected: root.snap.deployment.selected_team === "blue"
                    onClicked: {
                        if (root.snap.deployment.selected_team !== "blue")
                            viewModel.toggleTeam()
                    }
                }
            }

            SectionTitle { text: "作战单位" }

            Grid {
                width: parent.width
                columns: 2
                spacing: 8

                AppButton {
                    width: (parent.width - 8) / 2
                    text: "1  侦察无人机"
                    selected: root.snap.deployment.selected_unit_type === "scout_drone"
                    onClicked: viewModel.selectUnitType("scout_drone")
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: "2  打击无人机"
                    selected: root.snap.deployment.selected_unit_type === "strike_drone"
                    onClicked: viewModel.selectUnitType("strike_drone")
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: "3  无人战车"
                    selected: root.snap.deployment.selected_unit_type === "ground_vehicle"
                    onClicked: viewModel.selectUnitType("ground_vehicle")
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: "4  导弹发射车"
                    selected: root.snap.deployment.selected_unit_type === "missile_vehicle"
                    onClicked: viewModel.selectUnitType("missile_vehicle")
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: "5  指挥节点"
                    selected: root.snap.deployment.selected_unit_type === "command_node"
                    onClicked: viewModel.selectUnitType("command_node")
                }
            }

            AppButton {
                width: parent.width
                text: "撤销上次兵种放置"
                onClicked: viewModel.undoDeployment()
            }

            SectionTitle { text: "地图障碍" }

            Row {
                width: parent.width
                spacing: 7

                AppButton {
                    width: (parent.width - 14) / 3
                    text: "6 山地"
                    tone: "#7db08b"
                    selected: root.snap.deployment.selected_obstacle_type === "mountain"
                    onClicked: viewModel.selectObstacleType("mountain")
                }
                AppButton {
                    width: (parent.width - 14) / 3
                    text: "7 建筑"
                    tone: "#8da8cc"
                    selected: root.snap.deployment.selected_obstacle_type === "building"
                    onClicked: viewModel.selectObstacleType("building")
                }
                AppButton {
                    width: (parent.width - 14) / 3
                    text: "8 禁行区"
                    tone: root.redColor
                    selected: root.snap.deployment.selected_obstacle_type === "restricted"
                    onClicked: viewModel.selectObstacleType("restricted")
                }
            }

            AppButton {
                width: parent.width
                text: "删除选中障碍"
                tone: "#ffca64"
                onClicked: viewModel.deleteSelected()
            }

            SectionTitle { text: "全局地图操作" }

            AppButton {
                width: parent.width
                text: "清空全部兵种与障碍"
                tone: root.redColor
                onClicked: root.confirmAction("清空部署", "清空全部兵种和障碍？基地与地图尺寸会保留。",
                                             function() { viewModel.clearDeployment() })
            }
        }
    }

    Component {
        id: runtimeControls

        Column {
            width: parent ? parent.width : 320
            spacing: 10

            SectionTitle { text: "运行观察" }

            Text {
                width: parent.width
                text: "点击单位查看详情与范围。滚轮缩放，中键拖动地图；右下总览可点击定位。"
                color: root.mutedColor
                font.family: "Microsoft YaHei"
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }

            AppButton {
                width: parent.width
                text: root.snap.show_wrecks ? "隐藏残骸" : "显示残骸"
                onClicked: viewModel.toggleWrecks()
            }

            AppButton {
                width: parent.width
                visible: root.snap.game_state === "finished"
                text: "查看本局结算"
                tone: "#ffca64"
                onClicked: resultsDialog.open()
            }

            Rectangle {
                width: parent.width
                height: 56
                radius: 10
                color: root.snap.statistics.winner ? root.alphaColor(root.redColor, 0.14) : root.cardColor
                border.color: root.snap.statistics.winner ? root.redColor : "#263d5a"

                Text {
                    anchors.centerIn: parent
                    text: root.snap.statistics.winner === "red" ? "红方获胜"
                          : root.snap.statistics.winner === "blue" ? "蓝方获胜"
                          : root.snap.statistics.winner === "draw" ? "双方平局"
                          : "交战进行中"
                    color: root.snap.statistics.winner ? "#ffffff" : root.accentColor
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 17
                    font.bold: true
                }
            }
        }
    }

    footer: Rectangle {
        objectName: "workflowControls"
        height: 64
        color: "#0c192a"
        border.color: "#203955"

        RowLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            AppButton {
                Layout.preferredWidth: 100
                text: root.snap.game_state === "finished" ? "再来一局" : "开始仿真"
                tone: root.accentColor
                selected: root.deploymentMode || root.snap.game_state === "finished"
                enabled: root.deploymentMode || root.snap.game_state === "finished"
                onClicked: root.deploymentMode ? viewModel.startSimulation() : viewModel.restartSimulation()
            }
            AppButton {
                Layout.preferredWidth: 84
                text: root.snap.game_state === "paused" ? "继续" : "暂停"
                tone: "#ffca64"
                selected: root.snap.game_state === "paused"
                enabled: root.snap.game_state === "running" || root.snap.game_state === "paused"
                onClicked: viewModel.togglePause()
            }
            AppButton {
                Layout.preferredWidth: 82
                text: "单步推进"
                enabled: root.snap.game_state === "paused"
                onClicked: viewModel.stepSimulation()
            }
            Text {
                text: "速度"
                color: root.mutedColor
                font.family: "Microsoft YaHei"
                font.pixelSize: 12
            }
            Repeater {
                model: ["1×", "2×", "4×", "快速"]
                delegate: AppButton {
                    required property string modelData
                    required property int index
                    Layout.preferredWidth: 52
                    text: modelData
                    selected: root.snap.speed_index === index
                    enabled: root.snap.game_state !== "finished"
                    onClicked: viewModel.setSpeed(index)
                }
            }
            Item { Layout.fillWidth: true }
            AppButton {
                Layout.preferredWidth: 104
                text: "返回部署"
                tone: root.redColor
                enabled: !root.deploymentMode
                onClicked: root.requestReset()
            }
            AppButton {
                Layout.preferredWidth: 66
                text: "帮助"
                onClicked: helpDialog.open()
            }
        }
    }

    Dialog {
        id: confirmationDialog
        objectName: "clearConfirmation"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(440, root.width - 40)
        modal: true
        title: root.pendingTitle
        palette.window: "#14243a"
        palette.windowText: "#eaf4ff"
        palette.button: "#203653"
        palette.buttonText: "#eaf4ff"
        background: Rectangle { color: "#14243a"; radius: 12; border.color: "#3a526d" }
        header: Text {
            text: root.pendingTitle
            color: "#eaf4ff"
            padding: 18
            bottomPadding: 8
            font.family: "Microsoft YaHei"
            font.pixelSize: 16
            font.bold: true
        }
        contentItem: Text {
            text: root.pendingMessage
            color: "#dce8f6"
            font.family: "Microsoft YaHei"
            font.pixelSize: 13
            wrapMode: Text.Wrap
        }
        footer: Item {
            implicitHeight: 56
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.bottomMargin: 18
                spacing: 8
                ActionButton { Layout.fillWidth: true; text: "取消"; onClicked: confirmationDialog.reject() }
                ActionButton { Layout.fillWidth: true; text: "确认"; highlighted: true; onClicked: confirmationDialog.accept() }
            }
        }
        onAccepted: {
            const action = root.pendingAction
            root.pendingAction = null
            if (action) action()
        }
        onRejected: root.pendingAction = null
    }

    FileDialog {
        id: loadMapDialog
        objectName: "loadMapDialog"
        title: "载入战场地图"
        currentFolder: viewModel.userScenarioUrl
        nameFilters: ["战场地图 (*.json)"]
        onAccepted: viewModel.loadMapFromUrl(selectedFile)
    }
    FileDialog {
        id: saveMapDialog
        objectName: "saveMapDialog"
        title: "地图另存为"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        currentFolder: viewModel.userScenarioUrl
        nameFilters: ["战场地图 (*.json)"]
        onAccepted: viewModel.saveMapToUrl(selectedFile)
    }
    FileDialog {
        id: exportDialog
        objectName: "exportDialog"
        title: "导出本局战报"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        currentFolder: viewModel.userScenarioUrl
        nameFilters: ["战报数据 (*.json)"]
        onAccepted: viewModel.exportResultToUrl(selectedFile)
    }

    FileDialog {
        id: exportRecordsDialog
        objectName: "exportRecordsDialog"
        title: "导出运行记录（" + root.recordCategoryLabel(root.recordFilter === "all" ? "全部" : root.recordFilter) + "）"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        currentFolder: viewModel.userScenarioUrl
        nameFilters: ["运行记录 (*.json)"]
        onAccepted: viewModel.exportRecordsToUrl(selectedFile, root.recordFilter)
    }

    Dialog {
        id: timingDialog
        objectName: "timingDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(480, root.width - 40)
        height: Math.min(390, root.height - 40)
        modal: true
        title: "时间设置"
        property string validationError: ""
        padding: 18
        palette.windowText: "#eaf4ff"
        palette.base: "#0d1a2a"
        palette.text: "#eaf4ff"
        palette.button: "#182a42"
        palette.buttonText: "#eaf4ff"
        background: Rectangle { radius: 12; color: "#14243a"; border.color: "#36516e" }
        header: Text {
            text: timingDialog.title
            color: "#eaf4ff"
            padding: 18
            bottomPadding: 8
            font.family: "Microsoft YaHei"
            font.pixelSize: 16
            font.bold: true
        }
        onOpened: {
            stepDurationField.text = String(root.timing.step_duration_seconds)
            maxStepsField.text = String(root.timing.max_steps)
            validationError = ""
        }
        contentItem: ScrollView {
            id: timingScroll
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: timingScroll.availableWidth
                spacing: 12
                Text {
                    Layout.fillWidth: true
                    text: root.timing.editable ? "部署或暂停时可修改；暂停修改后从下一步生效。"
                        : root.snap.game_state === "running" ? "当前正在运行，请先暂停再修改。" : "本局已结束，请返回部署后修改。"
                    color: root.timing.editable ? root.mutedColor : "#ffca64"
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                Label { text: "单步时长（秒，0.01–60）"; color: "#dce8f6" }
                TextField {
                    id: stepDurationField
                    objectName: "stepDurationField"
                    Layout.fillWidth: true
                    enabled: root.timing.editable
                    selectByMouse: true
                    inputMethodHints: Qt.ImhFormattedNumbersOnly
                    validator: DoubleValidator { bottom: 0.01; top: 60; decimals: 6; notation: DoubleValidator.StandardNotation; locale: "C" }
                    Accessible.name: "单步时长（秒）"
                }
                Label { text: "最大运行步数（1–1,000,000）"; color: "#dce8f6" }
                TextField {
                    id: maxStepsField
                    objectName: "maxStepsField"
                    Layout.fillWidth: true
                    enabled: root.timing.editable
                    selectByMouse: true
                    inputMethodHints: Qt.ImhDigitsOnly
                    validator: IntValidator { bottom: 1; top: 1000000 }
                    Accessible.name: "最大运行步数"
                }
                Text {
                    Layout.fillWidth: true
                    text: "单步时长控制累计仿真时间与播放节奏；移动、侦察与攻击规则仍按步推进。速度倍率仅影响播放。"
                    color: root.mutedColor
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }
                Text {
                    objectName: "timingValidationError"
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: timingDialog.validationError
                    color: root.redColor
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
            }
        }
        footer: Item {
            implicitHeight: 58
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                ActionButton { Layout.fillWidth: true; text: "关闭"; onClicked: timingDialog.close() }
                ActionButton {
                    objectName: "applyTimingButton"
                    Layout.fillWidth: true
                    text: "应用设置"
                    highlighted: true
                    enabled: root.timing.editable
                    onClicked: {
                        const duration = Number(stepDurationField.text)
                        const limit = Number(maxStepsField.text)
                        if (!stepDurationField.acceptableInput || !maxStepsField.acceptableInput
                            || !isFinite(duration) || !isFinite(limit)) {
                            timingDialog.validationError = "请填写范围内的单步时长和整数步数。"
                            return
                        }
                        if (limit < Number(root.snap.statistics.time_step || 0)) {
                            timingDialog.validationError = "最大运行步数不能小于已经运行的步数。"
                            return
                        }
                        viewModel.setTiming(duration, limit)
                        if (Number(root.timing.step_duration_seconds) === duration && Number(root.timing.max_steps) === limit)
                            timingDialog.close()
                        else timingDialog.validationError = root.snap.message || "设置未生效，请检查当前状态。"
                    }
                }
            }
        }
    }

    Dialog {
        id: recordsDialog
        objectName: "recordsDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(780, root.width - 40)
        height: Math.min(650, root.height - 40)
        modal: true
        title: "运行记录"
        padding: 18
        palette.windowText: "#eaf4ff"
        palette.base: "#14243a"
        palette.text: "#eaf4ff"
        palette.button: "#182a42"
        palette.buttonText: "#eaf4ff"
        background: Rectangle { radius: 12; color: "#101d2e"; border.color: "#36516e" }
        header: Text {
            text: recordsDialog.title
            color: "#eaf4ff"
            padding: 18
            bottomPadding: 8
            font.family: "Microsoft YaHei"
            font.pixelSize: 16
            font.bold: true
        }
        contentItem: ColumnLayout {
            spacing: 9
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: root.recording.has_run ? "累计 " + root.recording.record_count + " 条 · 界面展示最近 200 条中的匹配记录"
                        : "开始仿真后，侦察、共享、摧毁、战术状态与结果将自动记录。"
                    color: root.mutedColor
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                ComboBox {
                    id: recordCategorySelector
                    objectName: "recordCategorySelector"
                    Layout.preferredWidth: 104
                    textRole: "label"
                    valueRole: "key"
                    model: [
                        {label: "全部", key: "all"}, {label: "侦察", key: "scout"},
                        {label: "共享", key: "sharing"}, {label: "摧毁", key: "destroyed"},
                        {label: "战术", key: "tactical"}, {label: "结果", key: "result"},
                        {label: "设置", key: "settings"}, {label: "运行", key: "lifecycle"},
                        {label: "交战", key: "combat"}
                    ]
                    Accessible.name: "运行记录类别"
                    onActivated: root.recordFilter = currentValue
                }
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 130
                color: "#0a1525"
                radius: 8
                border.color: "#263d5a"
                ListView {
                    id: recordsList
                    objectName: "recordsList"
                    anchors.fill: parent
                    anchors.margins: 8
                    clip: true
                    spacing: 5
                    model: root.filteredRecords()
                    ScrollBar.vertical: ScrollBar {}
                    delegate: Column {
                        id: recordRow
                        required property var modelData
                        width: recordsList.width
                        spacing: 3
                        Text {
                            width: parent.width
                            text: "#" + recordRow.modelData.seq + " · 第 " + recordRow.modelData.step + " 步 · "
                                + root.secondsLabel(recordRow.modelData.elapsed_seconds) + " · "
                                + root.recordCategoryLabel(recordRow.modelData.category)
                            color: recordRow.modelData.category === "destroyed" ? root.redColor : root.accentColor
                            font.family: "Microsoft YaHei"
                            font.pixelSize: 11
                            wrapMode: Text.Wrap
                        }
                        Text {
                            width: parent.width
                            text: recordRow.modelData.message || ""
                            color: "#dce8f6"
                            font.family: "Microsoft YaHei"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                        }
                        Rectangle { width: parent.width; height: 1; color: "#1d3149" }
                    }
                    Text {
                        anchors.centerIn: parent
                        width: parent.width - 16
                        visible: recordsList.count === 0
                        text: root.recording.has_run ? "此类别暂无记录。导出包含本局全部匹配记录。" : "当前还没有运行记录。"
                        color: root.mutedColor
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: root.recording.last_error ? "自动保存失败：" + root.recording.last_error + "。可手动导出保留记录。"
                    : root.recording.save_path ? "已自动保存：" + root.recording.save_path
                    : root.recording.directory ? "记录自动保存目录：" + root.recording.directory : "运行结束或返回部署时自动保存；手动导出可随时使用。"
                color: root.recording.last_error ? root.redColor : root.mutedColor
                font.family: "Microsoft YaHei"
                font.pixelSize: 11
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 3
                elide: Text.ElideRight
            }
            Text {
                Layout.fillWidth: true
                text: "历史运行（最近 " + Math.min(10, (root.recording.history || []).length) + " 局，可在记录目录中查看完整文件）"
                color: "#dce8f6"
                font.family: "Microsoft YaHei"
                font.pixelSize: 11
                wrapMode: Text.Wrap
                visible: (root.recording.history || []).length > 0
            }
            ScrollView {
                    id: historyScroll
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.min(82, historyColumn.implicitHeight)
                    visible: (root.recording.history || []).length > 0
                    clip: true
                    contentWidth: availableWidth
                    Column {
                        id: historyColumn
                        width: historyScroll.availableWidth
                        spacing: 5
                        Repeater {
                            model: (root.recording.history || []).slice(0, 10)
                            delegate: Text {
                                required property var modelData
                                width: historyColumn.width
                                text: (modelData.scene_name || "当前场景") + " · " + modelData.steps + " 步 · "
                                    + root.secondsLabel(modelData.elapsed_seconds) + " · " + modelData.record_count + " 条 · "
                                    + (modelData.finished ? (modelData.winner === "red" ? "红方胜" : modelData.winner === "blue" ? "蓝方胜" : "平局")
                                       : modelData.run_id === root.recording.run_id && root.snap.game_state === "paused" ? "已暂停"
                                       : modelData.run_id === root.recording.run_id && root.snap.game_state === "running" ? "运行中" : "已中止")
                                    + "\n" + (modelData.save_path || "尚未保存")
                                color: root.mutedColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 11
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
            }
        }
        footer: Item {
            implicitHeight: 58
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                ActionButton { Layout.fillWidth: true; text: "关闭"; onClicked: recordsDialog.close() }
                ActionButton {
                    objectName: "openRecordsDirectoryButton"
                    Layout.fillWidth: true
                    text: "打开记录目录"
                    enabled: !!root.recording.has_run || (root.recording.history || []).length > 0
                    onClicked: Qt.openUrlExternally(viewModel.recordingDirectoryUrl)
                }
                ActionButton {
                    objectName: "exportRecordsButton"
                    Layout.fillWidth: true
                    text: "导出此类别全部记录…"
                    highlighted: true
                    enabled: !!root.recording.has_run
                    onClicked: exportRecordsDialog.open()
                }
            }
        }
    }

    ResultsDialog {
        id: resultsDialog
        objectName: "resultsDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(650, root.width - 40)
        height: Math.min(500, root.height - 40)
        stats: root.snap.statistics
        destroyedUnits: root.recording.destroyed_units || []
        sceneName: root.snap.scene_name || root.snap.current_scenario || "当前场景"
        onReturnToMap: close()
        onRestart: { close(); viewModel.restartSimulation() }
        onEditDeployment: { close(); viewModel.resetSimulation() }
        onExportResult: exportDialog.open()
        onViewRecords: { close(); recordsDialog.open() }
    }

    HelpDialog {
        id: helpDialog
        objectName: "helpDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(680, root.width - 40)
        height: Math.min(580, root.height - 40)
        onClosed: viewModel.dismissHelp()
    }

    Connections {
        target: viewModel
        function onSnapshotChanged() {
            battleCanvas.requestPaint()
            attackCanvas.syncEvents(root.snap.attack_events || [])
            if (root.snap.game_state === "finished" && !root.resultPresented) {
                root.resultPresented = true
                resultsDialog.open()
            } else if (root.snap.game_state !== "finished") {
                root.resultPresented = false
                if (resultsDialog.visible) resultsDialog.close()
            }
        }
    }

    Component.onCompleted: {
        if (viewModel.firstRun) Qt.callLater(function() { helpDialog.open() })
    }

    Shortcut { sequence: "F1"; enabled: !root.dialogActive; onActivated: helpDialog.open() }
    Shortcut { sequence: "Return"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.startSimulation() }
    Shortcut { sequence: "Enter"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.startSimulation() }
    Shortcut { sequence: "Space"; enabled: !root.deploymentMode && root.snap.game_state !== "finished" && !root.dialogActive; onActivated: viewModel.togglePause() }
    Shortcut { sequence: "S"; enabled: root.snap.game_state === "paused" && !root.dialogActive; onActivated: viewModel.stepSimulation() }
    Shortcut { sequence: "F"; enabled: root.snap.game_state !== "finished" && !root.dialogActive; onActivated: viewModel.cycleSpeed() }
    Shortcut { sequence: "K"; enabled: !root.deploymentMode && !root.dialogActive; onActivated: viewModel.toggleWrecks() }
    Shortcut { sequence: "R"; enabled: !root.deploymentMode && !root.dialogActive; onActivated: root.requestReset() }
    Shortcut { sequence: "Ctrl+S"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.saveMap() }
    Shortcut { sequence: "Ctrl+Shift+S"; enabled: root.deploymentMode && !root.dialogActive; onActivated: saveMapDialog.open() }
    Shortcut { sequence: "L"; enabled: root.deploymentMode && !root.dialogActive; onActivated: root.requestLoadMap() }
    Shortcut { sequence: "T"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.toggleTeam() }
    Shortcut { sequence: "C"; enabled: root.deploymentMode && !root.dialogActive; onActivated: root.confirmAction("清空部署", "清空全部兵种和障碍？基地与地图尺寸会保留。", function() { viewModel.clearDeployment() }) }
    Shortcut { sequence: "Backspace"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.undoDeployment() }
    Shortcut { sequence: "Delete"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.deleteSelected() }
    Shortcut { sequence: "1"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectUnitType("scout_drone") }
    Shortcut { sequence: "2"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectUnitType("strike_drone") }
    Shortcut { sequence: "3"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectUnitType("ground_vehicle") }
    Shortcut { sequence: "4"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectUnitType("missile_vehicle") }
    Shortcut { sequence: "5"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectUnitType("command_node") }
    Shortcut { sequence: "6"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectObstacleType("mountain") }
    Shortcut { sequence: "7"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectObstacleType("building") }
    Shortcut { sequence: "8"; enabled: root.deploymentMode && !root.dialogActive; onActivated: viewModel.selectObstacleType("restricted") }
}
