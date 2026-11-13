"""Rasterize the brand mark into the icon sizes the packages must ship.

Source of truth is core/素材/文矩_图标.svg. The Windows ico and the Linux
hicolor PNGs are generated from it so the exe resource, the window icon and
the file-manager icon are the same drawing.
"""
from pathlib import Path
import subprocess, sys

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / 'core' / '素材' / '文矩_图标.svg'
ICO = ROOT / 'launcher' / 'WenJu.ico'
HICOLOR = ROOT / 'launcher' / 'icons' / 'hicolor'
# 24 is used by Explorer's content view. 64/128/512 are for Linux hicolor.
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 256)


def render(size, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([
        'rsvg-convert', '-w', str(size), '-h', str(size), '-o', str(dest), str(SVG),
    ])


def build():
    from PIL import Image
    pngs = []
    for size in SIZES:
        dest = HICOLOR / f'{size}x{size}' / 'apps' / 'wenju.png'
        render(size, dest)
        pngs.append((size, dest))
    images = []
    for size in ICO_SIZES:
        images.append(Image.open(HICOLOR / f'{size}x{size}' / 'apps' / 'wenju.png').convert('RGBA'))
    images[0].save(ICO, format='ICO', sizes=[(s, s) for s in ICO_SIZES], append_images=images[1:])
    # Pillow's ICO writer can drop sizes. Rewrite the directory ourselves if needed.
    _write_ico(ICO, images)
    print(ICO, 'sizes', ICO_SIZES)


def _write_ico(path, images):
    """Write a PNG-compressed ICO so every requested size is really present."""
    import struct
    blobs = []
    for im in images:
        buf = __import__('io').BytesIO()
        im.save(buf, format='PNG')
        blobs.append(buf.getvalue())
    count = len(blobs)
    header = struct.pack('<HHH', 0, 1, count)
    offset = 6 + 16 * count
    entries = b''
    body = b''
    for im, blob in zip(images, blobs):
        w = 0 if im.width == 256 else im.width
        h = 0 if im.height == 256 else im.height
        entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        body += blob
    path.write_bytes(header + entries + body)


if __name__ == '__main__':
    if not SVG.is_file():
        sys.exit('missing ' + str(SVG))
    build()
