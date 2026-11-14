"""Display size for a picture, in points.

Stated size wins (docx extent, HTML width/height or style, RTF picwgoal
and picscalex). Otherwise pixels convert at the image DPI, or 96.
EMF and placeable WMF use the physical size in the header.
A picture is scaled down only when it is wider than the limit.
"""

import struct

A4_WIDTH_TWIP = 11906
DEFAULT_MARGIN_TWIP = 1440
_PT_PER_IN = 72.0
_DEFAULT_DPI = 96.0


def content_width_pt(page_twip=A4_WIDTH_TWIP, left_twip=DEFAULT_MARGIN_TWIP, right_twip=DEFAULT_MARGIN_TWIP):
    return (float(page_twip) - float(left_twip) - float(right_twip)) / 20.0


def num(value):
    number = float(value)
    if number == int(number):
        return int(number)
    return round(number, 2)


def fit_points(width, height, limit):
    width = float(width or 0)
    height = float(height or 0)
    limit = float(limit or 0)
    if width <= 0 or height <= 0 or limit <= 0 or width <= limit:
        return num(width), num(height)
    scale = limit / width
    return num(limit), num(height * scale)


def display_size(blob, stated_w=None, stated_h=None, scale_x=None, scale_y=None, limit_pt=None):
    """Return the point size to store and to write into docx."""
    sx = 1.0 if scale_x is None else float(scale_x) / 100.0
    sy = 1.0 if scale_y is None else float(scale_y) / 100.0
    width = float(stated_w or 0) * sx
    height = float(stated_h or 0) * sy
    if width <= 0 or height <= 0:
        native_w, native_h = _native_points(blob or b"")
        if width <= 0 and native_w:
            width = native_w * (sx if scale_x is not None else 1.0)
        if height <= 0 and native_h:
            height = native_h * (sy if scale_y is not None else 1.0)
    if width <= 0:
        width = 72
    if height <= 0:
        height = 72
    width, height = fit_points(width, height, content_width_pt())
    if limit_pt:
        width, height = fit_points(width, height, limit_pt)
    return width, height


def html_box(width_attr, height_attr, style):
    """HTML width/height or the matching CSS length, in points. 0 means absent."""
    styled_w, styled_h = _style_box(style or "")
    return styled_w or _attr_length(width_attr), styled_h or _attr_length(height_attr)


def _native_points(blob):
    vector = _vector_points(blob)
    if vector:
        return vector
    pixels = _pixel_size(blob)
    if not pixels:
        return 0, 0
    px_w, px_h, dpi_x, dpi_y = pixels
    return _px_to_pt(px_w, dpi_x), _px_to_pt(px_h, dpi_y)


def _px_to_pt(pixels, dpi):
    if not pixels:
        return 0
    return float(pixels) * _PT_PER_IN / float(dpi or _DEFAULT_DPI)


def _vector_points(blob):
    if len(blob) >= 40 and struct.unpack_from("<I", blob, 0)[0] == 1:
        size = struct.unpack_from("<I", blob, 4)[0]
        if size >= 88:
            left, _top, right, bottom = struct.unpack_from("<iiii", blob, 24)
            if right > left and bottom > _top:
                return (right - left) / 100.0 / 25.4 * _PT_PER_IN, (bottom - _top) / 100.0 / 25.4 * _PT_PER_IN
    if blob[:4] == b"\xd7\xcd\xc6\x9a" and len(blob) >= 22:
        left, top, right, bottom, inch = struct.unpack_from("<hhhhH", blob, 6)
        inch = inch or 1440
        if right > left and bottom > top:
            return (right - left) / float(inch) * _PT_PER_IN, (bottom - top) / float(inch) * _PT_PER_IN
    return None


def _pixel_size(blob):
    png = _png(blob)
    if png:
        return png
    jpeg = _jpeg(blob)
    if jpeg:
        return jpeg
    gif = _gif(blob)
    if gif:
        return gif
    bmp = _bmp(blob)
    if bmp:
        return bmp
    return None


