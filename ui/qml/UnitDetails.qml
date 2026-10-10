pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: detail
    property var unit: ({})
    readonly property bool hasUnit: !!(unit && unit.id)
    readonly property color teamColor: unit && unit.team === "red" ? "#ff5d73" : "#4ca6ff"
    signal clearSelection()
    implicitHeight: hasUnit ? (unit.destroyed ? 330 : 286) : 74
    radius: 10
    color: "#14243a"
    border.color: hasUnit ? teamColor : "#263d5a"

    Text {
        visible: !detail.hasUnit
        anchors.fill: parent
        anchors.margins: 12
        text: "单位详情\n点击战场中的单位查看属性与状态"
        color: "#8da2ba"
        font.family: "Microsoft YaHei"
        font.pixelSize: 12
        lineHeight: 1.4
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.Wrap
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 6
        visible: detail.hasUnit
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: detail.unit.name || "单位详情"
                color: detail.teamColor
                font.family: "Microsoft YaHei"
                font.pixelSize: 15
                font.bold: true
                elide: Text.ElideRight
            }
            ToolButton {
                text: "×"
                implicitWidth: 28
                implicitHeight: 28
                palette.buttonText: "#9fb4c9"
                Accessible.name: "取消选中单位"
                onClicked: detail.clearSelection()
            }
        }
        Text {
            Layout.fillWidth: true
            text: (detail.unit.team === "red" ? "红方" : "蓝方") + " · "
                + (detail.unit.unit_type_label || detail.unit.unit_type || "") + " · "
                + (detail.unit.domain_label || detail.unit.domain || "")
            color: "#9fb4c9"
            font.family: "Microsoft YaHei"
            font.pixelSize: 11
            elide: Text.ElideRight
        }
        Text {
            text: "生命  " + (detail.unit.hp || 0) + " / " + (detail.unit.max_hp || 0)
            color: "#dce8f6"
            font.family: "Microsoft YaHei"
            font.pixelSize: 12
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 5
            radius: 2
            color: "#30405a"
            Rectangle {
                width: parent.width * Math.max(0, (detail.unit.hp || 0) / Math.max(1, detail.unit.max_hp || 1))
                height: parent.height
                radius: 2
                color: detail.unit.destroyed ? "#ff5d73" : "#54e1c2"
            }
        }
        Text {
            text: "弹药  " + (detail.unit.ammo || 0) + " / " + (detail.unit.max_ammo || 0)
            color: "#dce8f6"
            font.family: "Microsoft YaHei"
            font.pixelSize: 12
        }
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 10
            rowSpacing: 5
            Text { text: "移动速度"; color: "#8da2ba"; font.family: "Microsoft YaHei"; font.pixelSize: 11 }
            Text { text: Number(detail.unit.speed || 0).toFixed(1); color: "#dce8f6"; font.family: "Consolas"; font.pixelSize: 12 }
            Text { text: "侦察 / 攻击范围"; color: "#8da2ba"; font.family: "Microsoft YaHei"; font.pixelSize: 11 }
            Text { text: (detail.unit.detect_range || 0) + " / " + (detail.unit.attack_range || 0); color: "#dce8f6"; font.family: "Consolas"; font.pixelSize: 12 }
            Text { text: "当前位置"; color: "#8da2ba"; font.family: "Microsoft YaHei"; font.pixelSize: 11 }
            Text { text: Math.round(detail.unit.x || 0) + ", " + Math.round(detail.unit.y || 0); color: "#dce8f6"; font.family: "Consolas"; font.pixelSize: 12 }
        }
        Text {
            Layout.fillWidth: true
            text: "状态  " + (detail.unit.status_label || detail.unit.status || "")
                + " · " + (detail.unit.engagement || "")
            color: detail.unit.destroyed ? "#ff8fa0" : "#54e1c2"
            font.family: "Microsoft YaHei"
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Text {
            objectName: "unitDestructionTime"
            Layout.fillWidth: true
            visible: !!detail.unit.destroyed && detail.unit.destroyed_step !== undefined && detail.unit.destroyed_step !== null
            text: "摧毁时间  第 " + detail.unit.destroyed_step + " 步 · "
                + Number(detail.unit.destroyed_elapsed_seconds || 0).toFixed(2) + " 秒"
                + (detail.unit.killer_id ? "\n击毁方  " + detail.unit.killer_id : "")
            color: "#ff8fa0"
            font.family: "Microsoft YaHei"
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Item { Layout.fillHeight: true }
    }
}
