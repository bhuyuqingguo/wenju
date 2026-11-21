"""Verified OFL fonts shared between online downloads and portable packs."""
import hashlib
import os
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SOURCE = 'https://raw.githubusercontent.com/notofonts/noto-cjk/'
FAMILIES = {'sans': 'Noto Sans CJK SC', 'serif': 'Noto Serif CJK SC'}
FILES = {
    'sans': ('Sans2.004', {
        'NotoSansCJKsc-Regular.otf': ('Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf', 16437364, '2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b'),
        'NotoSansCJKsc-Bold.otf': ('Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf', 17002248, 'b5f0d1a190a7f9b43c310a8850630af12553df32c4c050543f9059732d9b4c0a'),
        'OFL.txt': ('LICENSE', 4301, '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2'),
    }),
    'serif': ('Serif2.003', {
        'NotoSerifCJKsc-Regular.otf': ('Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Regular.otf', 24543080, '2a2eae2628df83556c54018c41e20fa532c1b862c5256ae8b3f23feb918d12ca'),
        'NotoSerifCJKsc-Bold.otf': ('Serif/OTF/SimplifiedChinese/NotoSerifCJKsc-Bold.otf', 25521460, '8af07d4b6c2e82bcc72a30e066eaf295f11b9424f4aad2eaa9fe0e9c3b38fc73'),
        'OFL.txt': ('Serif/LICENSE', 4301, '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2'),
    }),
}
MARKER = b'WenJu OFL Font Pack 1\n'
_CHUNK = 256 * 1024


def font_group(name):
    key = name.casefold().replace(' ', '')
    if any(x in key for x in ('黑', '雅黑', 'simhei', 'yahei', 'heiti', 'sans', 'arial', 'calibri', 'aptos', 'tahoma', 'verdana')):
        return 'sans'
    if any(x in key for x in ('宋', 'simsun', 'fangsong', 'stsong', 'xiaobiaosong', 'serif', 'timesnewroman', 'cambria', 'georgia')):
        return 'serif'
    return ''


def storage(data):
    return Path(data) / '开源字体'


def files_on_disk(root, group):
    folder = root / group
    return all((folder / name).is_file() and (folder / name).stat().st_size == size
               for name, (_, size, _) in FILES[group][1].items())


def _verify(stream, target, size, sha, cancelled):
    with target.open('wb') as out:
        _verify_existing(stream, out, size, sha, cancelled, target.name)


def _save(root, group, source, cancelled):
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.wenju-font-', dir=str(root.parent)) as tmp:
        incoming = Path(tmp)
        for name, (path, size, sha) in FILES[group][1].items():
            with source(name, path) as stream:
                _verify(stream, incoming / name, size, sha, cancelled)
        dest = root / group
        dest.mkdir(exist_ok=True)
        for name in FILES[group][1]:
            os.replace(incoming / name, dest / name)


def download(root, groups, cancelled):
    deadline = time.monotonic() + 480
    for group in groups:
        if files_on_disk(root, group):
            continue
        tag = FILES[group][0]
        def source(_name, path):
            return urllib.request.urlopen(SOURCE + tag + '/' + path, timeout=10)
        try:
            _save(root, group, source, lambda: cancelled() or time.monotonic() >= deadline)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValueError('无法连接官方字体源。可稍后重试，或从联网电脑导出字体包后离线导入。') from exc


def export_pack(root, destination, cancelled):
    groups = [g for g in FILES if files_on_disk(root, g)]
    if not groups:
        raise ValueError('还没有可导出的开源字体。')
    destination = Path(destination)
    fd, name = tempfile.mkstemp(prefix='.wenju-font-', dir=str(destination.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(name, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('WenJu-Font-Pack.txt', MARKER)
            for group in groups:
                for filename, (_, size, sha) in FILES[group][1].items():
                    with (root / group / filename).open('rb') as stream, archive.open(group + '/' + filename, 'w') as output:
                        _verify_existing(stream, output, size, sha, cancelled)
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _verify_existing(stream, output, size, sha, cancelled, name=''):
    digest = hashlib.sha256()
    left = size
    while left:
        if cancelled():
            raise InterruptedError('已取消字体操作。')
        chunk = stream.read(min(left, _CHUNK))
        if not chunk:
            break
        left -= len(chunk)
        digest.update(chunk)
        if output is not None:
            output.write(chunk)
    if left or stream.read(1) or digest.hexdigest() != sha:
        raise ValueError('字体文件与官方版本校验不符：' + name)


def verify_local(path, group):
    _, size, sha = FILES[group][1][path.name]
    with path.open('rb') as stream:
        _verify_existing(stream, None, size, sha, lambda: False, path.name)


def import_pack(root, source, cancelled):
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        if len(members) > 1 + sum(len(spec[1]) for spec in FILES.values()):
            raise ValueError('字体包包含多余文件。')
        by_name = {item.filename: item for item in members}
        marker = by_name.pop('WenJu-Font-Pack.txt', None)
        if (not marker or marker.file_size != len(MARKER) or len(by_name) + 1 != len(members)
                or archive.read(marker) != MARKER):
            raise ValueError('请选择从文矩导出的字体包 ZIP。')
        remaining = set(by_name)
        groups = []
        for group, (_, entries) in FILES.items():
            expected = {group+'/'+name: size for name, (_, size, _) in entries.items()}
            if expected.keys() & remaining:
                if any(name not in by_name or by_name[name].file_size != size for name, size in expected.items()):
                    raise ValueError('字体包内的字体或许可证不完整。')
                remaining.difference_update(expected)
                groups.append(group)
        if remaining or not groups:
            raise ValueError('字体包内含有无法识别的文件。')
        with tempfile.TemporaryDirectory(prefix='wenju-font-') as temp:
            staging = Path(temp)
            for group in groups:
                _save(staging, group, lambda name, _path: archive.open(group + '/' + name), cancelled)
            for group in groups:
                if files_on_disk(root, group):
                    continue
                _save(root, group, lambda name, _path: (staging / group / name).open('rb'), cancelled)

