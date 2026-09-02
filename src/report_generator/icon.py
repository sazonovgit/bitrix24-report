"""Простая иконка приложения (ICO 32×32)."""

from __future__ import annotations

import struct
from pathlib import Path


def write_app_icon(path: Path) -> Path:
    """Пишет синий квадрат 32×32 с белой полосой — без сторонних библиотек."""
    size = 32
    pixels = bytearray()
    for y in range(size):
        for x in range(size):
            if 6 <= x <= 25 and 13 <= y <= 18:
                pixels.extend(b"\xff\xff\xff\xff")
            else:
                pixels.extend(b"\x79\x4e\x1f\xff")

    dib = struct.pack(
        "<IiiHHIIiiII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )
    xor = bytes(pixels)
    and_mask = b"\x00" * (size * 4)
    image = dib + xor + and_mask

    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        size,
        size,
        0,
        0,
        1,
        32,
        len(image),
        6 + 16,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entry + image)
    return path
