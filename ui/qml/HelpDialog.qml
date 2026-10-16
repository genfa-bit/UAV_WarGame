pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "Theme.js" as Theme

Dialog {
    id: dialog
    modal: true
    title: "使用帮助"
    padding: 16
    closePolicy: Popup.CloseOnEscape
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

    contentItem: ScrollView {
        id: helpScroll
        clip: true
        contentWidth: availableWidth
        Column {
            width: helpScroll.availableWidth
            spacing: 16
            Text {
                width: parent.width
                text: "选择场景 → 编辑部署 → 运行观察 → 查看记录"
                color: Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                wrapMode: Text.Wrap
            }
            Repeater {
                model: [
                    { title: "1  选择场景", body: "标准对抗适合快速演示，障碍环境可观察绕障。山区河谷与河谷城镇提供地形地图；自定义场景可从空白部署，或载入已保存的 JSON 地图。" },
                    { title: "2  编辑部署", body: "选择阵营与单位类型，左键放置；选择障碍后左键拖拽绘制。选中障碍可调整大小或按 Delete 删除，右键可删除单位或障碍。部署完成后可保存地图并开始仿真。" },
                    { title: "3  运行观察", body: "滚轮缩放，中键拖动，放大后直接按住左键拖动也能平移，小地图点击或拖动定位。若按住处正在进行部署编辑（拉框创建、拖动对象），需先按住不动再拖动才会改为平移。地图工具可适应地图、切换图层；底部可暂停、单步与变速。部署或暂停时可在“时间设置”修改单步时长与最大步数；点击单位查看属性、状态和摧毁时刻。" },
                    { title: "4  记录与结算", body: "“运行记录”分类查看侦察、共享、摧毁、战术与结果，含步数及累计时间，并可导出完整 JSON。暂停、结束或重新部署时自动保存。结束后可导出战报，或沿用部署再来一局；达到最大步数仍未分胜负则为平局。" },
                    { title: "5  战局回放", body: "每局运行记录都带有逐步的单位与基地状态，可完整回放：结算对话框点“回放本局”，运行记录的历史行点“回放”，或在底部工具栏用“载入回放…”选择任意记录文件（部署阶段也可用，刚启动就能看旧记录）。回放中可拖动时间轴定位、播放/暂停、单步前后、变速，运行记录面板与战场统计会同步到那一刻。回放不会新建或覆盖任何记录文件；按 Esc 或“退出回放”回到进入回放前的部署，从部署阶段进入时回到当时正在编辑的布局。旧版本（schema 2）记录不含逐帧数据，只能查看不能回放。" }
                ]
                delegate: Column {
                    id: helpStep
                    required property var modelData
                    width: helpScroll.availableWidth
                    spacing: 6
                    Text { width: parent.width; text: helpStep.modelData.title; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.bold: true }
                    Text { width: parent.width; text: helpStep.modelData.body; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; wrapMode: Text.Wrap; lineHeight: 1.45 }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.divider }
            Text { text: "单位图例"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.bold: true }
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
                        Image { width: 32; height: 32; anchors.horizontalCenter: parent.horizontalCenter; source: "../assets/unit_icons/" + legend.modelData.type + ".png"; fillMode: Image.PreserveAspectFit }
                        Text { width: parent.width; text: legend.modelData.label; color: Theme.muted; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSize; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap }
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.divider }
            Text { text: "快捷键"; color: Theme.text; font.family: Theme.fontFamily; font.pixelSize: 13; font.bold: true }
            Text {
                width: parent.width
                text: "Enter 开始 · Space 暂停 / 继续 · S 单步 · F 变速\n1–5 选择单位 · 6–8 选择障碍 · T 切换阵营\nBackspace 撤销单位放置 · Delete 删除选中障碍\nCtrl+S 保存 · Ctrl+Shift+S 另存为 · L 载入地图\nK 显示 / 隐藏残骸 · R 返回部署 · F1 打开帮助\n回放：Space 播放 / 暂停 · ← → 单步 · Esc 退出回放"
                color: Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSize
                wrapMode: Text.Wrap
                lineHeight: 1.5
            }
        }
    }
    footer: Item {
        implicitHeight: 48
        ActionButton {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            anchors.bottomMargin: 16
            text: "关闭帮助"
            onClicked: dialog.close()
        }
    }
}
