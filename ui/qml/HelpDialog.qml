pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    modal: true
    title: "使用帮助"
    padding: 18
    closePolicy: Popup.CloseOnEscape
    palette.windowText: "#eaf4ff"
    palette.window: "#101d2e"
    palette.base: "#14243a"
    palette.button: "#182a42"
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

    contentItem: ScrollView {
        id: helpScroll
        clip: true
        contentWidth: availableWidth
        Column {
            width: helpScroll.availableWidth
            spacing: 14
            Text {
                width: parent.width
                text: "从场景到结算，四步完成一次对战"
                color: "#54e1c2"
                font.family: "Microsoft YaHei"
                font.pixelSize: 17
                font.bold: true
                wrapMode: Text.Wrap
            }
            Repeater {
                model: [
                    { title: "1  选择场景", body: "标准对抗用于快速演示；障碍环境用于观察绕障。山区河谷和河谷城镇提供更丰富的地图，自定义场景可从空白部署，也可载入已保存的 JSON 地图。" },
                    { title: "2  部署编辑", body: "选择红方或蓝方和单位类型，左键在战场放置。选择障碍类型，左键拖拽绘制障碍；左键选中障碍后可调整大小或按 Delete 删除，右键可直接删除单位或障碍。先保存地图，再开始仿真。" },
                    { title: "3  运行观察", body: "滚轮缩放，中键拖动地图，右下小地图可点击或拖动定位；顶部可适应地图、切换网格、地标和全部范围。底部可暂停、单步和调整速度。点击单位查看实时属性，黄色虚线表示攻击范围；右侧可筛选日志。" },
                    { title: "4  查看结算", body: "战斗结束自动展示结果。本局达到时间步上限将结算平局。可返回最终地图、沿用部署再来一局、调整部署或导出战报。" }
                ]
                delegate: Column {
                    id: helpStep
                    required property var modelData
                    width: helpScroll.availableWidth
                    spacing: 4
                    Text { width: parent.width; text: helpStep.modelData.title; color: "#eaf4ff"; font.family: "Microsoft YaHei"; font.pixelSize: 13; font.bold: true }
                    Text { width: parent.width; text: helpStep.modelData.body; color: "#9fb4c9"; font.family: "Microsoft YaHei"; font.pixelSize: 12; wrapMode: Text.Wrap; lineHeight: 1.3 }
                }
            }
            Text { text: "单位图例"; color: "#eaf4ff"; font.family: "Microsoft YaHei"; font.pixelSize: 13; font.bold: true }
            Row {
                width: parent.width
                Repeater {
                    model: [
                        { type: "scout_drone", label: "侦察无人机" },
                        { type: "strike_drone", label: "打击无人机" },
                        { type: "ground_vehicle", label: "无人战车" },
                        { type: "missile_vehicle", label: "导弹发射车" },
                        { type: "command_node", label: "指挥节点" }
                    ]
                    delegate: Column {
                        id: legend
                        required property var modelData
                        width: helpScroll.availableWidth / 5
                        spacing: 4
                        Image { width: 38; height: 38; anchors.horizontalCenter: parent.horizontalCenter; source: "../assets/unit_icons/" + legend.modelData.type + ".png"; fillMode: Image.PreserveAspectFit }
                        Text { width: parent.width; text: legend.modelData.label; color: "#9fb4c9"; font.family: "Microsoft YaHei"; font.pixelSize: 10; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap }
                    }
                }
            }
            Text { text: "快捷键"; color: "#eaf4ff"; font.family: "Microsoft YaHei"; font.pixelSize: 13; font.bold: true }
            Text {
                width: parent.width
                text: "Enter 开始 · Space 暂停 / 继续 · S 单步 · F 变速\n1–5 选择单位 · 6–8 选择障碍 · T 切换阵营\nBackspace 撤销单位放置 · Delete 删除选中障碍\nCtrl+S 保存 · Ctrl+Shift+S 另存为 · L 载入地图\nK 显示 / 隐藏残骸 · R 返回部署 · F1 打开帮助"
                color: "#9fb4c9"
                font.family: "Microsoft YaHei"
                font.pixelSize: 12
                wrapMode: Text.Wrap
                lineHeight: 1.5
            }
        }
    }
    footer: Item {
        implicitHeight: 56
        ActionButton {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            anchors.bottomMargin: 18
            text: "开始使用"
            highlighted: true
            onClicked: dialog.close()
        }
    }
}
