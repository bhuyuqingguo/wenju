import json

from wenju_format import WenjuDoc, apply_template, load, save, to_docx


def merge(docs):
    """Concatenate documents. The caller's list order is the section order. Source toc blocks are dropped."""
    blocks = []
    sections = []
    assets = {}
    for index, doc in enumerate(docs):
        if blocks:
            blocks.append({"type": "pagebreak"})
        start = len(blocks)
        blocks.extend(_copy_blocks(doc, index, assets))
        for section in doc.styles.get("sections") or [{"at": 0, "header": "", "footer": ""}]:
            sections.append({
                "at": start + int(section.get("at") or 0),
                "header": section.get("header") or "",
                "footer": section.get("footer") or "",
            })
    if any(block.get("type") == "heading" for block in blocks) and not any(block.get("type") == "toc" for block in blocks):
        blocks.insert(0, {"type": "toc"})
        for section in sections:
            if section["at"] > 0:
                section["at"] += 1
    return WenjuDoc(blocks, {"sections": sections}, assets, {"wenju": 1})


def _copy_blocks(doc, index, assets):
    mapping = {}
    for name in sorted(doc.assets):
        base = name.split("/")[-1]
        target = "assets/%d_%s" % (index, base)
        serial = 1
        while target in assets:
            target = "assets/%d_%d_%s" % (index, serial, base)
            serial += 1
        assets[target] = doc.assets[name]
        mapping[name] = target
    copied = []
    for block in doc.blocks:
        if block.get("type") == "toc":
            continue
        block = json.loads(json.dumps(block))
        if block.get("type") == "image":
            block["asset"] = mapping[block["asset"]]
        copied.append(block)
    return copied


def merge_export(paths, out_wenju, out_docx, template=None, progress=None):
    """Load paths in the given order, save one .wenju, and write a Word file with TOC and page fields.

    progress(percents, overall) receives one percent per input file and the overall percent.
    """
    if not paths:
        raise ValueError("没有可合稿的文档")
    docs = []
    percents = [0 for _ in paths]
    count = len(paths)

    def emit(overall):
        if progress:
            progress(list(percents), overall)

    for index, path in enumerate(paths):
        percents[index] = 50
        emit(int(sum(percents) / float(count) * 0.9))
        docs.append(load(path))
        percents[index] = 100
        emit(int(sum(percents) / float(count) * 0.9))
    merged = merge(docs)
    if template:
        apply_template(merged, template)
    save(merged, out_wenju)
    to_docx(merged, out_docx, template=None)
    emit(100)
    return {"wenju": out_wenju, "docx": out_docx}
