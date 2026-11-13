---
name: verify-clipboard-import
description: "Re-check the clipboard import invariants after a change to core/clipboard_import.py, the docx image round-trip in core/wenju_format.py, or the read-versus-convert gate in app.py. Use when a change can drop, duplicate, reorder, or rewrite a pasted picture, or can write a file before the user converts."
---

# 核对剪贴板导入的四条不变量

剪贴板读入是文矩的核心路径。一条测试只覆盖写下来的例子。这个检查在声明的范围内穷举短文档，并直接跑仓库里的解析和读写代码。

## 不变量

读入返回的文档（经 `to_docx` 再 `from_docx`）必须满足：

1. 剪贴板里的每张图恰好出现一次，不丢、不重。
2. 段落、图片、表格的相对顺序不变。表格里的图仍在原来的单元格，不掉到表格后面。
3. EMF 和 WMF 的字节与来源相同，不被改成位图。
4. 读入不调用 `wenju_format.save`，也不往输出目录写文件。只有用户开始转换时，`Bridge._clipboard_item` 才保存 `.wenju`。

破坏任何一条，用户都会看到缺图、重图、图跑出单元格、矢量图变成别的东西，或者还没点转换就已经生成文件。

## 范围

穷举的是长度不超过 2 的文档。每一块只取六种之一：段落、PNG、EMF、空表格、单元格里一张 PNG、单元格里一张 EMF。每种文档都用同一套字节走 HTML `file://` 和 RTF `\bin`。另外单独核对：只走 HTML、只走 RTF、EMF/WMF 替换 PNG 预览、`\bin` 载荷里含 `{}\\`、左右两个单元格各一张图、文档已有图时不再追加那张单独的 MIME 图、以及一份 200 页（400 张 PNG/JPEG/EMF、200 个表格）的样本。

读入期间会在临时目录写一份 docx，返回前删掉。`DATA/预览` 里的预览缓存不在第 4 条里。单元格里「图在两个字中间」的先后，这个模型只保证图还在该格。图表、页眉页脚、合并文档、真实 Word 剪贴板样本都不在这次检查里。

## 代码

- `core/clipboard_import.py`：`document_from_parts`、`_apply_rtf_pictures`、`_through_docx`、`parts_from_mime`、`_file_image`，以及 RTF 的 `bin` 记号。
- `core/wenju_format.py`：表格单元格 `images` 的写出、读回和校验。
- `app.py`：`importClipboard`、`_clip_ready`、`_clip_failed`、`setConvertTarget`、`setClipboardBrush` 不写文件；`_begin_batch` 只在 `action=='convert'` 时调用 `_clipboard_item`，由它调用 `save`。

## 怎么跑

在仓库根目录：

```bash
python -m unittest test_clipboard_invariants -v
```

Python 3.8 即可，不需要额外的检查器。CI 的 `unit` 作业会跑同一个命令。大约一秒。末尾的 `SCALE` 行是 200 页样本的耗时和内存。

## 失败时怎么读

失败信息里的 spine 就是文档顺序：`text`、`image`（原始字节）、`table`（单元格文字和该格的图）、`break`。

- 实际 spine 比预期多一张图：图被放了两次。曾把 `_apply_rtf_pictures` 里「只追加没用完的 RTF 图」改成「每张 RTF 图都再追加一次」，一张图的文档就多出一张同样的图。
- 实际 spine 少一张图，或图出现在表格外面：图丢了，或从单元格里掉出来了。
- `image` 的字节不是原来的 EMF/WMF：字节被改写了。
- `AssertionError: save during read`：读入调用了 `wenju_format.save`。
- `importClipboard` 的断言失败并列出 `_clipboard_item`：读入路径在用户点转换之前就去写文件了。

先对照上面的函数看是代码坏了，还是文档形状超出了「六种块、长度不超过 2」的模型。超出范围时，改检查要单独说明新范围，不要为了让检查通过而放宽不变量。

## 同步

覆盖的就是上面三个文件里的那些函数。上次确认检查与代码一致的提交：`SYNC_COMMIT`。

只有在这个提交之后重新跑过检查，并且确认检查描述的仍是新提交里的代码时，才把 `SYNC_COMMIT` 改成新的提交号。覆盖的代码变了而这一行没变，就说明检查可能还在描述旧代码。
