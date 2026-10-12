pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: detail
    property var unit: ({})
    readonly property bool hasUnit: !!(unit && unit.id)
    readonly property color teamColor: unit && unit.team === "red" ? Theme.red : Theme.blue
    signal clearSelection()
    implicitHeight: hasUnit ? detailsContent.implicitHeight + 24 : 74
    radius: Theme.radiusSmall
    color: Theme.field
    border.color: Theme.divider

    Text {
        visible: !detail.hasUnit
        anchors.fill: parent
        anchors.margins: 12
        text: "单位详情\n点击战场中的单位查看属性与状态"
        color: Theme.muted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
        lineHeight: 1.4
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.Wrap
    }

    ColumnLayout {
        id: detailsContent
        anchors.fill: parent
        anchors.margins: 12
        spacing: 6
        visible: detail.hasUnit
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: detail.unit.name || "单位详情"
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 14
                font.bold: true
                elide: Text.ElideRight
            }
            ToolButton {
                text: "×"
                implicitWidth: 28
                implicitHeight: 28
                hoverEnabled: true
                palette.buttonText: Theme.muted
                Accessible.name: "取消选中单位"
                background: Rectangle {
                    radius: Theme.radiusSmall
                    color: parent.hovered ? Theme.surfaceRaised : "transparent"
                    border.color: parent.activeFocus ? Theme.accent : "transparent"
                }
                onClicked: detail.clearSelection()
            }
        }
        Text {
            Layout.fillWidth: true
            text: (detail.unit.team === "red" ? "红方" : "蓝方") + " · "
                + (detail.unit.unit_type_label || detail.unit.unit_type || "") + " · "
                + (detail.unit.domain_label || detail.unit.domain || "")
            color: detail.teamColor
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            elide: Text.ElideRight
        }
        Text {
            text: "生命  " + (detail.unit.hp || 0) + " / " + (detail.unit.max_hp || 0)
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 5
            radius: 2
            color: Theme.divider
            Rectangle {
                width: parent.width * Math.max(0, (detail.unit.hp || 0) / Math.max(1, detail.unit.max_hp || 1))
                height: parent.height
                radius: 2
                color: detail.unit.destroyed ? Theme.red : Theme.accent
            }
        }
        Text {
            text: "弹药  " + (detail.unit.ammo || 0) + " / " + (detail.unit.max_ammo || 0)
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 10
            rowSpacing: 5
            Text { text: "移动速度"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
            Text { text: Number(detail.unit.speed || 0).toFixed(1); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
            Text { text: "侦察 / 攻击范围"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
            Text { text: (detail.unit.detect_range || 0) + " / " + (detail.unit.attack_range || 0); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
            Text { text: "当前位置"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
            Text { text: Math.round(detail.unit.x || 0) + ", " + Math.round(detail.unit.y || 0); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
        }
        Text {
            Layout.fillWidth: true
            text: "状态  " + (detail.unit.status_label || detail.unit.status || "")
                + " · " + (detail.unit.engagement_label || detail.unit.engagement || "")
            color: detail.unit.destroyed ? Theme.red : Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
        }
        Text {
            objectName: "unitDestructionTime"
            Layout.fillWidth: true
            visible: !!detail.unit.destroyed && detail.unit.destroyed_step !== undefined && detail.unit.destroyed_step !== null
            text: "摧毁时间  第 " + detail.unit.destroyed_step + " 步 · "
                + Number(detail.unit.destroyed_elapsed_seconds || 0).toFixed(2) + " 秒"
                + (detail.unit.killer_id ? "\n击毁方  " + detail.unit.killer_id : "")
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
        }
        Item { Layout.fillHeight: true }
    }
}
