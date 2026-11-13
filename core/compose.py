import json

from wenju_format import WenjuDoc, apply_template, load, save, to_docx


def merge(docs):
    """Concatenate documents. The caller's list order is the section order. Source toc blocks are dropped."""
    blocks = []
    sections = []
    assets = {}
    for index, doc in enumerate(docs):
        copied = _copy_blocks(doc, index, assets)
        stripped = 0
        if index and copied and copied[0].get("type") == "pagebreak":
            copied = copied[1:]
            stripped = 1
        if index and (not blocks or blocks[-1].get("type") != "pagebreak"):
            blocks.append({"type": "pagebreak"})
        start = len(blocks)
        blocks.extend(copied)
        for order, section in enumerate(doc.sections or [{"at": 0, "header": "", "footer": ""}]):
            brk = section.get("break") or "nextPage"
            if order == 0 and index > 0:
                brk = "nextPage"
            rel = _content_index(doc.blocks, int(section.get("at") or 0))
            if stripped and rel:
                rel -= 1
            sections.append({
                "at": start + rel,
                "header": section.get("header") or "",
                "footer": section.get("footer") or "",
                "break": brk,
            })
    if any(block.get("type") == "heading" for block in blocks) and not any(block.get("type") == "toc" for block in blocks):
        blocks.insert(0, {"type": "toc"})
        for section in sections:
            if section["at"] > 0:
                section["at"] += 1
    return WenjuDoc(blocks, {}, assets, {"format": "wenju", "version": 1, "source": {"kind": "merge", "name": ""}}, sections)


def _content_index(blocks, at):
    """Index within the blocks that remain after toc entries are dropped."""
    kept = 0
    for index, block in enumerate(blocks):
        if index >= at:
            return kept
        if block.get("type") != "toc":
            kept += 1
    return kept


def _copy_blocks(doc, index, assets):
    mapping = {}
    for name in sorted(doc.assets):
        base = name.split("/")[-1]
        target = "%d_%s" % (index, base)
        serial = 1
        while target in assets:
            target = "%d_%d_%s" % (index, serial, base)
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
