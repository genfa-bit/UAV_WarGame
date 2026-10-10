pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: terrain
    property real worldWidth: 800
    property real worldHeight: 600
    property string mapStyle: "tactical"
    property var visual: ({})
    property bool showGrid: true
    property bool showLandmarks: true
    readonly property url imageSource: visual && visual.background
        ? "../assets/maps/" + visual.background : ""
    readonly property real sx: width / Math.max(1, worldWidth)
    readonly property real sy: height / Math.max(1, worldHeight)

    Rectangle { anchors.fill: parent; color: "#0a1828" }
    Image {
        id: terrainImage
        objectName: "terrainImage"
        readonly property bool imageReady: status === Image.Ready
        anchors.fill: parent
        source: terrain.imageSource
        fillMode: Image.Stretch
        smooth: true
        mipmap: true
        opacity: 0.9
    }
    Rectangle {
        anchors.fill: parent
        color: "#102331"
        opacity: terrain.imageSource.toString() ? 0.2 : 0
    }

    Canvas {
        id: terrainCanvas
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            const sx = terrain.sx
            const sy = terrain.sy
            if (terrain.showGrid) {
                const step = terrain.mapStyle === "tactical" ? 40 : 100
                ctx.strokeStyle = terrain.mapStyle === "tactical" ? "#17314a" : "rgba(228,242,225,0.18)"
                ctx.lineWidth = 1
                ctx.fillStyle = "rgba(227,243,233,0.64)"
                ctx.font = "10px Microsoft YaHei"
                for (let x = 0; x <= terrain.worldWidth; x += step) {
                    ctx.beginPath()
                    ctx.moveTo(x * sx, 0)
                    ctx.lineTo(x * sx, height)
                    ctx.stroke()
                    if (x > 0 && x % 100 === 0 && x < terrain.worldWidth)
                        ctx.fillText(String(x), x * sx + 4, 13)
                }
                for (let y = 0; y <= terrain.worldHeight; y += step) {
                    ctx.beginPath()
                    ctx.moveTo(0, y * sy)
                    ctx.lineTo(width, y * sy)
                    ctx.stroke()
                    if (y > 0 && y % 100 === 0 && y < terrain.worldHeight)
                        ctx.fillText(String(y), 4, y * sy - 4)
                }
            }
            const routes = terrain.visual && terrain.visual.routes ? terrain.visual.routes : []
            for (let r = 0; r < routes.length; ++r) {
                const route = routes[r]
                const points = route.points || route
                if (!points || points.length < 2) continue
                ctx.beginPath()
                ctx.strokeStyle = route.color || "rgba(250,230,164,0.58)"
                ctx.lineWidth = 2
                ctx.setLineDash([7, 5])
                for (let p = 0; p < points.length; ++p) {
                    const point = points[p]
                    const px = (point.x !== undefined ? point.x : point[0]) * sx
                    const py = (point.y !== undefined ? point.y : point[1]) * sy
                    if (p === 0) ctx.moveTo(px, py)
                    else ctx.lineTo(px, py)
                }
                ctx.stroke()
                ctx.setLineDash([])
            }
        }
    }

    Repeater {
        model: terrain.showLandmarks && terrain.visual ? (terrain.visual.landmarks || []) : []
        delegate: Item {
            id: landmark
            required property var modelData
            x: modelData.x * terrain.sx
            y: modelData.y * terrain.sy
            readonly property string symbol: modelData.kind === "lake" ? "≈"
                : modelData.kind === "bridge" ? "═" : modelData.kind === "airfield" ? "✈"
                : modelData.kind === "farmland" ? "▦" : "◇"
            readonly property color tint: modelData.kind === "lake" ? "#b1e0ee"
                : modelData.kind === "farmland" ? "#e2efb5" : "#f4ebcc"
            Rectangle {
                x: -8
                y: -8
                width: 16
                height: 16
                radius: 4
                color: "#b80b1924"
                border.color: landmark.tint
                Text { anchors.centerIn: parent; text: landmark.symbol; color: landmark.tint; font.pixelSize: 12 }
            }
            Rectangle {
                x: 12
                y: -11
                width: placeName.implicitWidth + 12
                height: 23
                radius: 4
                color: "#b80b1924"
                Text {
                    id: placeName
                    anchors.centerIn: parent
                    text: landmark.modelData.name
                    color: landmark.tint
                    font.family: "Microsoft YaHei"
                    font.pixelSize: 11
                }
            }
        }
    }

    onVisualChanged: terrainCanvas.requestPaint()
    onShowGridChanged: terrainCanvas.requestPaint()
    onMapStyleChanged: terrainCanvas.requestPaint()
    onWidthChanged: terrainCanvas.requestPaint()
    onHeightChanged: terrainCanvas.requestPaint()
}
