pragma ComponentBehavior: Bound

import QtQuick
import "Theme.js" as Theme

Rectangle {
    id: overview
    property real worldWidth: 800
    property real worldHeight: 600
    property var visual: ({})
    property var units: []
    property real visibleX: 0
    property real visibleY: 0
    property real visibleWidth: worldWidth
    property real visibleHeight: worldHeight
    signal centerRequested(real worldX, real worldY)
    radius: Theme.radiusSmall
    color: Theme.surface
    border.color: Theme.border
    clip: true

    Text {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 5
        text: "总览 · 点击定位"
        color: Theme.muted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSmall
    }
    Item {
        id: overviewMap
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.top: parent.top
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        anchors.bottomMargin: 4
        anchors.topMargin: 24
        clip: true
        readonly property real sx: width / Math.max(1, overview.worldWidth)
        readonly property real sy: height / Math.max(1, overview.worldHeight)
        Rectangle { anchors.fill: parent; color: Theme.field }
        Image {
            anchors.fill: parent
            source: overview.visual && overview.visual.background
                ? "../assets/maps/" + overview.visual.background : ""
            fillMode: Image.Stretch
            smooth: true
            opacity: 0.76
        }
        Repeater {
            model: overview.units
            delegate: Rectangle {
                required property var modelData
                x: modelData.x * overviewMap.sx - 2.5
                y: modelData.y * overviewMap.sy - 2.5
                width: 5
                height: 5
                radius: 2.5
                color: modelData.team === "red" ? Theme.red : Theme.blue
                opacity: modelData.destroyed ? 0.25 : 1
            }
        }
        Rectangle {
            x: overview.visibleX * overviewMap.sx
            y: overview.visibleY * overviewMap.sy
            width: overview.visibleWidth * overviewMap.sx
            height: overview.visibleHeight * overviewMap.sy
            color: "#1682b7af"
            border.width: 1
            border.color: Theme.accent
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onPressed: function(mouse) {
                overview.centerRequested(mouse.x / overviewMap.sx, mouse.y / overviewMap.sy)
            }
            onPositionChanged: function(mouse) {
                if (pressed) overview.centerRequested(mouse.x / overviewMap.sx, mouse.y / overviewMap.sy)
            }
        }
    }
}
