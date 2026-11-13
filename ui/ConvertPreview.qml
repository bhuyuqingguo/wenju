import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var blocks: []
    property color ink: appearance.palette["#22344a"]
    property color muted: appearance.palette["#7b8899"]
    property color line: appearance.palette["#dce3eb"]
    property color soft: appearance.palette["#eaf0f6"]
    property color surface: appearance.colors.surface

    Text {
        anchors.fill: parent
        visible: root.blocks.length === 0
        text: "拖入文件或读取剪贴板后，这里显示标题、段落、表格和图片。画不出的图片和图表会标明占位。"
        wrapMode: Text.Wrap
        color: root.muted
        font.pixelSize: Math.round(13 * appearance.scale)
        font.family: appearance.fontFamily
    }

    ListView {
        id: list
        objectName: "previewList"
        anchors.fill: parent
        visible: root.blocks.length > 0
        clip: true
        spacing: 10
        model: root.blocks
        boundsBehavior: Flickable.StopAtBounds
        onContentYChanged: {
            if (contentHeight > height + 4 && contentY > contentHeight - height - 120)
                bridge.morePreview()
        }
        ScrollBar.vertical: ScrollBar {
            policy: list.contentHeight > list.height + 4 ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded
        }
        delegate: Column {
            id: row
            required property var modelData
            width: list.width
            spacing: 4

            Text {
                width: row.width
                visible: row.modelData.kind === "heading" || row.modelData.kind === "paragraph"
                textFormat: Text.RichText
                text: "<span style=\"color:" + root.ink + "\">" + (row.modelData.html || "") + "</span>"
                wrapMode: Text.WordWrap
                color: root.ink
                font.family: appearance.fontFamily
                font.pixelSize: row.modelData.kind === "heading" ? Math.round(16 * appearance.scale) : Math.round(13 * appearance.scale)
                leftPadding: row.modelData.kind === "heading" ? Math.max(0, (row.modelData.level - 1) * 12) : 0
                horizontalAlignment: row.modelData.align === "center" ? Text.AlignHCenter : row.modelData.align === "right" ? Text.AlignRight : Text.AlignLeft
            }

            Column {
                width: row.width
                visible: row.modelData.kind === "table"
                spacing: 4
                Text {
                    width: parent.width
                    text: "表格"
                    color: root.ink
                    font.pixelSize: Math.round(12 * appearance.scale)
                    font.bold: true
                    font.family: appearance.fontFamily
                }
                Rectangle {
                    width: parent.width
                    height: tableCol.implicitHeight + 2
                    color: root.surface
                    border.color: root.line
                    radius: 4
                    clip: true
                    Column {
                        id: tableCol
                        width: parent.width
                        Repeater {
                            model: row.modelData.rows || []
                            delegate: Rectangle {
                                id: tableRow
                                required property var modelData
                                required property int index
                                property int cols: Math.max(1, modelData.length)
                                width: tableCol.width
                                height: grid.implicitHeight
                                color: index % 2 === 0 ? root.soft : root.surface
                                GridLayout {
                                    id: grid
                                    width: parent.width
                                    columns: tableRow.cols
                                    columnSpacing: 0
                                    rowSpacing: 0
                                    Repeater {
                                        model: tableRow.modelData
                                        delegate: Rectangle {
                                            required property var modelData
                                            required property int index
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: cellText.implicitHeight + 12
                                            border.color: root.line
                                            border.width: 1
                                            color: "transparent"
                                            Text {
                                                id: cellText
                                                x: 6
                                                y: 6
                                                width: Math.max(24, parent.width - 12)
                                                text: modelData || " "
                                                wrapMode: Text.Wrap
                                                color: root.ink
                                                font.pixelSize: Math.round(12 * appearance.scale)
                                                font.family: appearance.fontFamily
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                Text {
                    width: parent.width
                    visible: (row.modelData.note || "") !== ""
                    text: row.modelData.note || ""
                    wrapMode: Text.Wrap
                    color: root.muted
                    font.pixelSize: Math.round(11 * appearance.scale)
                    font.family: appearance.fontFamily
                }
            }

            Column {
                width: Math.min(row.width, 420)
                visible: row.modelData.kind === "image"
                spacing: 4
                Image {
                    id: shot
                    property real boxW: Math.min(row.width, 420)
                    property real natW: Math.max(1, row.modelData.w || 120)
                    property real natH: Math.max(1, row.modelData.h || 80)
                    property real fit: Math.min(boxW / natW, 160 / natH, 4)
                    width: Math.max(72, Math.min(boxW, natW * fit))
                    height: Math.max(48, natH * (width / natW))
                    source: row.modelData.path || ""
                    fillMode: Image.PreserveAspectFit
                    smooth: false
                    asynchronous: true
                }
                Text {
                    visible: shot.status === Image.Error
                    width: parent.width
                    text: "这张图片没有显示出来。原件仍在文矩包内，界面没有把它画完。"
                    wrapMode: Text.Wrap
                    color: root.muted
                    font.pixelSize: Math.round(12 * appearance.scale)
                    font.family: appearance.fontFamily
                }
                Text {
                    width: parent.width
                    text: row.modelData.note || ""
                    wrapMode: Text.Wrap
                    color: root.muted
                    font.pixelSize: Math.round(11 * appearance.scale)
                    font.family: appearance.fontFamily
                }
            }

            Rectangle {
                width: row.width
                height: holdCol.implicitHeight + 16
                visible: row.modelData.kind === "placeholder"
                radius: 8
                color: root.soft
                border.color: root.line
                Column {
                    id: holdCol
                    x: 10
                    y: 8
                    width: parent.width - 20
                    spacing: 2
                    Text {
                        width: parent.width
                        text: row.modelData.title || "占位"
                        color: root.ink
                        font.pixelSize: Math.round(13 * appearance.scale)
                        font.bold: true
                        font.family: appearance.fontFamily
                        elide: Text.ElideRight
                    }
                    Text {
                        width: parent.width
                        text: row.modelData.note || ""
                        wrapMode: Text.Wrap
                        color: root.muted
                        font.pixelSize: Math.round(12 * appearance.scale)
                        font.family: appearance.fontFamily
                    }
                }
            }
        }
    }
}
