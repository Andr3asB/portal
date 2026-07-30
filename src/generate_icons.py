"""
Erstellt PWA-Icons und Favicon für das Familienportal (kein Pillow nötig).

Motiv: weiße "16" auf Marken-Blau – Anspielung auf die Hausnummer
(Schwabenstr. 16), siehe Wunsch #12. Die Ziffern sind ein handgeschriebenes
5x7-Pixelraster, das per Nearest-Neighbor auf jede Icon-Größe skaliert wird.
"""
import struct, zlib, os

os.makedirs("static", exist_ok=True)

BLAU  = (74, 144, 217)   # Marken-Blau, Default von --farbe in base.html
WEISS = (255, 255, 255)

DIGIT_1 = [
    "00100",
    "01100",
    "00100",
    "00100",
    "00100",
    "00100",
    "01110",
]
DIGIT_6 = [
    "00111",
    "01000",
    "10000",
    "11110",
    "10001",
    "10001",
    "01110",
]

GRID   = [DIGIT_1[r] + "0" + DIGIT_6[r] for r in range(7)]  # "1" + Lücke + "6"
GRID_W = len(GRID[0])
GRID_H = len(GRID)


def make_png(size, cell):
    """size x size-PNG: blauer Hintergrund, zentrierte weiße '16' (Zellgröße `cell`)."""
    off_x = (size - GRID_W * cell) // 2
    off_y = (size - GRID_H * cell) // 2

    def pixel_color(x, y):
        gx, gy = (x - off_x) // cell, (y - off_y) // cell
        if 0 <= gx < GRID_W and 0 <= gy < GRID_H and GRID[gy][gx] == "1":
            return WEISS
        return BLAU

    raw = bytearray()
    for y in range(size):
        raw.append(0)  # Filter-Byte "None"
        for x in range(size):
            raw.extend(pixel_color(x, y))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


# (Dateiname, Icon-Größe, Zellgröße) – Zellgröße = Größe/16, damit das 11x7-Raster
# bei jeder Auflösung sauber zentriert und proportional bleibt.
ICONS = [
    ("static/icon-512.png",    512, 32),
    ("static/icon-192.png",    192, 12),
    ("static/favicon-32.png",   32,  2),
    ("static/favicon-16.png",   16,  1),
]

for fname, size, cell in ICONS:
    with open(fname, "wb") as f:
        f.write(make_png(size, cell))

print("Icons erstellt.")
