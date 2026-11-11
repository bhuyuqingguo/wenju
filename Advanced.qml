import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    required property var controller
    color: appearance.colors.surface;radius:12;border.color:appearance.palette["#e0e6ee"]
    Rectangle {width:156;anchors.top:parent.top;anchors.bottom:parent.bottom;radius:12;color:appearance.palette["#edf2f7"]
        ListView {id:sectionList;anchors.fill:parent;anchors.margins:10;clip:true;spacing:3;model:root.controller.ruleSections
            ScrollBar.vertical:ScrollBar{policy:ScrollBar.AsNeeded}
            delegate:Rectangle {required property var modelData;width:ListView.view.width;height:34*appearance.scale;radius:6;color:root.controller.sectionName===modelData.key.replace("."," / ")?appearance.palette["#d6e3ef"]:"transparent"
                Text{anchors.left:parent.left;anchors.leftMargin:10;anchors.verticalCenter:parent.verticalCenter;text:modelData.name;color:appearance.palette["#294c6b"];font.pixelSize:Math.round(12*appearance.scale)}
                MouseArea{anchors.fill:parent;onClicked:{root.forceActiveFocus();root.controller.setSection(modelData.key);}}
            }
        }
    }
    ColumnLayout {
        anchors{left:parent.left;leftMargin:180;right:parent.right;rightMargin:22;top:parent.top;topMargin:22;bottom:parent.bottom;bottomMargin:20}spacing:14
        Text{text:root.controller.sectionName;color:appearance.palette["#22344a"];font.pixelSize:Math.round(21*appearance.scale);font.weight:Font.DemiBold}
        Text{text:root.controller.sectionTip;color:appearance.palette["#7b8899"];font.pixelSize:Math.round(12*appearance.scale);wrapMode:Text.WordWrap;Layout.fillWidth:true}
        Rectangle{Layout.fillWidth:true;height:1;color:appearance.palette["#e9eef4"]}
        ScrollView {Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
            ColumnLayout {width:parent.width;spacing:10
                Repeater {model:root.controller.ruleFields
                    delegate:Rectangle {id:row;required property var modelData;Layout.fillWidth:true;implicitHeight:64*appearance.scale;radius:8;color:appearance.palette["#f7f9fc"]
                        RowLayout {anchors.fill:parent;anchors.margins:12;spacing:12
                            Text {text:row.modelData.label;color:appearance.palette["#354b61"];font.pixelSize:Math.round(12*appearance.scale);wrapMode:Text.WordWrap;Layout.preferredWidth:170*appearance.scale;Layout.maximumWidth:170*appearance.scale}
                            Item{Layout.fillWidth:true}
                            Loader {Layout.preferredWidth:Math.min(280,row.width-210);Layout.preferredHeight:40*appearance.scale
                                property var rowData:row.modelData
                                sourceComponent:rowData.kind==="bool"?booleanEditor:rowData.kind==="choice"?choiceEditor:textEditor
                            }
                            Text{text:row.modelData.unit;color:appearance.palette["#7b8899"];font.pixelSize:Math.round(11*appearance.scale);Layout.preferredWidth:24}
                        }
                    }
                }
                Text {visible:root.controller.ruleFields.length===0;text:"请在左侧选择标题级别或封面子项。";color:appearance.palette["#7b8899"];font.pixelSize:Math.round(13*appearance.scale);Layout.topMargin:20}
            }
        }
        RowLayout {Layout.fillWidth:true
            Text {text:"有效修改自动保留在当前方案；任务使用启动时的规则。";color:appearance.palette["#7b8899"];font.pixelSize:Math.round(11*appearance.scale);Layout.fillWidth:true;wrapMode:Text.WordWrap}
            Button {visible:root.controller.sectionName==="字体嵌入";text:"添加字体目录";onClicked:root.controller.fontDirectory()}
        }
    }
    Component {id:booleanEditor
        Switch {property var f:parent.rowData;checked:f.value;onClicked:root.controller.editRule(f.path,checked);text:checked?"已开启":"已关闭";font.pixelSize:Math.round(12*appearance.scale)}
    }
    Component {id:textEditor
        TextField {property var f:parent.rowData;objectName:"field_"+f.path;text:f.display;selectByMouse:true;font.pixelSize:Math.round(12*appearance.scale);color:appearance.palette["#22344a"];leftPadding:10
            placeholderText:f.kind==="array"?"多个项目用顿号分隔":""
            background:Rectangle{radius:6;color:appearance.colors.surface;border.color:parent.activeFocus?appearance.palette["#245a83"]:appearance.palette["#dce4ed"]}
            onEditingFinished:{if(!root.controller.editRule(f.path,text))text=f.display;}
        }
    }
    Component {id:choiceEditor
        ComboBox {id:combo;property var f:parent.rowData;model:f.labels;editable:f.editable;currentIndex:f.values.indexOf(f.value);editText:f.display;font.pixelSize:Math.round(12*appearance.scale)
            palette.text:appearance.palette["#22344a"];palette.buttonText:appearance.palette["#22344a"];palette.base:appearance.colors.surface;palette.highlight:appearance.palette["#245a83"];palette.highlightedText:appearance.colors.onAccent
            background:Rectangle{radius:6;color:appearance.colors.surface;border.color:appearance.palette["#dce4ed"]}
            onActivated:root.controller.editRule(f.path,f.values[currentIndex])
            onAccepted:root.controller.editRule(f.path,editText)
            onActiveFocusChanged:if(!activeFocus&&editable&&editText!==f.display)root.controller.editRule(f.path,editText)
        }
    }
}
