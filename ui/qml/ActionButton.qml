import QtQuick
import QtQuick.Controls

Button {
    id: control
    property color tone: "#54e1c2"
    implicitHeight: 38
    implicitWidth: 120
    font.family: "Microsoft YaHei"
    font.pixelSize: 13
    opacity: enabled ? 1 : 0.45
    contentItem: Text {
        text: control.text
        color: control.highlighted ? control.tone : "#dce8f6"
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: 8
        color: control.down ? "#294562" : control.hovered ? "#203653" : "#182a42"
        border.width: control.highlighted || control.activeFocus ? 2 : 1
        border.color: control.highlighted || control.activeFocus ? control.tone : "#2b4260"
    }
}
