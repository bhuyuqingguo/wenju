import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string label: ""
    property int percent: 0
    spacing: 2
    Label {
        visible: root.label.length > 0
        text: root.label
        Layout.fillWidth: true
        elide: Text.ElideRight
        color: appearance.palette["#22344a"]
    }
    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        ProgressBar {
            Layout.fillWidth: true
            from: 0
            to: 100
            value: Math.max(0, Math.min(100, root.percent))
        }
        Label {
            text: root.percent + "%"
            color: appearance.palette["#7b8899"]
            font.pixelSize: Math.round(11 * appearance.scale)
        }
    }
}
