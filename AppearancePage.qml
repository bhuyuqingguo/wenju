import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    spacing:18
    ScrollView {Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
        ColumnLayout {width:parent.width;spacing:20
            Text {text:"为你的工作空间，换一种心情。";font.pixelSize:Math.round(20*appearance.scale);font.family:appearance.fontFamily;color:appearance.colors.ink}
            GridLayout {Layout.fillWidth:true;columns:3;columnSpacing:14;rowSpacing:14
                Repeater {model:appearance.themes
                    delegate:Rectangle {required property var modelData;Layout.fillWidth:true;Layout.preferredHeight:165*appearance.scale;radius:12;color:appearance.colors.surface;border.width:appearance.themeId===modelData.id?2:1;border.color:appearance.themeId===modelData.id?appearance.colors.accent:appearance.colors.line
                        ColumnLayout {anchors.fill:parent;anchors.margins:15;spacing:10
                            Rectangle {Layout.fillWidth:true;Layout.fillHeight:true;radius:6;color:modelData.bg
                                Rectangle{width:parent.width*0.24;height:parent.height;radius:6;color:modelData.nav}
                                Column{anchors{left:parent.left;leftMargin:parent.width*0.30;right:parent.right;rightMargin:12;top:parent.top;topMargin:12}spacing:8
                                    Rectangle{width:parent.width*0.6;height:5;radius:2;color:modelData.accent}
                                    Rectangle{width:parent.width;height:22*appearance.scale;radius:4;color:modelData.surface}
                                    Rectangle{width:parent.width*0.4;height:12*appearance.scale;radius:3;color:modelData.accent}
                                }
                            }
                            Text{text:modelData.name;font.pixelSize:Math.round(14*appearance.scale);font.family:appearance.fontFamily;color:appearance.colors.ink;font.weight:Font.DemiBold}
                            Text{text:modelData.desc;font.pixelSize:Math.round(11*appearance.scale);font.family:appearance.fontFamily;color:appearance.colors.muted;Layout.fillWidth:true;elide:Text.ElideRight}
                        }
                        MouseArea{anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:appearance.setPreferences(modelData.id,appearance.fontFamily,appearance.fontSize)}
                    }
                }
            }
            Rectangle {Layout.fillWidth:true;implicitHeight:165*appearance.scale;radius:12;color:appearance.colors.surface;border.color:appearance.colors.line
                ColumnLayout {anchors.fill:parent;anchors.margins:22;spacing:12
                    Text{text:"界面文字";font.pixelSize:Math.round(17*appearance.scale);font.family:appearance.fontFamily;color:appearance.colors.ink;font.weight:Font.DemiBold}
                    RowLayout {Layout.fillWidth:true;spacing:16
                        ColumnLayout {Layout.fillWidth:true
                            Text{text:"字体";color:appearance.colors.muted;font.pixelSize:Math.round(12*appearance.scale);font.family:appearance.fontFamily}
                            ComboBox{objectName:"uiFontChoice";Layout.fillWidth:true;implicitHeight:42*appearance.scale;model:bridge.fontNames;currentIndex:model.indexOf(appearance.fontFamily);editable:true;editText:appearance.fontFamily;font.family:appearance.fontFamily;font.pixelSize:Math.round(14*appearance.scale)
                                onActivated:appearance.setPreferences(appearance.themeId,currentText,appearance.fontSize)
                                onAccepted:appearance.setPreferences(appearance.themeId,editText,appearance.fontSize)
                            }
                        }
                        ColumnLayout {Layout.preferredWidth:260*appearance.scale
                            Text{text:"字号";color:appearance.colors.muted;font.pixelSize:Math.round(12*appearance.scale);font.family:appearance.fontFamily}
                            ComboBox{objectName:"uiSizeChoice";Layout.fillWidth:true;implicitHeight:42*appearance.scale;model:["12 · 紧凑","14 · 标准","16 · 舒适","18 · 大字"];currentIndex:[12,14,16,18].indexOf(appearance.fontSize);font.family:appearance.fontFamily;font.pixelSize:Math.round(14*appearance.scale)
                                onActivated:appearance.setPreferences(appearance.themeId,appearance.fontFamily,[12,14,16,18][currentIndex])
                            }
                        }
                    }
                    Text{text:"只改变软件界面，不改变文档字体、字号或模板。";color:appearance.colors.muted;font.pixelSize:Math.round(12*appearance.scale);font.family:appearance.fontFamily}
                }
            }
        }
    }
    RowLayout{Layout.fillWidth:true
        Switch{text:"界面动效";checked:appearance.motion;onClicked:appearance.setMotion(checked)}
        Switch{text:"启动时显示开场动画";checked:appearance.showIntro;font.family:appearance.fontFamily;onClicked:appearance.setShowIntro(checked)}
        Item{Layout.fillWidth:true}
    }
    RowLayout{Layout.fillWidth:true
        Text{text:"自动保存 · 即时生效";color:appearance.colors.muted;font.pixelSize:Math.round(12*appearance.scale);font.family:appearance.fontFamily;Layout.fillWidth:true}
        Button{text:"恢复默认外观";implicitHeight:42*appearance.scale;font.family:appearance.fontFamily;font.pixelSize:Math.round(13*appearance.scale);onClicked:appearance.reset()}
    }
}
