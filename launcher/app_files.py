"""App files that must sit next to the runtime.

The set comes from the repo: root modules and QML, plus everything under ui/.
A hand-kept list dropped new files and the package still built. This check
fails when app.py imports a local module, or Main.qml uses a QML type, that
the set does not contain.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
TEXT_FILES = (
    '使用说明.txt', 'README.md', 'requirements-windows.txt', '可选字体/README.txt',
)
_MOD = re.compile(r'(?m)^[ \t]*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)\b')
_QML_USE = re.compile(r'\b([A-Z][A-Za-z0-9_]*)\s*\{')
_QML_DEF = re.compile(r'\bcomponent\s+([A-Z][A-Za-z0-9_]*)')
_QML_IMPORT = re.compile(r'import\s+"([^"]+)"')


def names(root=ROOT):
    """Relative paths copied beside the runtime, excluding tests."""
    root = Path(root)
    found = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        if path.suffix == '.py' and path.name.startswith('test_'):
            continue
        if path.suffix in ('.py', '.qml'):
            found.append(path.name)
    ui = root / 'ui'
    if ui.is_dir():
        for path in sorted(ui.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                found.append(path.relative_to(root).as_posix())
    for name in TEXT_FILES:
        if (root / name).is_file():
            found.append(name)
    return tuple(found)


def required(root=ROOT):
    """Local modules app.py imports, and QML types Main.qml can load."""
    root = Path(root)
    needed = []
    app = (root / 'app.py').read_text(encoding='utf-8')
    for name in sorted(set(_MOD.findall(app))):
        rel = name + '.py'
        if (root / rel).is_file():
            needed.append(rel)
        elif (root / 'core' / rel).is_file():
            needed.append('core/' + rel)
    main = (root / 'Main.qml').read_text(encoding='utf-8')
    defined = set(_QML_DEF.findall(main))
    used = set(_QML_USE.findall(main)) - defined
    folders = [root]
    for rel in _QML_IMPORT.findall(main):
        folders.append(root / rel)
    stems = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob('*.qml')):
            stems.setdefault(path.stem, path.relative_to(root).as_posix())
    for name in sorted(used):
        if name in stems:
            needed.append(stems[name])
    for rel in _QML_IMPORT.findall(main):
        folder = root / rel
        if not folder.is_dir():
            continue
        qmldir = folder / 'qmldir'
        if qmldir.is_file():
            needed.append(qmldir.relative_to(root).as_posix())
        for path in sorted(folder.glob('*.qml')):
            needed.append(path.relative_to(root).as_posix())
    seen = set()
    unique = []
    for item in needed:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return tuple(unique)


def gaps(root=ROOT):
    """Required files the copy set would leave out. core/ is copied as a tree."""
    payload = set(names(root))
    missing = []
    for rel in required(root):
        if rel in payload or rel.startswith('core/'):
            continue
        missing.append(rel)
    return missing


def require_tree(root=ROOT, stage=None):
    missing = list(gaps(root))
    if stage is not None:
        stage = Path(stage)
        for rel in list(required(root)) + list(names(root)):
            if not (stage / rel).is_file():
                missing.append(rel)
    missing = sorted(set(missing))
    if missing:
        raise SystemExit('portable package is missing: ' + ', '.join(missing))
    return missing


if __name__ == '__main__':
    require_tree(ROOT)
    print('PASS: package file set includes app.py imports and Main.qml types')
    sys.exit(0)
