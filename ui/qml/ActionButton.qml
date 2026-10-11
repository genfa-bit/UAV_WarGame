import QtQuick
import QtQuick.Controls
import "Theme.js" as Theme

Button {
    id: control
    property color tone: Theme.accent
    property bool selected: false
    implicitHeight: Theme.controlHeight
    implicitWidth: 112
    leftPadding: 10
    rightPadding: 10
    topPadding: 4
    bottomPadding: 4
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSize
    font.bold: highlighted
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    opacity: enabled ? 1 : 0.4
    Accessible.name: text
    Keys.onReturnPressed: function(event) { if (enabled) clicked(); event.accepted = true }
    Keys.onEnterPressed: function(event) { if (enabled) clicked(); event.accepted = true }
    contentItem: Text {
        text: control.text
        color: control.highlighted ? Theme.onAccent
            : control.selected ? control.tone : Theme.text
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.highlighted
            ? (control.down ? Theme.accentPressed : control.hovered ? Theme.accentHover : control.tone)
            : control.down ? Theme.selection
            : control.selected ? Theme.selection
            : control.hovered ? Theme.surfaceRaised
            : control.flat ? "transparent" : Theme.field
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? Theme.accentHover
            : control.highlighted ? "transparent"
            : control.selected ? Qt.rgba(control.tone.r, control.tone.g, control.tone.b, 0.55)
            : control.flat && !control.hovered ? "transparent" : Theme.border
    }
}
