import QtQuick
import QtQuick.Controls

Rectangle {
    id: opening
    objectName: "openingAnimation"
    property bool playing: false
    property real reveal: 0
    property real settle: 0
    property real lettering: 0
    property real seal: 0
    signal finished()
    visible: playing
    focus: playing
    color: "#102C45"
    function dismiss() { sequence.stop(); playing = false; finished(); }
    onPlayingChanged: if (playing) { forceActiveFocus(); sequence.restart(); }
    Keys.onEscapePressed: dismiss()
    MouseArea { anchors.fill: parent }

    // Quiet architectural lines echo the ruler in the original brand mark.
    Repeater {
        model: 7
        Rectangle {
            required property int index
            x: opening.width / 2 + (index - 3) * 120
            width: 1; height: opening.height
            color: "#24435B"; opacity: 0.23 * opening.reveal
        }
    }
    Rectangle {
        anchors.centerIn: parent; anchors.verticalCenterOffset: -36
        width: 420; height: 420; radius: 210; color: "transparent"
        border.color: "#496278"; opacity: 0.17 * opening.reveal
        scale: 0.94 + opening.settle * 0.06
    }
    Rectangle {
        anchors.centerIn: parent; anchors.verticalCenterOffset: -36
        width: 560; height: 560; radius: 280; color: "transparent"
        border.color: "#496278"; opacity: 0.09 * opening.reveal
    }
    Item {
        id: composition
        width: 440; height: 340
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -12 + (1 - opening.settle) * 12
        opacity: opening.reveal
        Item {
            id: emblem
            width: 132; height: 132; anchors.horizontalCenter: parent.horizontalCenter
            y: 14; scale: 0.92 + opening.settle * 0.08
            // A pair of sheets resolves into the signature blue tile.
            Rectangle {
                x: -7 * (1 - opening.settle); y: 8; width: 132; height: 132; radius: 29
                rotation: -8 * (1 - opening.settle); color: "#34536B"
                opacity: 0.35 * (1 - opening.settle)
            }
            Rectangle { anchors.fill: parent; radius: 29; color: "#204F79" }
            Item {
                x: 28; y: 23; width: 80; height: 82
                // The ruler and baseline draw themselves without textures or shaders.
                Rectangle { x: 0; y: 0; width: 15; height: 80 * opening.settle; color: "#F6F8FA" }
                Repeater {
                    model: 3
                    Rectangle {
                        required property int index
                        x: 0; y: 28 + index * 11; width: 10; height: 3
                        color: "#204F79"; opacity: opening.settle
                    }
                }
                Rectangle { x: 0; y: 65; width: 80 * opening.settle; height: 15; color: "#F6F8FA" }
                Repeater {
                    model: 3
                    Rectangle {
                        required property int index
                        property real progress: Math.max(0, Math.min(1, (opening.settle - index * 0.16) / 0.68))
                        x: 29 + (1 - progress) * (16 + index * 9); y: 15 + index * 15
                        width: (50 - index * 11) * progress; height: 6; radius: 3
                        color: index === 0 ? "#F6F8FA" : index === 1 ? "#B8CDD9" : "#85A8C2"
                        opacity: progress
                    }
                }
            }
            Rectangle {
                x: 99; y: 18; width: 14; height: 14; radius: 7
                color: "#FFB522"; scale: opening.seal; opacity: opening.seal
            }
        }
        Text {
            x: 0; y: 176 + (1 - opening.lettering) * 10; width: parent.width
            text: "文矩"; horizontalAlignment: Text.AlignHCenter
            font.family: appearance.fontFamily; font.pixelSize: 46
            font.weight: Font.Medium; font.letterSpacing: 9
            color: "#F4F3EE"; opacity: opening.lettering
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; y: 246; spacing: 13
            opacity: opening.lettering
            Rectangle { width: 30; height: 1; color: "#A68B5C"; anchors.verticalCenter: parent.verticalCenter }
            Text {
                text: "文档，自有章法。"; font.family: appearance.fontFamily
                font.pixelSize: 15; font.letterSpacing: 3; color: "#BBCBD5"
            }
            Rectangle { width: 30; height: 1; color: "#A68B5C"; anchors.verticalCenter: parent.verticalCenter }
        }
        Text {
            y: 297; width: parent.width; text: "W E N J U   /   D O C U M E N T  S T U D I O"
            horizontalAlignment: Text.AlignHCenter; font.pixelSize: 9
            color: "#7894A9"; opacity: opening.lettering * 0.85
        }
    }
    Column {
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom
        anchors.bottomMargin: 42; spacing: 12; opacity: opening.lettering
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; spacing: 8
            Repeater {
                model: 3
                Rectangle {
                    required property int index
                    width: index === 1 ? 24 : 4; height: 3; radius: 1.5
                    color: index === 1 ? "#C7A261" : "#486176"
                }
            }
        }
        Text { text: "从一份好模板开始"; font.family: appearance.fontFamily; font.pixelSize: 12; font.letterSpacing: 2; color: "#8FA8BA" }
    }
    Button {
        id: skip
        objectName: "skipOpening"
        anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 24
        text: "跳过  →"; implicitWidth: 100; implicitHeight: 40
        onClicked: opening.dismiss()
        background: Rectangle { radius: 20; color: skip.hovered ? "#29465E" : "transparent"; border.color: "#3A5367" }
        contentItem: Text { text: skip.text; color: "#C2D0DA"; font.family: appearance.fontFamily; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    }
    SequentialAnimation {
        id: sequence
        PropertyAction { target: opening; property: "opacity"; value: 1 }
        PropertyAction { target: opening; property: "reveal"; value: 0 }
        PropertyAction { target: opening; property: "settle"; value: 0 }
        PropertyAction { target: opening; property: "lettering"; value: 0 }
        PropertyAction { target: opening; property: "seal"; value: 0 }
        ParallelAnimation {
            NumberAnimation { target: opening; property: "reveal"; to: 1; duration: 360; easing.type: Easing.OutCubic }
            SequentialAnimation {
                PauseAnimation { duration: 100 }
                NumberAnimation { target: opening; property: "settle"; to: 1; duration: 850; easing.type: Easing.InOutCubic }
            }
            SequentialAnimation {
                PauseAnimation { duration: 560 }
                NumberAnimation { target: opening; property: "lettering"; to: 1; duration: 600; easing.type: Easing.OutCubic }
            }
            SequentialAnimation {
                PauseAnimation { duration: 820 }
                NumberAnimation { target: opening; property: "seal"; to: 1; duration: 320; easing.type: Easing.OutCubic }
            }
        }
        PauseAnimation { duration: 440 }
        NumberAnimation { target: opening; property: "opacity"; to: 0; duration: 380; easing.type: Easing.InOutCubic }
        ScriptAction { script: { opening.playing = false; opening.finished(); } }
    }
}
