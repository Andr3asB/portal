"""Erstellt einfache PNG-Icons für das PWA-Manifest (kein Pillow nötig)."""
import struct, zlib, os

os.makedirs("static", exist_ok=True)


def solid_png(w, h, r, g, b):
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes([r, g, b]) * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 1))
        + chunk(b"IEND", b"")
    )


for size in [192, 512]:
    with open(f"static/icon-{size}.png", "wb") as f:
        f.write(solid_png(size, size, 74, 144, 217))

print("Icons erstellt.")
