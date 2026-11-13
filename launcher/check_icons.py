"""Fail the build when a package entry has a missing or incomplete icon.

Windows: the user-facing exe must embed a GROUP_ICON with 16, 24, 32, 48 and
256. python.exe / pythonw.exe keep the CPython icon and must not be the entry.
Linux: a desktop entry's Icon= must resolve, and an AppImage must contain
.DirIcon. There is no deb in this repository; the hicolor tree is what an
install script copies into ~/.local/share/icons.
"""
from pathlib import Path
import struct, sys

REQUIRED = (16, 24, 32, 48, 256)


def ico_sizes(path):
    data = Path(path).read_bytes()
    if data[:4] != b'\x00\x00\x01\x00':
        raise SystemExit(f'{path} is not an ICO')
    count = struct.unpack_from('<H', data, 4)[0]
    sizes = []
    for i in range(count):
        w, h = data[6 + i * 16], data[7 + i * 16]
        sizes.append((w or 256, h or 256))
    return sizes


def _sections(data):
    e = struct.unpack_from('<I', data, 0x3C)[0]
    if data[e:e + 4] != b'PE\0\0':
        raise SystemExit('not a PE file')
    nsec = struct.unpack_from('<H', data, e + 6)[0]
    optsz = struct.unpack_from('<H', data, e + 20)[0]
    magic = struct.unpack_from('<H', data, e + 24)[0]
    if magic == 0x20B:
        dd = e + 24 + 112
    elif magic == 0x10B:
        dd = e + 24 + 96
    else:
        raise SystemExit('unknown PE magic')
    rsrc_rva = struct.unpack_from('<I', data, dd + 2 * 8)[0]
    sec = e + 24 + optsz
    sections = []
    for i in range(nsec):
        vs, va, rs, rp = struct.unpack_from('<IIII', data, sec + i * 40 + 8)
        sections.append((va, max(vs, rs), rp))
    return rsrc_rva, sections


def _r2o(sections, rva):
    for va, span, rp in sections:
        if va <= rva < va + span:
            return rp + (rva - va)
    return None


def exe_icon_sizes(path):
    data = Path(path).read_bytes()
    rsrc_rva, sections = _sections(data)
    if not rsrc_rva:
        return []
    root = _r2o(sections, rsrc_rva)
    if root is None:
        return []

    def walk(off):
        nn, ni = struct.unpack_from('<HH', data, off + 12)
        found = []
        for i in range(nn + ni):
            name, nxt = struct.unpack_from('<II', data, off + 16 + i * 8)
            if nxt & 0x80000000:
                found += walk(_r2o(sections, rsrc_rva + (nxt & 0x7FFFFFFF)))
            else:
                leaf = _r2o(sections, rsrc_rva + nxt)
                data_rva, size = struct.unpack_from('<II', data, leaf)
                found.append((name, size, _r2o(sections, data_rva)))
        return found

    # Top level: type id. 14 is RT_GROUP_ICON.
    nn, ni = struct.unpack_from('<HH', data, root + 12)
    sizes = []
    for i in range(nn + ni):
        name, nxt = struct.unpack_from('<II', data, root + 16 + i * 8)
        if name != 14 or not (nxt & 0x80000000):
            continue
        for _ident, size, blob in walk(_r2o(sections, rsrc_rva + (nxt & 0x7FFFFFFF))):
            group = data[blob:blob + size]
            count = struct.unpack_from('<H', group, 4)[0]
            for n in range(count):
                w, h = group[6 + n * 14], group[7 + n * 14]
                sizes.append((w or 256, h or 256))
    return sizes


def require_sizes(label, sizes):
    missing = [s for s in REQUIRED if (s, s) not in sizes]
    if missing:
        raise SystemExit(f'{label} icon missing sizes {missing}; has {sizes}')
    print(f'{label}: {sizes}')


def check_exe(exe):
    require_sizes(str(exe), exe_icon_sizes(exe))


def check_ico(path):
    require_sizes(str(path), ico_sizes(path))


def check_linux_tree(root):
    """Check a staged Linux tree. AppImage and deb are optional layouts."""
    root = Path(root)
    if not list(root.rglob('.DirIcon')):
        raise SystemExit(f'{root} is missing .DirIcon')
    desktop_files = list(root.rglob('*.desktop'))
    if not desktop_files:
        raise SystemExit(f'{root} has no .desktop entry, so a file manager cannot show the product icon')
    for desktop in desktop_files:
        icon = None
        for line in desktop.read_text(encoding='utf-8').splitlines():
            if line.startswith('Icon='):
                icon = line.split('=', 1)[1].strip()
        if not icon:
            raise SystemExit(f'{desktop} has no Icon=')
        if icon.startswith('/') or icon.startswith('.'):
            candidate = (desktop.parent / icon).resolve() if icon.startswith('.') else Path(icon)
            if not candidate.is_file():
                raise SystemExit(f'{desktop} Icon={icon} does not exist')
        else:
            # Theme name. The staged hicolor tree must contain it before install.
            hits = list(root.rglob(f'hicolor/*/apps/{icon}.png'))
            if not hits:
                raise SystemExit(f'{desktop} Icon={icon} is not in the staged hicolor tree')
            have = {p.parent.parent.name for p in hits}
            missing = [f'{s}x{s}' for s in REQUIRED if f'{s}x{s}' not in have]
            if missing:
                raise SystemExit(f'hicolor missing {missing}')
        print(f'{desktop.name}: Icon={icon}')
    appimage = list(root.rglob('.DirIcon'))
    for marker in root.rglob('AppImage'):
        pass
    if (root / '.DirIcon').is_file() or any(p.name.endswith('.AppImage') for p in root.rglob('*')):
        if not (root / '.DirIcon').is_file():
            raise SystemExit('AppImage is missing .DirIcon')
    print('linux icon check ok')


def main(argv):
    if len(argv) < 3:
        raise SystemExit('usage: check_icons.py ico|exe|linux <path>')
    kind, path = argv[1], Path(argv[2])
    if kind == 'ico':
        check_ico(path)
    elif kind == 'exe':
        check_exe(path)
    elif kind == 'linux':
        check_linux_tree(path)
    else:
        raise SystemExit('unknown kind ' + kind)


if __name__ == '__main__':
    main(sys.argv)
