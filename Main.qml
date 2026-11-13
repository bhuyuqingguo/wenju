import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: win
    width: 1220; height: 820; minimumWidth: 1060; minimumHeight: 740
    visible: true; title: "文矩 · 文档格式整理"
    color: appearance.palette["#f4f6f9"]
    property int page: 2
    onPageChanged: if(appearance.motion)pageReveal.restart()
    NumberAnimation {id:pageReveal;target:pageArea;property:"opacity";from:0.35;to:1;duration:180;easing.type:Easing.OutCubic}
    property string ink: appearance.palette["#22344a"]
    property string blue: appearance.palette["#245a83"]
    property string muted: appearance.palette["#7b8899"]
    property string prefix: "— "
    property string suffix: " —"
    property string pageFont: "宋体"
    property real pageSize: 10.5
    property real spacing: 0
    property string alignment: "底部居中"
    property string startMode: "目录后"
    property int selectedPreset: 2
    property string templateId: "unit"
    property string templateName: "单位通用报告"
    property string category: "全部"
    property var templates: [
        {name:"极简数字", example:"1", prefix:"", suffix:"", font:"Times New Roman", size:10.5, spacing:0},
        {name:"短线页码", example:"- 1 -", prefix:"- ", suffix:" -", font:"Times New Roman", size:10.5, spacing:0},
        {name:"长线页码", example:"— 1 —", prefix:"— ", suffix:" —", font:"宋体", size:10.5, spacing:0},
        {name:"中文页码", example:"第 1 页", prefix:"第 ", suffix:" 页", font:"宋体", size:10.5, spacing:0}
    ]
    function settings() { return {prefix:prefix,suffix:suffix,font:pageFont,size:pageSize,spacing:spacing,alignment:alignment,start:startMode,template:templateId,enabled:pageEnabled,uniform:pageUniform}; }
    property bool pageEnabled: true
    property bool pageUniform: true
    property string pendingTemplate: ""
    property int pendingPage: 0
    function syncPage() {
        let s=bridge.pageSettings;
        prefix=s.prefix;suffix=s.suffix;pageFont=s.font;pageSize=Number(s.size);spacing=s.spacing;alignment=s.alignment;startMode=s.start;pageEnabled=s.enabled;pageUniform=s.uniform;
        templateId=bridge.selectedId;templateName=bridge.selectedName;
    }
    function commitPage() { bridge.updatePage(settings()); }
    function chooseTemplate(t, destination) {
        pendingTemplate=t.id;pendingPage=destination===undefined?0:destination;
        if(bridge.dirty) switchDialog.open();
        else {bridge.selectTemplate(t.id);page=pendingPage;}
    }
    function preset(i) { let t=templates[i]; selectedPreset=i; prefix=t.prefix;suffix=t.suffix;pageFont=t.font;pageSize=t.size;spacing=t.spacing;alignment="底部居中";pageEnabled=true;pageUniform=true;commitPage(); }
    Component.onCompleted: {syncPage();opening.playing=startupAnimation;if(bridge.fontNotice) fontNotice.open();}
    onClosing: function(close) { if(bridge.busy) {close.accepted=false; closeNotice.open();} }
    Dialog {id:fontNotice;anchors.centerIn:parent;width:640;title:"需要安装字体";modal:true;standardButtons:Dialog.Ok
        Text {width:600;wrapMode:Text.Wrap;text:bridge.fontNotice;color:win.ink}}
    Dialog {id:closeNotice; anchors.centerIn:parent;width:620;title:"文档正在整理";modal:true;standardButtons:Dialog.Ok
        Label {text:"请等待当前文档完成后再关闭。可先点击「停止后续任务」。"}}
    Dialog {id:reportDialog;anchors.centerIn:parent;title:"工作记录与报告";width:720;height:560;modal:true;standardButtons:Dialog.Close
        ScrollView {anchors.fill:parent;TextArea{id:reportText;readOnly:true;wrapMode:TextEdit.Wrap;font.pixelSize:Math.round(13*appearance.scale);selectByMouse:true}}
    }
    Connections {target:bridge
        function onReportReady(text){reportText.text=text;reportDialog.open();}
        function onRulesChanged(){win.syncPage();}
        function onErrorRaised(text){clipProgress.close();errorText.text=text;errorDialog.open();}
        function onClipboardStarted(){clipProgress.open();}
        function onClipboardFinished(text){clipProgress.close();clipDoneText.text=text;clipDone.open();}
    }
    Dialog{id:errorDialog;anchors.centerIn:parent;width:560;title:"请检查设置";modal:true;standardButtons:Dialog.Ok
        Text{id:errorText;width:520;wrapMode:Text.Wrap;color:win.ink}}
    Dialog{id:saveDialog;anchors.centerIn:parent;width:480;title:"另存为个人模板";modal:true
        ColumnLayout{width:440;spacing:16
            Txt{text:"保存完整规则，下次一键使用。";color:win.muted}
            Entry{id:saveName;objectName:"saveName";Layout.fillWidth:true;placeholderText:"例如：研发中心技术方案"}
            RowLayout{Item{Layout.fillWidth:true}Action{text:"取消";implicitWidth:90;onClicked:saveDialog.close()}Action{text:"保存模板";objectName:"saveAsButton";primary:true;onClicked:{win.contentItem.forceActiveFocus();if(bridge.saveAs(saveName.text))saveDialog.close();}}}
        }
        onOpened:{saveName.text=bridge.selectedName+" · 我的版本";saveName.forceActiveFocus();saveName.selectAll();}
    }
    Dialog{id:switchDialog;anchors.centerIn:parent;width:500;title:"切换模板";modal:true
        ColumnLayout{width:460;spacing:16
            Txt{text:"当前方案有修改。另存后可在模板书架找回。";wrapMode:Text.Wrap;Layout.fillWidth:true}
            RowLayout{Action{text:"取消";implicitWidth:80;onClicked:switchDialog.close()}Action{text:"先另存";implicitWidth:110;onClicked:{switchDialog.close();saveDialog.open();}}Action{text:"放弃修改并切换";implicitWidth:180;onClicked:{switchDialog.close();bridge.selectTemplate(win.pendingTemplate);win.page=win.pendingPage;}}}
        }
    }
    Dialog{id:deleteDialog;anchors.centerIn:parent;width:520;title:"删除个人模板";modal:true;standardButtons:Dialog.Yes|Dialog.No
        Txt{text:"删除当前个人模板？内置模板不受影响。"}
        onAccepted:bridge.deleteTemplate(bridge.selectedId)
    }
    Dialog{id:pathDialog;anchors.centerIn:parent;width:640;title:"按文件路径添加";modal:true;standardButtons:Dialog.Ok|Dialog.Cancel
        TextArea{id:pathInput;width:600;height:180;placeholderText:"每行一个文档完整路径";selectByMouse:true}
        onAccepted:bridge.addPaths(pathInput.text)
    }
    Dialog{id:inferConfirm;anchors.centerIn:parent;width:560;title:"识别模板";modal:true;standardButtons:Dialog.Ok|Dialog.Cancel
        Txt{text:"识别结果将替换当前工作方案。\n如需保留修改，请先另存为模板。"}
        onAccepted:bridge.inferTemplate()
    }
    Dialog{id:clipProgress;objectName:"clipProgress";anchors.centerIn:parent;width:420;title:"正在从剪贴板导入";modal:true;closePolicy:Popup.NoAutoClose
        ColumnLayout{width:380;spacing:12
            ProgressBar{from:0;to:100;value:bridge.importProgress;Layout.fillWidth:true}
            Txt{text:bridge.importProgress+"%";color:win.muted}
        }
    }
    Dialog{id:clipDone;objectName:"clipDone";anchors.centerIn:parent;width:520;title:"剪贴板导入完成";modal:true;standardButtons:Dialog.Ok
        Text{id:clipDoneText;width:480;wrapMode:Text.Wrap;color:win.ink}
    }

    Dialog{id:manageDialog;anchors.centerIn:parent;width:560;title:"管理模板";modal:true;standardButtons:Dialog.Close
        ColumnLayout{width:520;spacing:16
            Txt{text:"当前方案："+bridge.selectedName;Layout.fillWidth:true;elide:Text.ElideRight}
            GridLayout{columns:2;Layout.fillWidth:true
                Action{text:"导入模板";Layout.fillWidth:true;onClicked:{manageDialog.close();bridge.importTemplates();}}
                Action{text:"导出当前方案";Layout.fillWidth:true;onClicked:bridge.exportTemplates(false)}
                Action{text:"导出全部模板";Layout.fillWidth:true;onClicked:bridge.exportTemplates(true)}
                Action{text:"从文档识别";Layout.fillWidth:true;enabled:!bridge.busy;onClicked:{manageDialog.close();inferConfirm.open();}}
                Action{text:"另存当前方案";Layout.fillWidth:true;onClicked:{manageDialog.close();saveDialog.open();}}
                Action{text:"删除当前模板";Layout.fillWidth:true;enabled:bridge.personal;onClicked:{manageDialog.close();deleteDialog.open();}}
            }
        }
    }
    component Txt: Text { color:win.ink; font.family:appearance.fontFamily; font.pixelSize:Math.round(14*appearance.scale); renderType:Text.NativeRendering }
    component Action: Button {
        id: control
        property bool primary: false
        implicitHeight:42*appearance.scale; implicitWidth:140
        scale:down?0.97:1
        Behavior on scale {NumberAnimation{duration:appearance.motion?100:0}}
        leftPadding:18;rightPadding:18
        contentItem: Txt {text:control.text;color:control.primary?appearance.colors.onAccent:win.blue;horizontalAlignment:Text.AlignHCenter;verticalAlignment:Text.AlignVCenter;font.pixelSize:Math.round(13*appearance.scale);font.weight:Font.DemiBold}
        background: Rectangle {radius:8;color:control.primary?(control.hovered?appearance.palette["#316b97"]:win.blue):(control.hovered?appearance.palette["#e9eff6"]:appearance.colors.surface);border.color:control.primary?win.blue:appearance.palette["#dce3eb"];opacity:control.enabled?1:0.5}
    }
    component Entry: TextField {
        implicitHeight:42*appearance.scale; selectByMouse:true; color:win.ink;font.pixelSize:Math.round(14*appearance.scale);leftPadding:12
        background: Rectangle {radius:7;color:appearance.palette["#f9fafc"];border.color:parent.activeFocus?win.blue:appearance.palette["#e0e5ed"]}
    }
    component Choice: ComboBox {
        implicitHeight:42*appearance.scale;font.pixelSize:Math.round(13*appearance.scale)
        palette.text:win.ink;palette.buttonText:win.ink;palette.base:appearance.palette["#f9fafc"];palette.window:appearance.colors.surface;palette.highlight:win.blue;palette.highlightedText:appearance.colors.onAccent
        background: Rectangle {radius:7;color:appearance.palette["#f9fafc"];border.color:appearance.palette["#e0e5ed"]}
    }

    Rectangle {
        width:218;anchors.top:parent.top;anchors.bottom:parent.bottom;color:appearance.palette["#183a57"]
        Column {
            x:24;y:34;spacing:8
            Row {spacing:12
                Image {width:40;height:40;source:"core/素材/文矩_图标_512.png";smooth:true}
                Txt {text:"文矩";font.pixelSize:Math.round(28*appearance.scale);font.weight:Font.DemiBold;color:appearance.colors.navText}
            }
            Txt {text:"文档，自有章法。";font.pixelSize:Math.round(12*appearance.scale);color:appearance.palette["#a6bbcd"];font.letterSpacing:2}
        }
        Column {
            x:14;y:150;width:190;spacing:10
            Repeater {
                model:[{title:"选择模板",page:2,icon:"▥"},{title:"文档整理",page:0,icon:"▤"},{title:"设置",page:3,icon:"≡"}]
                delegate: Rectangle {
                    required property int index; required property var modelData
                    objectName:"nav_"+modelData.page; width:190;height:48*appearance.scale;radius:8;color:(win.page===modelData.page||(modelData.page===3&&(win.page===1||win.page===4)))?appearance.palette["#2c526f"]:"transparent"
                    Rectangle {visible:(win.page===modelData.page||(modelData.page===3&&(win.page===1||win.page===4)));x:0;y:15;width:3;height:18;radius:2;color:appearance.palette["#e6b35f"]}
                    Row {x:19;anchors.verticalCenter:parent.verticalCenter;spacing:16
                        Txt {text:modelData.icon;color:(win.page===modelData.page||(modelData.page===3&&(win.page===1||win.page===4)))?appearance.colors.navText:appearance.palette["#a6bbcd"];font.pixelSize:Math.round(20*appearance.scale)}
                        Txt {text:modelData.title;color:(win.page===modelData.page||(modelData.page===3&&(win.page===1||win.page===4)))?appearance.colors.navText:appearance.palette["#a6bbcd"];font.weight:Font.Medium}
                    }
                    MouseArea {anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:win.page=modelData.page}
                }
            }
            Txt {x:19;topPadding:22;text:"本地工作空间";color:appearance.palette["#738fa6"];font.pixelSize:Math.round(11*appearance.scale)}
        }
        Item {
            x:30;y:460;width:158;height:180;visible:win.height>900&&appearance.scale<=1
            Rectangle {x:12;y:18;width:117;height:145;radius:5;color:"transparent";border.color:appearance.palette["#35536c"];rotation:-8}
            Rectangle {x:28;y:9;width:117;height:145;radius:5;color:appearance.palette["#1e405d"];border.color:appearance.palette["#49647b"]
                Rectangle{x:19;y:25;width:45;height:4;radius:2;color:appearance.palette["#9aabba"]}
                Repeater {model:5;Rectangle{required property int index;x:19;y:48+index*14;width:index===4?46:77;height:2;color:appearance.palette["#45647d"]}}
                Rectangle {x:19;y:128;width:77;height:1;color:appearance.palette["#688297"]}
                Rectangle {x:87;y:19;width:10;height:10;radius:5;color:appearance.palette["#e6b35f"]}
            }
            Txt {x:17;y:178;text:"一拖即成 · 文自有矩";font.pixelSize:Math.round(10*appearance.scale);font.letterSpacing:1;color:appearance.palette["#819bad"]}
        }
        Column {x:30;anchors.bottom:parent.bottom;anchors.bottomMargin:28;spacing:9
            Row {spacing:7;Rectangle{width:6;height:6;radius:3;color:appearance.palette["#8cbaa8"];anchors.verticalCenter:parent.verticalCenter} Txt{text:"离线运行 · 文档不上传";color:appearance.palette["#adc1d0"];font.pixelSize:Math.round(11*appearance.scale)}}
            Txt {text:"3.3.0  /  文档格式整理";color:appearance.palette["#738fa6"];font.pixelSize:Math.round(11*appearance.scale)}
            Txt {text:"使用帮助 ↗";color:appearance.palette["#adc1d0"];font.pixelSize:Math.round(11*appearance.scale);MouseArea{anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:bridge.help()}}
        }
    }

    ColumnLayout {
        anchors {left:parent.left;leftMargin:250;right:parent.right;rightMargin:32;top:parent.top;topMargin:28;bottom:parent.bottom;bottomMargin:20}
        spacing:20
        RowLayout {
            Layout.fillWidth:true
            Column {spacing:7
                Txt {text:page===0?"文档整理":page===1?"页码设计":page===2?"选择模板":page===3?"设置 · 格式规则":"设置 · 外观";font.pixelSize:Math.round(28*appearance.scale);font.weight:Font.DemiBold}
                Txt {text:page===0?"选好格式，剩下的交给文矩。":page===1?"从一个好用的样式开始，让细节恰到好处。":page===2?"为不同的工作，准备恰好的格式。":page===3?"让每一项格式，都符合你的要求。":"文矩的另一面，随你喜欢。";color:muted;font.pixelSize:Math.round(13*appearance.scale)}
            }
            Item {Layout.fillWidth:true}
            Action {visible:page===2;text:"管理模板";onClicked:manageDialog.open()}
            Action {visible:page!==2&&page<4;text:page===0?"体验样例":"另存为模板";onClicked:{win.contentItem.forceActiveFocus();if(page===0)bridge.sample();else saveDialog.open();}}
            Action {visible:(page===1||page===3);text:"保存修改";primary:true;enabled:bridge.personal&&bridge.dirty;onClicked:{win.contentItem.forceActiveFocus();bridge.saveTemplate();}}
        }

        RowLayout{visible:page===1||page===3||page===4;Layout.fillWidth:true;spacing:10
            Action{text:"格式规则";primary:page===3;onClicked:page=3}
            Action{text:"页码设计";primary:page===1;onClicked:page=1}
            Action{text:"外观与皮肤";primary:page===4;onClicked:page=4}
            Item{Layout.fillWidth:true}
        }
        Item {id:pageArea
            Layout.fillWidth:true;Layout.fillHeight:true
            ColumnLayout {
                anchors.fill:parent;spacing:18;visible:page===0
                Rectangle {
                    Layout.fillWidth:true;Layout.preferredHeight:268;radius:12;color:appearance.palette["#eaf0f6"];border.color:appearance.palette["#dbe5ef"]
                    Column {anchors.centerIn:parent;spacing:10
                        Rectangle {anchors.horizontalCenter:parent.horizontalCenter;width:46;height:46;radius:12;color:appearance.colors.surface;Txt{anchors.centerIn:parent;text:"+";font.pixelSize:Math.round(30*appearance.scale);color:blue}}
                        Txt {anchors.horizontalCenter:parent.horizontalCenter;text:"把 Word 文档拖到这里";font.pixelSize:Math.round(19*appearance.scale);font.weight:Font.DemiBold}
                        Txt {anchors.horizontalCenter:parent.horizontalCenter;text:"DOCX / DOC / WPS / RTF / 文矩 · 可批量添加 · 原文件保持不变";color:muted;font.pixelSize:Math.round(12*appearance.scale)}
                        Row {anchors.horizontalCenter:parent.horizontalCenter;spacing:10
                            Action {text:"选择文档";primary:true;onClicked:bridge.choose()}
                            Action {objectName:"importClipboard";text:"从剪贴板导入";implicitWidth:168;enabled:!bridge.busy;onClicked:bridge.importClipboard(clipboardBrush.checked)}
                        }
                        CheckBox {id:clipboardBrush;objectName:"clipboardBrush";anchors.horizontalCenter:parent.horizontalCenter;text:"按模板刷格式";checked:false;onToggled:bridge.setClipboardBrush(checked)
                            palette.text:win.ink;palette.windowText:win.ink;palette.buttonText:win.ink
                        }
                        Txt {anchors.horizontalCenter:parent.horizontalCenter;text:"默认保留复制时的标题、表格、图片、字体和字号";color:muted;font.pixelSize:Math.round(11*appearance.scale)}
                    }
                    DropArea {anchors.fill:parent;onDropped:function(drop){if(drop.hasUrls)bridge.dropFiles(drop.urls);}}
                }
                Rectangle {
                    Layout.fillWidth:true;Layout.preferredHeight:72;radius:10;color:appearance.colors.surface;border.color:appearance.palette["#e2e7ee"]
                    RowLayout {anchors.fill:parent;anchors.margins:18;spacing:18
                        Rectangle {width:38;height:38;radius:8;color:appearance.palette["#f1f4f8"];Txt{anchors.centerIn:parent;text:"Aa";color:blue;font.pixelSize:Math.round(17*appearance.scale)}}
                        Column {spacing:5;Txt{text:win.templateName+(bridge.dirty?" · 已修改":"");font.weight:Font.Medium}Txt{text:"页码："+prefix+"1"+suffix+"  ·  "+pageFont+"  "+pageSize+" 磅";color:muted;font.pixelSize:Math.round(12*appearance.scale)}}
                        Item {Layout.fillWidth:true}
                        Action {text:"选择模板";implicitWidth:100;onClicked:page=2}
                        Action {text:"高级设置";implicitWidth:100;onClicked:page=3}
                    }
                }
                Rectangle {
                    Layout.fillWidth:true;Layout.fillHeight:true;radius:12;color:appearance.colors.surface;border.color:appearance.palette["#e2e7ee"]
                    ColumnLayout {anchors.fill:parent;anchors.margins:20;spacing:12
                        RowLayout {Layout.fillWidth:true;Txt{text:"待整理文档";font.weight:Font.DemiBold}Txt{text:bridge.files.length+" 份";color:muted;font.pixelSize:Math.round(12*appearance.scale)}Item{Layout.fillWidth:true}Action{text:"清空列表";implicitWidth:96;implicitHeight:32;enabled:!bridge.busy;onClicked:bridge.clear()}}
                        Rectangle {Layout.fillWidth:true;height:1;color:appearance.palette["#edf0f5"]}
                        Item {Layout.fillWidth:true;Layout.fillHeight:true
                            Column {visible:bridge.files.length===0;anchors.centerIn:parent;spacing:8
                                Txt {anchors.horizontalCenter:parent.horizontalCenter;text:"准备好你的第一份文档";color:appearance.palette["#8795a5"]}
                                Txt {text:"也可以点击右上角「体验样例」，看看整理效果。";color:appearance.palette["#a0aab7"];font.pixelSize:Math.round(12*appearance.scale)}
                            }
                            ListView {anchors.fill:parent;clip:true;spacing:8;model:bridge.files
                                delegate:Rectangle {required property var modelData;required property int index;width:ListView.view.width;height:72;radius:8;color:appearance.palette["#f7f9fc"]
                                    RowLayout {anchors.fill:parent;anchors.margins:12;spacing:12
                                        Rectangle{width:32;height:36;radius:5;color:appearance.palette["#e3edf6"];Txt{anchors.centerIn:parent;text:modelData.name.toLowerCase().endsWith(".wenju")?"文":"W";color:blue;font.weight:Font.Bold}}
                                        ColumnLayout{Layout.fillWidth:true;spacing:4;Txt{text:modelData.name;Layout.fillWidth:true;elide:Text.ElideMiddle;font.pixelSize:Math.round(13*appearance.scale)}Txt{text:modelData.state;color:modelData.output?appearance.palette["#35806c"]:muted;font.pixelSize:Math.round(11*appearance.scale);Layout.fillWidth:true;elide:Text.ElideRight}}
                                    }
                                    MouseArea{anchors.fill:parent;anchors.rightMargin:300;onClicked:bridge.openFile(index)}
                                    Row {anchors.right:parent.right;anchors.rightMargin:8;anchors.verticalCenter:parent.verticalCenter;spacing:6
                                        Action {text:"存为文矩";implicitWidth:96;implicitHeight:32;enabled:!bridge.busy;onClicked:bridge.saveWenju(index)}
                                        Action {text:"导出DOCX";implicitWidth:108;implicitHeight:32;enabled:!bridge.busy;onClicked:bridge.exportDocx(index)}
                                        Action {text:"报告";implicitWidth:64;implicitHeight:32;visible:!!modelData.output||!!modelData.error;onClicked:bridge.showReport(index)}
                                    }
                                }
                            }
                        }
                    }
                }
                RowLayout {Layout.fillWidth:true
                    Action {text:"打开输出文件夹";onClicked:bridge.openOutput()}
                    Action {text:"按路径添加";implicitWidth:110;onClicked:pathDialog.open()}
                    Item{Layout.fillWidth:true}
                    Action {visible:bridge.busy;text:"停止后续任务";onClicked:bridge.cancel()}
                    Action {text:bridge.busy?"正在整理…":"开始整理  →";primary:true;implicitWidth:166;enabled:!bridge.busy;onClicked:{win.contentItem.forceActiveFocus();bridge.start(win.settings());}}
                }
            }

            ColumnLayout {
                anchors.fill:parent;spacing:18;visible:page===1
                RowLayout {Layout.fillWidth:true;spacing:12
                    Repeater {model:win.templates
                        delegate:Rectangle {required property var modelData;required property int index;Layout.fillWidth:true;Layout.preferredHeight:100;radius:10;color:selectedPreset===index?appearance.palette["#eaf1f8"]:appearance.colors.surface;border.color:selectedPreset===index?blue:appearance.palette["#e0e6ee"]
                            Column {anchors.centerIn:parent;spacing:12
                                Txt{text:modelData.example;anchors.horizontalCenter:parent.horizontalCenter;font.pixelSize:Math.round(23*appearance.scale);color:blue}
                                Txt{text:modelData.name;anchors.horizontalCenter:parent.horizontalCenter;font.pixelSize:Math.round(12*appearance.scale);color:muted}
                            }
                            MouseArea{anchors.fill:parent;cursorShape:Qt.PointingHandCursor;onClicked:win.preset(index)}
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth:true;Layout.fillHeight:true;spacing:18
                    Rectangle {
                        Layout.preferredWidth:355;Layout.fillHeight:true;radius:12;color:appearance.colors.surface;border.color:appearance.palette["#e2e7ee"]
                        ScrollView {anchors.fill:parent;anchors.margins:22;clip:true;contentWidth:availableWidth
                        ColumnLayout {width:parent.width;spacing:7
                            RowLayout{Layout.fillWidth:true;Txt{text:"样式细节";font.pixelSize:Math.round(16*appearance.scale);font.weight:Font.DemiBold}Item{Layout.fillWidth:true}Switch{checked:win.pageEnabled;text:"启用";onClicked:{win.pageEnabled=checked;win.commitPage();}}}
                            Txt{text:win.pageUniform?"所有字符统一应用字体、字号与字间距":"已保留中西文字体分别设置（见高级设置）";font.pixelSize:Math.round(11*appearance.scale);color:muted}
                            RowLayout {Layout.fillWidth:true;spacing:12
                                ColumnLayout {Layout.fillWidth:true;Txt{text:"左侧字符";font.pixelSize:Math.round(12*appearance.scale);color:muted}Entry{Layout.fillWidth:true;text:win.prefix;onTextEdited:{win.prefix=text;selectedPreset=-1;win.commitPage()}}}
                                ColumnLayout {Layout.fillWidth:true;Txt{text:"右侧字符";font.pixelSize:Math.round(12*appearance.scale);color:muted}Entry{Layout.fillWidth:true;text:win.suffix;onTextEdited:{win.suffix=text;selectedPreset=-1;win.commitPage()}}}
                            }
                            Txt{text:"字体";font.pixelSize:Math.round(12*appearance.scale);color:muted}
                            Choice {Layout.fillWidth:true;editable:true;model:bridge.fontNames;editText:win.pageFont;onActivated:{win.pageFont=currentText;win.commitPage();}onAccepted:{win.pageFont=editText;win.commitPage();}onActiveFocusChanged:if(!activeFocus&&editText.trim()&&editText!==win.pageFont){win.pageFont=editText;win.commitPage();}}
                            RowLayout {Layout.fillWidth:true;spacing:12
                                ColumnLayout {Layout.fillWidth:true;Txt{text:"字号 / 磅";font.pixelSize:Math.round(12*appearance.scale);color:muted}Choice{Layout.fillWidth:true;editable:true;validator:DoubleValidator{bottom:5;top:72} model:["9","10.5","12","14","16","18"];editText:String(win.pageSize);currentIndex:model.indexOf(String(win.pageSize));onActivated:{win.pageSize=Number(currentText);selectedPreset=-1;win.commitPage()}onAccepted:{if(Number(editText)>=5&&Number(editText)<=72){win.pageSize=Number(editText);win.commitPage();}}}}
                                ColumnLayout {Layout.fillWidth:true;Txt{text:"字间距 / 磅";font.pixelSize:Math.round(12*appearance.scale);color:muted}Choice{Layout.fillWidth:true;editable:true;validator:DoubleValidator{bottom:-2;top:20} model:["-0.5","0","0.5","1","1.5","2","3"];editText:String(win.spacing);currentIndex:model.indexOf(String(win.spacing));onActivated:{win.spacing=Number(currentText);selectedPreset=-1;win.commitPage()}onAccepted:{if(Number(editText)>=-2&&Number(editText)<=20){win.spacing=Number(editText);win.commitPage();}}}}
                            }
                            Txt{text:"对齐方式";font.pixelSize:Math.round(12*appearance.scale);color:muted}
                            Choice {Layout.fillWidth:true;model:["底部左侧","底部居中","底部右侧","底部两端对齐"];currentIndex:model.indexOf(win.alignment);onActivated:{win.alignment=currentText;win.commitPage();}}
                            Txt{text:"从哪里开始编号";font.pixelSize:Math.round(12*appearance.scale);color:muted}
                            Choice {Layout.fillWidth:true;model:["目录后","封面后","全文"];currentIndex:model.indexOf(win.startMode);onActivated:{win.startMode=currentText;win.commitPage();}}
                            Item{Layout.preferredHeight:4}
                        }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth:true;Layout.fillHeight:true;radius:12;color:appearance.palette["#e9eef4"]
                        Txt{x:20;y:18;text:"样式预览";font.pixelSize:Math.round(12*appearance.scale);color:muted}
                        Rectangle {
                            anchors{left:parent.left;right:parent.right;top:parent.top;bottom:parent.bottom;leftMargin:36;rightMargin:36;topMargin:54;bottomMargin:58}
                            color:"#ffffff";radius:2
                            Column {anchors{left:parent.left;right:parent.right;top:parent.top;margins:28}spacing:14
                                Rectangle{width:parent.width*0.55;height:9;color:appearance.palette["#d5dee8"]}
                                Item{height:5;width:1}
                                Repeater{model:9;Rectangle{required property int index;width:parent.width*(index===8?0.63:1);height:5;radius:2;color:appearance.palette["#edf0f4"]}}
                            }
                            Rectangle {anchors{left:parent.left;right:parent.right;bottom:parent.bottom;leftMargin:24;rightMargin:24;bottomMargin:65}height:1;color:appearance.palette["#edf0f4"]}
                            Text {anchors{left:parent.left;right:parent.right;bottom:parent.bottom;leftMargin:24;rightMargin:24;bottomMargin:30}
                                text:win.pageEnabled?win.prefix+"1"+win.suffix:"不显示页码";color:"#22344a";font.family:win.pageFont;font.pointSize:win.pageSize;font.letterSpacing:win.spacing*96/72
                                horizontalAlignment:(win.alignment==="底部左侧"||win.alignment==="底部两端对齐")?Text.AlignLeft:win.alignment==="底部右侧"?Text.AlignRight:Text.AlignHCenter
                            }
                        }
                        Txt{anchors{bottom:parent.bottom;bottomMargin:22;horizontalCenter:parent.horizontalCenter}text:"示意预览 · 实际分页以 Word / WPS 为准";color:muted;font.pixelSize:Math.round(11*appearance.scale)}
                    }
                }
                RowLayout {Layout.fillWidth:true;Txt{text:"数字自动随页变化，无需手动输入。";color:muted;font.pixelSize:Math.round(12*appearance.scale)}Item{Layout.fillWidth:true}Action{text:"返回文档整理 →";primary:true;implicitWidth:166;onClicked:page=0}}
            }
            TemplateHome{anchors.fill:parent;visible:page===2;onUseTemplate:function(entry,destination){win.chooseTemplate(entry,destination);if(entry.redhead)bridge.setSection("红头");}}
            ColumnLayout{anchors.fill:parent;visible:page===3;spacing:14
                RowLayout{Layout.fillWidth:true
                    Txt{text:bridge.selectedName+(bridge.dirty?" · 已修改":"");font.pixelSize:Math.round(14*appearance.scale);color:win.blue;Layout.fillWidth:true;elide:Text.ElideRight}
                    Action{text:"环境检测";implicitWidth:110;enabled:!bridge.busy;onClicked:bridge.environment()}
                    Action{text:"从文档识别";implicitWidth:125;enabled:!bridge.busy;onClicked:inferConfirm.open()}
                }
                Advanced{Layout.fillWidth:true;Layout.fillHeight:true;controller:bridge}
                RowLayout{Layout.fillWidth:true;Txt{text:"内置模板修改后请另存，个人模板可直接保存。";font.pixelSize:Math.round(11*appearance.scale);color:muted}Item{Layout.fillWidth:true}Action{text:"返回整理 →";primary:true;onClicked:{win.contentItem.forceActiveFocus();page=0;}}}
            }

            AppearancePage{anchors.fill:parent;visible:page===4}

        }
        Rectangle {Layout.fillWidth:true;height:1;color:appearance.palette["#dfe5ed"]}
        RowLayout{Layout.fillWidth:true;Rectangle{width:6;height:6;radius:3;color:bridge.busy?appearance.palette["#c79a46"]:appearance.palette["#5a9684"]}Txt{text:bridge.status;color:muted;font.pixelSize:Math.round(11*appearance.scale);Layout.fillWidth:true;elide:Text.ElideRight}Txt{text:"WENJU";color:appearance.palette["#a3adba"];font.pixelSize:Math.round(10*appearance.scale);font.letterSpacing:2}}
    }
    Opening{id:opening;anchors.fill:parent;z:1000;onFinished:win.contentItem.forceActiveFocus()}
}
