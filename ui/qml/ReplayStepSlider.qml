import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

// 回放进度条：按帧拖动定位。
Item {
    id: root
    property int cursor: 0
    property int frameCount: 0
    signal seek(int index)

    implicitHeight: 40

    // cursor 与 frameCount 是两条独立的绑定，求值顺序不保证。先把 to 撑开再写
    // value，否则先到的大游标会被旧区间夹回 0，滑块就再也跟不上定时器。
    function syncToCursor() {
        control.to = Math.max(0, root.frameCount - 1)
        control.value = root.cursor
    }

    Text {
        id: caption
        objectName: "replaySliderLabel"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        text: "第 " + root.cursor + " / " + Math.max(0, root.frameCount - 1) + " 步"
        color: Theme.muted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSize
        elide: Text.ElideRight
    }

    Slider {
        id: control
        objectName: "replaySlider"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: caption.bottom
        anchors.topMargin: 2
        from: 0
        to: 0
        value: 0
        stepSize: 1
        snapMode: Slider.SnapAlways
        enabled: root.frameCount > 1
        // 用 onMoved 而不是 onValueChanged：定时器推动游标时不该再回灌控制器。
        onMoved: root.seek(value)
        Accessible.name: "回放进度"
        // 不用 `value: root.cursor` 的声明式绑定——拖动会写 value 从而断开绑定，
        // 之后定时器推游标，滑块就不再跟着走了，所以改为显式同步。
        Connections {
            target: root
            function onCursorChanged() { root.syncToCursor() }
            function onFrameCountChanged() { root.syncToCursor() }
        }
        Component.onCompleted: root.syncToCursor()
    }
}
