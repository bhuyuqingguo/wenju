import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: home
    signal useTemplate(var entry, int destination)
    property string category:"全部"
    property string query:""
    property var filteredTemplates:bridge.templates.filter(t=>(category==="全部"||category===t.category)&&(!query||(t.name+t.desc+t.bodySummary).toLowerCase().includes(query)))
    spacing:16
    Rectangle {Layout.fillWidth:true;Layout.preferredHeight:104;radius:12;color:appearance.colors.soft
        Column {x:24;anchors.verticalCenter:parent.verticalCenter;spacing:10
            Text{text:"选一个模板，文档就有了章法。";color:appearance.colors.ink;font.family:appearance.fontFamily;font.pixelSize:Math.round(22*appearance.scale);font.weight:Font.DemiBold}
            Text{text:"01  选择模板     →     02  添加文档     →     03  一键整理";color:appearance.colors.muted;font.family:appearance.fontFamily;font.pixelSize:Math.round(12*appearance.scale)}
        }
        Text{anchors.right:parent.right;anchors.rightMargin:26;anchors.verticalCenter:parent.verticalCenter;text:bridge.templates.length+" 套\n可用模板";horizontalAlignment:Text.AlignRight;color:appearance.colors.accent;font.family:appearance.fontFamily;font.pixelSize:Math.round(17*appearance.scale);lineHeight:1.4}
    }
    RowLayout {Layout.fillWidth:true;spacing:8
        Repeater{model:["全部","科技研发","科研写作","公文办公","原版预设","我的模板"]
            delegate:Button {required property string modelData;text:modelData;implicitHeight:36*appearance.scale;implicitWidth:86*appearance.scale;font.family:appearance.fontFamily;font.pixelSize:Math.round(12*appearance.scale)
                contentItem:Text{text:parent.text;color:home.category===modelData?appearance.colors.onAccent:appearance.colors.ink;font:parent.font;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
                background:Rectangle{radius:7;color:home.category===modelData?appearance.colors.accent:appearance.colors.surface;border.color:appearance.colors.line}
                onClicked:home.category=modelData
            }
        }
        Item{Layout.fillWidth:true}
    }
    TextField {Layout.fillWidth:true;implicitHeight:38*appearance.scale;placeholderText:"搜索模板名称、用途或字体…";selectByMouse:true;font.family:appearance.fontFamily;font.pixelSize:Math.round(12*appearance.scale);color:appearance.colors.ink;leftPadding:14
        background:Rectangle{radius:8;color:appearance.colors.surface;border.color:appearance.colors.line}
        onTextEdited:home.query=text.trim().toLowerCase()
    }
    ScrollView {Layout.fillWidth:true;Layout.fillHeight:true;clip:true;contentWidth:availableWidth
        GridLayout {width:parent.width;columns:width<880||appearance.scale>1.15?2:3;columnSpacing:14;rowSpacing:14
            Repeater {model:home.filteredTemplates
                delegate:Rectangle {required property var modelData;Layout.fillWidth:true;Layout.preferredHeight:292*appearance.scale;radius:12;color:appearance.colors.surface;border.color:bridge.selectedId===modelData.id?appearance.colors.accent:appearance.colors.line
                    ColumnLayout {anchors.fill:parent;anchors.margins:18;spacing:10
                        RowLayout {Layout.fillWidth:true
                            Text{text:modelData.category;color:appearance.colors.muted;font.family:appearance.fontFamily;font.pixelSize:Math.round(10*appearance.scale)}
                            Item{Layout.fillWidth:true}
                            Text{text:modelData.id==="wudi-official"?"默认模板":bridge.selectedId===modelData.id?"当前方案":"";color:appearance.colors.accent;font.family:appearance.fontFamily;font.pixelSize:Math.round(10*appearance.scale)}
                        }
                        Text{text:modelData.name;Layout.fillWidth:true;elide:Text.ElideRight;color:appearance.colors.ink;font.family:appearance.fontFamily;font.pixelSize:Math.round(18*appearance.scale);font.weight:Font.DemiBold}
                        Rectangle {Layout.fillWidth:true;Layout.preferredHeight:112*appearance.scale;radius:7;color:appearance.colors.field
                            Column {anchors.fill:parent;anchors.margins:11;spacing:7*appearance.scale
                                Repeater {model:["正文   "+modelData.bodySummary,"行距   "+modelData.lineSummary,"标题   "+modelData.headingSummary,"页码   "+modelData.pageSummary]
                                    delegate:Text{required property string modelData;text:modelData;width:parent.width;elide:Text.ElideRight;color:appearance.colors.ink;font.family:appearance.fontFamily;font.pixelSize:Math.round(11*appearance.scale)}
                                }
                            }
                        }
                        Text{text:modelData.desc;Layout.fillWidth:true;Layout.fillHeight:true;wrapMode:Text.WordWrap;maximumLineCount:2;elide:Text.ElideRight;color:appearance.colors.muted;font.family:appearance.fontFamily;font.pixelSize:Math.round(11*appearance.scale)}
                        RowLayout {Layout.fillWidth:true
                            Button {objectName:"useTemplate_"+modelData.id;text:"用此模板整理  →";Layout.fillWidth:true;implicitHeight:36*appearance.scale;font.family:appearance.fontFamily;font.pixelSize:Math.round(12*appearance.scale)
                                contentItem:Text{text:parent.text;font:parent.font;color:appearance.colors.onAccent;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter}
                                background:Rectangle{radius:7;color:appearance.colors.accent}
                                onClicked:home.useTemplate(modelData,0)
                            }
                            Button{text:"细节";implicitWidth:58;implicitHeight:36*appearance.scale;flat:true;font.family:appearance.fontFamily;font.pixelSize:Math.round(11*appearance.scale);onClicked:{detail.entry=modelData;detail.open();}}
                        }
                    }
                }
            }
        }
    }
    Text{visible:home.filteredTemplates.length===0;text:"没有找到匹配模板，试试其他关键词或分类。";Layout.alignment:Qt.AlignHCenter;color:appearance.colors.muted;font.family:appearance.fontFamily;font.pixelSize:14}
    Text{text:"选中后即可添加文档；需要微调时，再进入设置。";color:appearance.colors.muted;font.family:appearance.fontFamily;font.pixelSize:Math.round(11*appearance.scale)}
    Dialog{id:detail;property var entry:({});anchors.centerIn:Overlay.overlay;width:540;modal:true;title:entry.name||"模板细节";standardButtons:Dialog.Close
        ColumnLayout {width:500;spacing:16
            Text{text:["正文："+(detail.entry.bodySummary||""),"行距："+(detail.entry.lineSummary||""),"标题："+(detail.entry.headingSummary||""),"页码："+(detail.entry.pageSummary||""),"页边距："+(detail.entry.marginSummary||"")].join("\n\n");color:appearance.colors.ink;font.family:appearance.fontFamily;font.pixelSize:Math.round(13*appearance.scale);wrapMode:Text.WordWrap;Layout.fillWidth:true}
            Text{text:detail.entry.desc||"";color:appearance.colors.muted;font.family:appearance.fontFamily;font.pixelSize:Math.round(12*appearance.scale);wrapMode:Text.WordWrap;Layout.fillWidth:true}
            RowLayout {Layout.fillWidth:true;Button{text:"编辑规则";onClicked:{detail.close();home.useTemplate(detail.entry,3);}}Item{Layout.fillWidth:true}Button{text:"使用这个模板 →";onClicked:{detail.close();home.useTemplate(detail.entry,0);}}}
        }
    }
}
