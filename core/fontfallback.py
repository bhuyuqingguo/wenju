FALLBACK = {
    "仿宋_GB2312": "仿宋",
    "楷体_GB2312": "楷体",
    "黑体_GB2312": "黑体",
}


def resolve(name):
    if not name:
        return name
    return FALLBACK.get(name, name)