def _png(blob):
    if not blob.startswith(b"\x89PNG\r\n\x1a\n") or len(blob) < 24:
        return None
    px_w, px_h = struct.unpack(">II", blob[16:24])
    dpi_x = dpi_y = _DEFAULT_DPI
    offset = 8
    while offset + 12 <= len(blob):
        length = struct.unpack(">I", blob[offset:offset + 4])[0]
        kind = blob[offset + 4:offset + 8]
        if kind == b"pHYs" and length >= 9 and offset + 8 + length <= len(blob):
            ppm_x, ppm_y, unit = struct.unpack(">IIB", blob[offset + 8:offset + 17])
            if unit == 1:
                if ppm_x:
                    dpi_x = ppm_x * 0.0254
                if ppm_y:
                    dpi_y = ppm_y * 0.0254
            break
        if kind == b"IEND":
            break
        offset += 12 + length
    return px_w, px_h, dpi_x, dpi_y


def _jpeg(blob):
    if not blob.startswith(b"\xff\xd8"):
        return None
    dpi_x = dpi_y = _DEFAULT_DPI
    width = height = 0
    index = 2
    while index + 4 < len(blob):
        if blob[index] != 0xFF:
            break
        while index < len(blob) and blob[index] == 0xFF:
            index += 1
        if index >= len(blob):
            break
        marker = blob[index]
        index += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(blob):
            break
        segment = int.from_bytes(blob[index:index + 2], "big")
        body = blob[index + 2:index + segment]
        if marker == 0xE0 and body.startswith(b"JFIF") and len(body) >= 12:
            unit = body[7]
            xd = int.from_bytes(body[8:10], "big")
            yd = int.from_bytes(body[10:12], "big")
            if unit == 1 and xd and yd:
                dpi_x, dpi_y = xd, yd
            elif unit == 2 and xd and yd:
                dpi_x, dpi_y = xd * 2.54, yd * 2.54
        if marker in (0xC0, 0xC1, 0xC2) and len(body) >= 6:
            height = int.from_bytes(body[1:3], "big")
            width = int.from_bytes(body[3:5], "big")
            break
        index += segment
    if not width or not height:
        return None
    return width, height, dpi_x, dpi_y


def _gif(blob):
    if not (blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a")) or len(blob) < 10:
        return None
    px_w, px_h = struct.unpack("<HH", blob[6:10])
    return px_w, px_h, _DEFAULT_DPI, _DEFAULT_DPI


def _bmp(blob):
    if not blob.startswith(b"BM") or len(blob) < 26:
        return None
    px_w = struct.unpack_from("<i", blob, 18)[0]
    px_h = abs(struct.unpack_from("<i", blob, 22)[0])
    dpi_x = dpi_y = _DEFAULT_DPI
    if len(blob) >= 46:
        ppm_x = struct.unpack_from("<i", blob, 38)[0]
        ppm_y = struct.unpack_from("<i", blob, 42)[0]
        if ppm_x > 0:
            dpi_x = ppm_x * 0.0254
        if ppm_y > 0:
            dpi_y = ppm_y * 0.0254
    if px_w <= 0 or px_h <= 0:
        return None
    return px_w, px_h, dpi_x, dpi_y


def _style_box(style):
    width = height = 0
    for part in style.split(";"):
        name, _, value = part.partition(":")
        key = name.strip().lower()
        if key == "width":
            width = _css_length(value.strip())
        elif key == "height":
            height = _css_length(value.strip())
    return width, height


def _attr_length(value):
    if value is None:
        return 0
    return _css_length(str(value).strip())


def _css_length(value):
    text = value.strip().lower()
    if not text:
        return 0
    if text.endswith("%"):
        try:
            return content_width_pt() * float(text[:-1]) / 100.0
        except ValueError:
            return 0
    for suffix, scale in (("pt", 1.0), ("px", _PT_PER_IN / _DEFAULT_DPI), ("in", _PT_PER_IN), ("cm", _PT_PER_IN / 2.54), ("mm", _PT_PER_IN / 25.4)):
        if text.endswith(suffix):
            try:
                return float(text[:-len(suffix)]) * scale
            except ValueError:
                return 0
    try:
        return float(text) * _PT_PER_IN / _DEFAULT_DPI
    except ValueError:
        return 0

