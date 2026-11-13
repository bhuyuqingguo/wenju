# -*- coding: utf-8 -*-
"""East Asian font names to write into a docx package."""

ALIASES = {
    "仿宋_GB2312": "仿宋",
}


def resolve(name):
    if not name:
        return name
    return ALIASES.get(str(name), name)
