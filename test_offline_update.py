"""Verify cumulative upgrades, data preservation and rollback."""
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent/'launcher'))
from offline_update import MARKER, apply
from package_update import PortableZipInfo, build, open_zip


class OfflineUpgradeTests(unittest.TestCase):
    def test_skip_release_rollback_and_platform(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            archives = home/'archives'
            archives.mkdir()
            stem = '文矩/'
            for v, changed in [('3.4.5', False), ('3.4.6', True), ('3.5.0', False)]:
                with zipfile.ZipFile(archives/f'WenJu_{v}_Windows_x64_Portable.zip', 'w') as z:
                    z.writestr(stem+'Main.qml', f'text:"{v}  / 文档"')
                    z.writestr(stem+'runtime/python.exe', b'changed' if changed else b'original')
                    z.writestr(stem+'runtime/large.dll', b'x' * 12345)
                    z.writestr(stem+'app.py', v)
                    if changed:
                        z.writestr(stem+'obsolete.py', b'delete')
            pack = build(archives, home, 'windows-x64', '3.5.0', ['3.4.5','3.4.6'])
            with open_zip(pack, metadata_encoding='gbk') as z:
                z.extractall(home/'patch')
            payload = home/'patch/update/update.zip'
            with zipfile.ZipFile(payload) as z:
                self.assertNotIn('payload/' + hashlib.sha256(b'x' * 12345).hexdigest(), z.namelist())
            for old in ('3.4.5','3.4.6'):
                root = home/old
                with zipfile.ZipFile(archives/f'WenJu_{old}_Windows_x64_Portable.zip') as z:
                    z.extractall(root)
                app = root/'文矩'
                data = app/'工作数据'
                data.mkdir()
                (data/'自定义模板.txt').write_bytes(b'keep')
                original = (app/'Main.qml').read_bytes()
                if old == '3.4.5':
                    with patch('offline_update.product_platform', return_value='win7-x64'):
                        with self.assertRaisesRegex(ValueError, '架构'):
                            apply(root, payload)
                    import offline_update
                    replace = offline_update.os.replace

                    def broken(source, target):
                        if Path(source) == root/MARKER/'stage/文矩/app.py':
                            raise OSError('simulated I/O failure')
                        return replace(source, target)

                    with patch('offline_update.os.replace', side_effect=broken):
                        with self.assertRaisesRegex(OSError, 'simulated'):
                            apply(root, payload)
                    self.assertEqual((app/'Main.qml').read_bytes(), original)
                    self.assertEqual((app/'app.py').read_text(), old)
                    self.assertFalse((root/MARKER).exists())
                self.assertEqual(apply(root, payload)[:2], (old, '3.5.0'))
                self.assertEqual((app/'runtime/python.exe').read_bytes(), b'original')
                self.assertFalse((app/'obsolete.py').exists())
                self.assertEqual((data/'自定义模板.txt').read_bytes(), b'keep')


class LegacyZipTests(unittest.TestCase):
    def test_gbk_names_roundtrip_without_python_311(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'names.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                info = PortableZipInfo('文矩/Main.qml')
                archive.writestr(info, b'ok')
            with open_zip(path, metadata_encoding='gbk') as archive:
                self.assertEqual(archive.read('文矩/Main.qml'), b'ok')
                archive.extractall(Path(d) / 'out')
            self.assertEqual((Path(d) / 'out' / '文矩' / 'Main.qml').read_bytes(), b'ok')


class DeterministicTarTests(unittest.TestCase):
    def test_kylin_gzip_mtime_does_not_change_digest(self):
        import hashlib, io, time
        from package_release import deterministic_tar_gz
        def digest(path):
            with deterministic_tar_gz(path) as tar:
                info = __import__('tarfile').TarInfo('文矩/runtime/bin/python3')
                info.type = __import__('tarfile').SYMTYPE
                info.linkname = 'python3.11'
                info.mtime = 1700000000
                info.mode = 0o777
                tar.addfile(info)
            return hashlib.sha256(Path(path).read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            first = digest(Path(d)/'a.tar.gz')
            time.sleep(2)
            second = digest(Path(d)/'b.tar.gz')
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
