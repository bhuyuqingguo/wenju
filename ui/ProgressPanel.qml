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
        visible: root.percent < 0 && root.files.length === 0
        text: "转换开始后，每一份文件都会显示百分比。"
        color: root.muted
        font.pixelSize: root.fontPx
        Layout.fillWidth: true
        wrapMode: Text.Wrap
    }
    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: Math.round(108 * Math.max(1, root.fontPx / 13))
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
                spacing: 3
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
                RowLayout {
                    visible: root.fontPx >= 17
                    width: parent.width
                    spacing: 8
                    Text { text: "原文件"; color: root.muted; font.pixelSize: Math.max(11, root.fontPx - 1) }
                    Text {
                        id: sourceWide
                        text: modelData.source || ""
                        Layout.fillWidth: true
                        Layout.preferredWidth: 0
                        color: root.ink
                        font.pixelSize: Math.max(11, root.fontPx - 1)
                        elide: Text.ElideMiddle
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            ToolTip.visible: containsMouse && parent.text !== ""
                            ToolTip.text: parent.text
                            ToolTip.delay: 300
                        }
                    }
                    Text { text: "目标文件"; color: root.muted; font.pixelSize: Math.max(11, root.fontPx - 1) }
                    Text {
                        id: outputWide
                        text: modelData.output ? modelData.output : "尚未生成"
                        Layout.fillWidth: true
                        Layout.preferredWidth: 0
                        color: modelData.output ? root.ink : root.muted
                        font.pixelSize: Math.max(11, root.fontPx - 1)
                        elide: Text.ElideMiddle
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            ToolTip.visible: containsMouse && parent.text !== ""
                            ToolTip.text: parent.text
                            ToolTip.delay: 300
                        }
                    }
                }
                RowLayout {
                    visible: root.fontPx < 17
                    width: parent.width
                    spacing: 8
                    Text {
                        text: "原文件"
                        color: root.muted
                        font.pixelSize: Math.max(11, root.fontPx - 1)
                        Layout.preferredWidth: Math.max(11, root.fontPx - 1) * 4 + 12
                        Layout.minimumWidth: Math.max(11, root.fontPx - 1) * 4 + 12
                    }
                    Item {
                        Layout.fillWidth: true
                        implicitHeight: sourceText.implicitHeight
                        Text {
                            id: sourceText
                            width: parent.width
                            text: modelData.source || ""
                            color: root.ink
                            font.pixelSize: Math.max(11, root.fontPx - 1)
                            elide: Text.ElideMiddle
                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                ToolTip.visible: containsMouse && parent.text !== ""
                                ToolTip.text: parent.text
                                ToolTip.delay: 300
                            }
                        }
                    }
                }
                RowLayout {
                    visible: root.fontPx < 17
                    width: parent.width
                    spacing: 8
                    Text {
                        text: "目标文件"
                        color: root.muted
                        font.pixelSize: Math.max(11, root.fontPx - 1)
                        Layout.preferredWidth: Math.max(11, root.fontPx - 1) * 4 + 12
                        Layout.minimumWidth: Math.max(11, root.fontPx - 1) * 4 + 12
                    }
                    Item {
                        Layout.fillWidth: true
                        implicitHeight: outputText.implicitHeight
                        Text {
                            id: outputText
                            width: parent.width
                            text: modelData.output ? modelData.output : "尚未生成"
                            color: modelData.output ? root.ink : root.muted
                            font.pixelSize: Math.max(11, root.fontPx - 1)
                            elide: Text.ElideMiddle
                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                ToolTip.visible: containsMouse && parent.text !== ""
                                ToolTip.text: parent.text
                                ToolTip.delay: 300
                            }
                        }
                    }
                }
                Text {
                    id: statusText
                    width: parent.width
                    visible: (modelData.message || "") !== "" && modelData.state !== "成功"
                    text: modelData.message || ""
                    color: modelData.state === "失败" ? root.badColor : root.muted
                    font.pixelSize: Math.max(11, root.fontPx - 1)
                    elide: Text.ElideRight
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        ToolTip.visible: containsMouse && parent.text !== ""
                        ToolTip.text: parent.text
                        ToolTip.delay: 300
                    }
                }
            }
        }
    }
}
