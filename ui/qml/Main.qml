pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root
    width: 1440
    height: 900
    minimumWidth: 1180
    minimumHeight: 720
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

    function unitShortName(unitType) {
        if (unitType === "scout_drone") return "侦"
        if (unitType === "strike_drone") return "击"
        if (unitType === "ground_vehicle") return "战"
        if (unitType === "missile_vehicle") return "导"
        return "指"
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
        height: 72
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
                    font.pixelSize: 22
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
                implicitWidth: 118
                implicitHeight: 44
                radius: 8
                color: "#13243a"
                border.color: "#263f5e"

                Column {
                    anchors.centerIn: parent
                    spacing: 1

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "时间步"
                        color: root.mutedColor
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 10
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.snap.statistics.time_step
                        color: "#ffffff"
                        font.family: "Consolas"
                        font.pixelSize: 20
                        font.bold: true
                    }
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 14

        Rectangle {
            id: battlefieldCard
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 720
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
                        text: "战场态势  /  " + root.snap.map.terrain
                        color: "#cfe0f2"
                        font.family: "Microsoft YaHei"
                        font.pixelSize: 13
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
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

            Item {
                id: battlefieldViewport
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: messageBar.top
                anchors.topMargin: 42
                anchors.margins: 14

                readonly property real scaleFactor: Math.min(
                    width / root.snap.map.width,
                    height / root.snap.map.height
                )

                Item {
                    id: battlefield
                    width: root.snap.map.width * battlefieldViewport.scaleFactor
                    height: root.snap.map.height * battlefieldViewport.scaleFactor
                    anchors.centerIn: parent
                    clip: true

                    Canvas {
                        id: battleCanvas
                        anchors.fill: parent
                        z: 1

                        onPaint: {
                            const ctx = getContext("2d")
                            const sx = width / root.snap.map.width
                            const sy = height / root.snap.map.height
                            ctx.clearRect(0, 0, width, height)
                            ctx.fillStyle = "#0a1828"
                            ctx.fillRect(0, 0, width, height)

                            ctx.lineWidth = 1
                            ctx.strokeStyle = "#17314a"
                            for (let x = 0; x <= root.snap.map.width; x += 40) {
                                ctx.beginPath()
                                ctx.moveTo(x * sx, 0)
                                ctx.lineTo(x * sx, height)
                                ctx.stroke()
                            }
                            for (let y = 0; y <= root.snap.map.height; y += 40) {
                                ctx.beginPath()
                                ctx.moveTo(0, y * sy)
                                ctx.lineTo(width, y * sy)
                                ctx.stroke()
                            }

                            for (let i = 0; i < root.snap.units.length; ++i) {
                                const unit = root.snap.units[i]
                                if (unit.destroyed) continue
                                ctx.beginPath()
                                ctx.arc(unit.x * sx, unit.y * sy,
                                        unit.detect_range * sx, 0, Math.PI * 2)
                                ctx.strokeStyle = unit.team === "red"
                                                  ? "rgba(255,93,115,0.16)"
                                                  : "rgba(76,166,255,0.16)"
                                ctx.lineWidth = 1
                                ctx.stroke()
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
                                fillMode: Image.Stretch
                                opacity: 0.5
                                smooth: true
                            }

                            Rectangle {
                                anchors.fill: parent
                                color: "transparent"
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

                            x: modelData.x * battlefieldViewport.scaleFactor - width / 2
                            y: modelData.y * battlefieldViewport.scaleFactor - 34
                            width: 76
                            height: 82
                            z: 3
                            opacity: modelData.destroyed ? 0.4 : 1

                            Rectangle {
                                objectName: "baseBackdrop-" + baseItem.modelData.team
                                property real outlineWidth: 0
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: 62
                                height: 62
                                radius: 31
                                color: root.alphaColor(baseItem.teamColor, 0.18)
                                border.width: outlineWidth
                            }

                            Image {
                                objectName: "baseIcon-" + baseItem.modelData.team
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: 4
                                width: 54
                                height: 54
                                source: "../assets/unit_icons/base_station.png"
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                mipmap: true
                            }

                            Rectangle {
                                anchors.horizontalCenter: parent.horizontalCenter
                                y: 63
                                width: 58
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
                                anchors.topMargin: 70
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

                            width: 88
                            height: 88
                            x: worldX * battlefieldViewport.scaleFactor - width / 2
                            y: worldY * battlefieldViewport.scaleFactor - 27
                            visible: root.snap.show_wrecks || !destroyed
                            opacity: destroyed ? 0.42 : 1
                            z: 5

                            Behavior on x {
                                enabled: !root.deploymentMode
                                NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
                            }
                            Behavior on y {
                                enabled: !root.deploymentMode
                                NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
                            }

                            Rectangle {
                                id: unitShape
                                width: 52
                                height: width
                                radius: width / 2
                                anchors.horizontalCenter: parent.horizontalCenter
                                color: root.alphaColor(
                                    unitDelegate.team === "red" ? root.redColor : root.blueColor,
                                    unitDelegate.destroyed ? 0.08 : 0.18)
                                border.width: 0

                                Image {
                                    id: unitIcon
                                    objectName: "unitIcon-" + unitDelegate.unitId
                                    anchors.centerIn: parent
                                    width: 44
                                    height: 44
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
                                width: 56
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
                                width: parent.width
                                text: unitDelegate.status + " · " + unitDelegate.engagement
                                color: root.mutedColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 8
                                horizontalAlignment: Text.AlignHCenter
                            }
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
            Layout.preferredWidth: 370
            Layout.minimumWidth: 340
            Layout.fillHeight: true
            radius: 14
            color: root.panelColor
            border.color: "#203955"

            ScrollView {
                anchors.fill: parent
                anchors.margins: 12
                clip: true
                contentWidth: availableWidth

                Column {
                    width: sidePanel.width - 42
                    spacing: 12

                    Loader {
                        width: parent.width
                        sourceComponent: root.deploymentMode ? deploymentControls : runtimeControls
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

                    Rectangle {
                        width: parent.width
                        height: 176
                        radius: 10
                        color: "#0b1726"
                        border.color: "#263d5a"
                        clip: true

                        Column {
                            anchors.fill: parent
                            anchors.margins: 9
                            spacing: 3

                            Text {
                                visible: root.snap.logs.length === 0
                                text: root.deploymentMode ? "等待开始仿真" : "暂无战斗日志"
                                color: root.mutedColor
                                font.family: "Microsoft YaHei"
                                font.pixelSize: 11
                            }

                            Repeater {
                                model: root.snap.logs.slice(-8)
                                delegate: Text {
                                    required property string modelData
                                    width: parent.width
                                    text: modelData
                                    color: modelData.indexOf("[Attack]") === 0
                                           ? "#ffd166" : "#9fb4c9"
                                    font.family: "Consolas"
                                    font.pixelSize: 10
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "快捷键  Enter 开始 · Space 暂停 · S 单步 · F 变速 · R 重置"
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
                    text: "1 山地"
                    tone: "#7db08b"
                    selected: root.snap.deployment.selected_obstacle_type === "mountain"
                    onClicked: viewModel.selectObstacleType("mountain")
                }
                AppButton {
                    width: (parent.width - 14) / 3
                    text: "2 建筑"
                    tone: "#8da8cc"
                    selected: root.snap.deployment.selected_obstacle_type === "building"
                    onClicked: viewModel.selectObstacleType("building")
                }
                AppButton {
                    width: (parent.width - 14) / 3
                    text: "3 禁行区"
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
                onClicked: viewModel.clearDeployment()
            }

            Row {
                width: parent.width
                spacing: 8

                AppButton { width: (parent.width - 8) / 2; text: "保存地图"; onClicked: viewModel.saveMap() }
                AppButton { width: (parent.width - 8) / 2; text: "加载地图"; onClicked: viewModel.loadMap() }
            }

            AppButton {
                width: parent.width
                height: 46
                text: "开始仿真"
                tone: root.accentColor
                selected: true
                onClicked: viewModel.startSimulation()
            }
        }
    }

    Component {
        id: runtimeControls

        Column {
            width: parent ? parent.width : 320
            spacing: 10

            SectionTitle { text: "仿真控制" }

            Row {
                width: parent.width
                spacing: 8

                AppButton {
                    width: (parent.width - 8) / 2
                    text: root.snap.game_state === "running" ? "暂停" : "继续"
                    tone: "#ffca64"
                    selected: root.snap.game_state === "paused"
                    enabled: root.snap.game_state !== "finished"
                    onClicked: viewModel.togglePause()
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: "单步推进"
                    onClicked: viewModel.stepSimulation()
                }
            }

            Row {
                width: parent.width
                spacing: 8

                AppButton {
                    width: (parent.width - 8) / 2
                    text: "速度 " + root.snap.speed_label
                    tone: root.accentColor
                    onClicked: viewModel.cycleSpeed()
                }
                AppButton {
                    width: (parent.width - 8) / 2
                    text: root.snap.show_wrecks ? "隐藏残骸" : "显示残骸"
                    onClicked: viewModel.toggleWrecks()
                }
            }

            AppButton {
                width: parent.width
                text: "返回部署并重置"
                tone: root.redColor
                onClicked: viewModel.resetSimulation()
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

    Connections {
        target: viewModel
        function onSnapshotChanged() {
            battleCanvas.requestPaint()
            attackCanvas.syncEvents(root.snap.attack_events || [])
        }
    }

    Item {
        anchors.fill: parent
        focus: true
        Component.onCompleted: forceActiveFocus()

        Keys.onPressed: function(event) {
            if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_S) {
                if (root.deploymentMode) viewModel.saveMap()
                event.accepted = true
                return
            }
            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                if (root.deploymentMode) viewModel.startSimulation()
            } else if (event.key === Qt.Key_Space) {
                viewModel.togglePause()
            } else if (event.key === Qt.Key_S) {
                viewModel.stepSimulation()
            } else if (event.key === Qt.Key_F) {
                viewModel.cycleSpeed()
            } else if (event.key === Qt.Key_K) {
                viewModel.toggleWrecks()
            } else if (event.key === Qt.Key_R) {
                viewModel.resetSimulation()
            } else if (event.key === Qt.Key_T && root.deploymentMode) {
                viewModel.toggleTeam()
            } else if (event.key === Qt.Key_C && root.deploymentMode) {
                viewModel.clearDeployment()
            } else if (event.key === Qt.Key_L && root.deploymentMode) {
                viewModel.loadMap()
            } else if (event.key === Qt.Key_Backspace && root.deploymentMode) {
                viewModel.undoDeployment()
            } else if (event.key === Qt.Key_Delete && root.deploymentMode) {
                viewModel.deleteSelected()
            } else if (event.key === Qt.Key_1 && root.deploymentMode) {
                viewModel.selectUnitType("scout_drone")
            } else if (event.key === Qt.Key_2 && root.deploymentMode) {
                viewModel.selectUnitType("strike_drone")
            } else if (event.key === Qt.Key_3 && root.deploymentMode) {
                viewModel.selectUnitType("ground_vehicle")
            } else if (event.key === Qt.Key_4 && root.deploymentMode) {
                viewModel.selectUnitType("missile_vehicle")
            } else if (event.key === Qt.Key_5 && root.deploymentMode) {
                viewModel.selectUnitType("command_node")
            } else if (event.key === Qt.Key_6 && root.deploymentMode) {
                viewModel.selectObstacleType("mountain")
            } else if (event.key === Qt.Key_7 && root.deploymentMode) {
                viewModel.selectObstacleType("building")
            } else if (event.key === Qt.Key_8 && root.deploymentMode) {
                viewModel.selectObstacleType("restricted")
            } else {
                return
            }
            event.accepted = true
        }
    }
}
