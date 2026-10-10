pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var stats
    property string sceneName: "当前场景"
    signal returnToMap()
    signal restart()
    signal editDeployment()
    signal exportResult()
    modal: true
    title: "本局结算"
    closePolicy: Popup.CloseOnEscape
    padding: 18
    palette.windowText: "#eaf4ff"
    palette.window: "#101d2e"
    palette.base: "#14243a"
    palette.button: "#182a42"
    palette.buttonText: "#eaf4ff"
    background: Rectangle { radius: 14; color: "#101d2e"; border.color: "#36516e" }
    header: Text {
        text: dialog.title
        color: "#eaf4ff"
        padding: 18
        bottomPadding: 8
        font.family: "Microsoft YaHei"
        font.pixelSize: 16
        font.bold: true
    }

    readonly property color winnerColor: stats.winner === "red" ? "#ff5d73"
        : stats.winner === "blue" ? "#4ca6ff" : "#ffd166"

    contentItem: ColumnLayout {
        spacing: 6
        Text {
            Layout.fillWidth: true
            text: dialog.stats.winner === "red" ? "红方获胜"
                : dialog.stats.winner === "blue" ? "蓝方获胜"
                : dialog.stats.winner === "draw" ? "双方平局" : "本局结束"
            color: dialog.winnerColor
            font.family: "Microsoft YaHei"
            font.pixelSize: 28
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            Layout.fillWidth: true
            text: dialog.sceneName + "  ·  运行 " + dialog.stats.time_step + " 时间步"
            color: "#9fb4c9"
            font.family: "Microsoft YaHei"
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            objectName: "finishReasonLabel"
            Layout.fillWidth: true
            visible: !!dialog.stats.finish_reason
            text: dialog.stats.finish_reason === "step_limit" ? "达到时间步上限，双方平局"
                : dialog.stats.finish_reason === "base_destroyed" ? "基地被摧毁"
                : dialog.stats.finish_reason === "elimination" ? "一方单位全灭" : ""
            color: dialog.winnerColor
            font.family: "Microsoft YaHei"
            font.pixelSize: 13
            font.bold: true
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: "结算项目"; color: "#9fb4c9"; font.family: "Microsoft YaHei"; font.pixelSize: 12 }
            Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: "红方"; color: "#ff5d73"; font.family: "Microsoft YaHei"; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
            Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: "蓝方"; color: "#4ca6ff"; font.family: "Microsoft YaHei"; font.pixelSize: 13; horizontalAlignment: Text.AlignHCenter }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#294461" }
        Repeater {
            model: [
                { label: "剩余单位", red: dialog.stats.red_remaining, blue: dialog.stats.blue_remaining },
                { label: "击毁目标", red: dialog.stats.red_kills, blue: dialog.stats.blue_kills },
                { label: "攻击次数", red: dialog.stats.red_attacks, blue: dialog.stats.blue_attacks },
                { label: "命中次数", red: dialog.stats.red_hits, blue: dialog.stats.blue_hits },
                { label: "累计伤害", red: dialog.stats.red_damage, blue: dialog.stats.blue_damage },
                { label: "剩余战斗力", red: dialog.stats.red_strength, blue: dialog.stats.blue_strength },
                { label: "基地耐久", red: dialog.stats.red_base_hp, blue: dialog.stats.blue_base_hp }
            ]
            delegate: RowLayout {
                id: resultRow
                required property var modelData
                Layout.fillWidth: true
                spacing: 8
                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: resultRow.modelData.label; color: "#dce8f6"; font.family: "Microsoft YaHei"; font.pixelSize: 12 }
                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: String(resultRow.modelData.red ?? 0); color: "#ff8fa0"; font.family: "Consolas"; font.pixelSize: 17; horizontalAlignment: Text.AlignHCenter }
                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: String(resultRow.modelData.blue ?? 0); color: "#8fc7ff"; font.family: "Consolas"; font.pixelSize: 17; horizontalAlignment: Text.AlignHCenter }
            }
        }
        Item { Layout.fillHeight: true }
        Text {
            Layout.fillWidth: true
            text: "返回地图可查看最终态势；再来一局沿用本局部署。"
            color: "#8da2ba"
            font.family: "Microsoft YaHei"
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }
    footer: Item {
        implicitHeight: 100
        GridLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            anchors.bottomMargin: 18
            columns: 2
            columnSpacing: 8
            rowSpacing: 8
            ActionButton { Layout.fillWidth: true; text: "返回地图"; onClicked: dialog.returnToMap() }
            ActionButton { Layout.fillWidth: true; text: "再来一局"; highlighted: true; onClicked: dialog.restart() }
            ActionButton { Layout.fillWidth: true; text: "调整部署"; onClicked: dialog.editDeployment() }
            ActionButton { Layout.fillWidth: true; text: "导出战报…"; tone: "#ffca64"; onClicked: dialog.exportResult() }
        }
    }
}
