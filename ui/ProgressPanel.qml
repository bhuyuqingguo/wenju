import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var files: []
    property int overall: 0
    property string heading: "总进度"
    property color ink: "#22344a"
    property color muted: "#7b8899"
    property color track: "#e6ebf1"
    property color fill: "#245a83"
    property color okColor: "#35806c"
    property color badColor: "#a33b3b"
    property int fontPx: 13
    property string label: ""
    property int percent: -1
    property bool idleHint: true

    function barColor(state) {
        if (state === "失败")
            return badColor
        if (state === "成功")
            return okColor
        return fill
    }

    ColumnLayout {
        visible: root.percent >= 0
        Layout.fillWidth: true
        spacing: 2
        Text {
            visible: root.label.length > 0
            text: root.label
            color: root.ink
            font.pixelSize: root.fontPx
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 8
                radius: 4
                color: root.track
                Rectangle {
                    width: Math.max(0, Math.min(parent.width, parent.width * Math.max(0, Math.min(100, root.percent)) / 100))
                    height: parent.height
                    radius: 4
                    color: root.fill
                }
            }
            Text { text: root.percent + "%"; color: root.muted; font.pixelSize: Math.max(11, root.fontPx - 1) }
        }
    }
    RowLayout {
        visible: root.percent < 0
        Layout.fillWidth: true
        Text { text: root.heading; color: root.ink; font.pixelSize: root.fontPx; font.bold: true }
        Item { Layout.fillWidth: true }
        Text { text: root.overall + "%"; color: root.ink; font.pixelSize: root.fontPx; font.bold: true }
    }
    Rectangle {
        visible: root.percent < 0
        Layout.fillWidth: true
        Layout.preferredHeight: 10
        radius: 5
        color: root.track
        Rectangle {
            width: Math.max(0, Math.min(parent.width, parent.width * root.overall / 100))
            height: parent.height
            radius: 5
            color: root.fill
        }
    }
    Text {
        visible: root.idleHint && root.percent < 0 && root.files.length === 0
        text: "转换开始后，每一份文件都会显示百分比。"
        color: root.muted
        font.pixelSize: root.fontPx
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 48
        visible: root.percent < 0 && root.files.length > 0
        ListView {
            id: list
            anchors.fill: parent
            clip: true
            spacing: 8
            model: root.files
            delegate: Column {
                required property var modelData
                width: list.width
                spacing: 4
                RowLayout {
                    width: parent.width
                    Text {
                        text: modelData.name
                        color: root.ink
                        font.pixelSize: root.fontPx
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                    }
                    Text { text: (modelData.percent || 0) + "%"; color: root.ink; font.pixelSize: root.fontPx; font.bold: true }
                    Text {
                        text: modelData.state || ""
                        color: modelData.state === "失败" ? root.badColor : (modelData.state === "成功" ? root.okColor : root.muted)
                        font.pixelSize: Math.max(11, root.fontPx - 1)
                    }
                }
                Rectangle {
                    width: parent.width
                    height: 8
                    radius: 4
                    color: root.track
                    Rectangle {
                        width: Math.max(0, Math.min(parent.width, parent.width * (modelData.percent || 0) / 100))
                        height: parent.height
                        radius: 4
                        color: root.barColor(modelData.state)
                    }
                }
                Text {
                    width: parent.width
                    visible: (modelData.target || modelData.docx || modelData.output || "") !== ""
                    text: "目标文件 " + (modelData.target || modelData.docx || modelData.output || "")
                    color: root.ink
                    font.pixelSize: Math.max(11, root.fontPx - 1)
                    elide: Text.ElideMiddle
                }
                Text {
                    width: parent.width
                    visible: (modelData.message || "") !== ""
                    text: modelData.message || ""
                    color: modelData.state === "失败" ? root.badColor : root.muted
                    font.pixelSize: Math.max(11, root.fontPx - 1)
                    elide: Text.ElideRight
                }
            }
        }
    }
}
