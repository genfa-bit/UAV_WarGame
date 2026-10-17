pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Dialog {
    id: dialog
    required property var stats
    property string sceneName: "当前场景"
    property var destroyedUnits: []
    signal returnToMap()
    signal restart()
    signal editDeployment()
    signal exportResult()
    signal viewRecords()
    signal replayRun()
    modal: true
    title: "本局结算"
    closePolicy: Popup.CloseOnEscape
    padding: 16
    palette.windowText: Theme.text
    palette.window: Theme.surface
    palette.base: Theme.field
    palette.button: Theme.surfaceRaised
    palette.buttonText: Theme.text
    background: Rectangle { radius: Theme.radius; color: Theme.surface; border.color: Theme.border }
    header: Text {
        text: dialog.title
        color: Theme.text
        padding: 16
        bottomPadding: 10
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontTitle
        font.bold: true
    }

    readonly property color winnerColor: stats.winner === "red" ? Theme.red
        : stats.winner === "blue" ? Theme.blue : Theme.warning

    contentItem: ScrollView {
        id: resultScroll
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
        width: resultScroll.availableWidth
        spacing: 8
        Text {
            Layout.fillWidth: true
            text: dialog.stats.winner === "red" ? "红方获胜"
                : dialog.stats.winner === "blue" ? "蓝方获胜"
                : dialog.stats.winner === "draw" ? "双方平局" : "本局结束"
            color: dialog.winnerColor
            font.family: Theme.fontFamily
            font.pixelSize: 22
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            Layout.fillWidth: true
            text: dialog.sceneName + "  ·  运行 " + dialog.stats.time_step + " 时间步 · "
                + Number(dialog.stats.elapsed_seconds || 0).toFixed(2) + " 秒"
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            objectName: "finishReasonLabel"
            Layout.fillWidth: true
            visible: !!dialog.stats.finish_reason
            text: dialog.stats.finish_reason === "step_limit" ? "达到时间步上限，双方平局"
                : dialog.stats.finish_reason === "base_destroyed" ? "基地被摧毁"
                : dialog.stats.finish_reason === "elimination" ? "一方单位全灭" : ""
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 6
            spacing: 8
            Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: "结算项目"; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
            Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: "红方"; color: Theme.red; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; horizontalAlignment: Text.AlignHCenter }
            Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: "蓝方"; color: Theme.blue; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; horizontalAlignment: Text.AlignHCenter }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.divider }
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
                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: resultRow.modelData.label; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize }
                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: String(resultRow.modelData.red ?? 0); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter }
                Text { Layout.fillWidth: true; Layout.preferredWidth: 1; text: String(resultRow.modelData.blue ?? 0); color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter }
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.topMargin: 4; implicitHeight: 1; color: Theme.divider }
        Text {
            Layout.fillWidth: true
            text: "摧毁时间（单位 / 基地） · " + dialog.destroyedUnits.length + " 条"
            color: Theme.text
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            font.bold: true
        }
        Text {
            Layout.fillWidth: true
            visible: dialog.destroyedUnits.length === 0
            text: "本局暂无摧毁记录。"
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
        }
        Repeater {
            model: dialog.destroyedUnits
            delegate: Text {
                required property var modelData
                Layout.fillWidth: true
                text: (modelData.name || modelData.unit_id) + " · 第 " + modelData.step + " 步 · "
                    + Number(modelData.elapsed_seconds || 0).toFixed(2) + " 秒"
                    + ((modelData.killer_name || modelData.killer_id) ? " · 击毁方 " + (modelData.killer_name || modelData.killer_id) : "")
                color: Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                wrapMode: Text.Wrap
            }
        }
        Text {
            Layout.fillWidth: true
            text: "再来一局将沿用本局部署。"
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSize
            wrapMode: Text.Wrap
        }
        }
    }
    footer: Item {
        implicitHeight: 156
        GridLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.bottomMargin: 16
            columns: 2
            columnSpacing: 8
            rowSpacing: 6
            ActionButton { Layout.fillWidth: true; text: "返回地图"; onClicked: dialog.returnToMap() }
            ActionButton { Layout.fillWidth: true; text: "再来一局"; highlighted: true; onClicked: dialog.restart() }
            ActionButton { Layout.fillWidth: true; text: "调整部署"; onClicked: dialog.editDeployment() }
            ActionButton { Layout.fillWidth: true; text: "导出战报…"; onClicked: dialog.exportResult() }
            ActionButton { objectName: "resultReplayButton"; Layout.fillWidth: true; Layout.columnSpan: 2; text: "回放本局"; onClicked: dialog.replayRun() }
            ActionButton { objectName: "resultRecordsButton"; Layout.fillWidth: true; Layout.columnSpan: 2; text: "运行记录与摧毁时间"; flat: true; onClicked: dialog.viewRecords() }
        }
    }
}
