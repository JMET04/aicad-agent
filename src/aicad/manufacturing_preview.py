from __future__ import annotations

import math
import re
import zlib
import xml.etree.ElementTree as ET
from typing import Any


_GRAPHICS = {"path", "line", "polyline", "polygon", "circle", "ellipse", "rect"}
_BLOCKED = re.compile(
    r"(?i)\b(?:todo|tbd|placeholder|dummy|generic[- ]?(?:preview|drawing|model))\b"
)


def probe_svg(data: bytes) -> tuple[bool, str, str | None]:
    """Parse a real SVG and return its root-bound source SHA declaration."""
    try:
        source = data.decode("utf-8-sig")
    except UnicodeError:
        return False, "SVG preview is not valid UTF-8", None
    lowered = source.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return False, "SVG preview may not contain a DTD or entity declaration", None
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return False, "SVG preview is not well-formed XML", None
    root_name = root.tag.rsplit("}", 1)[-1].casefold() if isinstance(root.tag, str) else ""
    if root_name != "svg":
        return False, "SVG preview root element is not svg", None
    if "viewBox" not in root.attrib and not ({"width", "height"} <= set(root.attrib)):
        return False, "SVG preview root lacks a viewport", None
    geometry_count = 0
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1].casefold() if isinstance(element.tag, str) else ""
        if name == "script":
            return False, "SVG preview contains script", None
        if name in _GRAPHICS:
            geometry_count += 1
    text = " ".join(value for value in root.itertext() if isinstance(value, str))
    if geometry_count < 2 or _BLOCKED.search(text):
        return False, "SVG preview lacks real graphic inventory or contains placeholder text", None
    source_sha = root.attrib.get("data-aicad-source-sha256")
    return True, "", source_sha


def _png_text(chunks: list[tuple[bytes, bytes]]) -> dict[str, list[str]]:
    metadata: dict[str, list[str]] = {}
    for kind, payload in chunks:
        if kind == b"tEXt":
            if b"\x00" not in payload:
                continue
            keyword, value = payload.split(b"\x00", 1)
            try:
                key_text = keyword.decode("latin-1")
                value_text = value.decode("latin-1")
            except UnicodeError:
                continue
            metadata.setdefault(key_text, []).append(value_text)
        elif kind == b"iTXt":
            if b"\x00" not in payload:
                continue
            keyword, remainder = payload.split(b"\x00", 1)
            if len(remainder) < 2:
                continue
            compression_flag, compression_method = remainder[0], remainder[1]
            remainder = remainder[2:]
            try:
                language, translated, value = remainder.split(b"\x00", 2)
                del language, translated
                if compression_flag == 1:
                    if compression_method != 0:
                        continue
                    value = zlib.decompress(value)
                elif compression_flag != 0:
                    continue
                key_text = keyword.decode("latin-1")
                value_text = value.decode("utf-8")
            except (ValueError, UnicodeError, zlib.error):
                continue
            metadata.setdefault(key_text, []).append(value_text)
    return metadata


def probe_png(data: bytes) -> tuple[bool, str, dict[str, list[str]]]:
    """Validate PNG structure, CRCs, meaningful pixels and structured text metadata."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False, "PNG signature is missing", {}
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    saw_iend = False
    try:
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset + 4], "big")
            kind = data[offset + 4:offset + 8]
            end = offset + 12 + length
            if length > 64 * 1024 * 1024 or end > len(data):
                raise ValueError("truncated or oversized chunk")
            payload = data[offset + 8:offset + 8 + length]
            declared_crc = int.from_bytes(data[offset + 8 + length:end], "big")
            actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
            if declared_crc != actual_crc:
                raise ValueError("chunk CRC mismatch")
            chunks.append((kind, payload))
            offset = end
            if kind == b"IEND":
                if length != 0 or offset != len(data):
                    raise ValueError("IEND is invalid or has trailing bytes")
                saw_iend = True
                break
        if not saw_iend or not chunks or chunks[0][0] != b"IHDR":
            raise ValueError("IHDR/IEND structure")
        if sum(1 for kind, _ in chunks if kind == b"IHDR") != 1:
            raise ValueError("duplicate IHDR")
        ihdr = chunks[0][1]
        if len(ihdr) != 13:
            raise ValueError("IHDR size")
        width = int.from_bytes(ihdr[0:4], "big")
        height = int.from_bytes(ihdr[4:8], "big")
        bit_depth, color_type, compression, filtering, interlace = (
            ihdr[8], ihdr[9], ihdr[10], ihdr[11], ihdr[12]
        )
        channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
        if (
            width < 96
            or height < 72
            or width * height > 20_000_000
            or bit_depth != 8
            or compression != 0
            or filtering != 0
            or interlace != 0
        ):
            raise ValueError("unsupported dimensions or encoding")
        idat = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
        if not idat:
            raise ValueError("IDAT missing")
        raw = zlib.decompress(idat)
        stride = width * channels
        if len(raw) != height * (stride + 1):
            raise ValueError("scanline size")
        previous = bytearray(stride)
        stats: dict[bytes, list[int]] = {}
        cursor = 0
        for y in range(height):
            filter_type = raw[cursor]
            encoded = raw[cursor + 1:cursor + 1 + stride]
            cursor += stride + 1
            row = bytearray(stride)
            for index, byte in enumerate(encoded):
                left = row[index - channels] if index >= channels else 0
                up = previous[index]
                upper_left = previous[index - channels] if index >= channels else 0
                if filter_type == 0:
                    predictor = 0
                elif filter_type == 1:
                    predictor = left
                elif filter_type == 2:
                    predictor = up
                elif filter_type == 3:
                    predictor = (left + up) // 2
                elif filter_type == 4:
                    p = left + up - upper_left
                    distances = (abs(p - left), abs(p - up), abs(p - upper_left))
                    predictor = (left, up, upper_left)[distances.index(min(distances))]
                else:
                    raise ValueError("unknown scanline filter")
                row[index] = (byte + predictor) & 255
            for x, start in enumerate(range(0, stride, channels)):
                pixel = bytes(row[start:start + channels])
                value = stats.setdefault(pixel, [0, x, x, y, y])
                value[0] += 1
                value[1] = min(value[1], x)
                value[2] = max(value[2], x)
                value[3] = min(value[3], y)
                value[4] = max(value[4], y)
            previous = row
        if len(stats) < 2:
            raise ValueError("solid image")
        dominant = max(stats, key=lambda pixel: stats[pixel][0])
        total = width * height
        non_dominant = total - stats[dominant][0]
        if non_dominant < max(8, math.ceil(total * 0.005)):
            raise ValueError("non-dominant pixel area is too small")
        secondary = [value for pixel, value in stats.items() if pixel != dominant]
        min_x = min(value[1] for value in secondary)
        max_x = max(value[2] for value in secondary)
        min_y = min(value[3] for value in secondary)
        max_y = max(value[4] for value in secondary)
        if (max_x - min_x + 1) < math.ceil(width * 0.20) or (max_y - min_y + 1) < math.ceil(height * 0.20):
            raise ValueError("non-dominant content has insufficient sheet span")
    except (KeyError, ValueError, zlib.error):
        return False, "PNG must have valid CRC/chunk closure and non-trivial content spanning at least 20% of both axes", {}
    return True, "", _png_text(chunks)
