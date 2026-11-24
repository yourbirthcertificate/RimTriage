"""Builds assets/RimWorldModApplier.ico and assets/icon.png from the drawing in modapplier/appicon.py.

Run:  python make_icon.py            (writes the files)
      python make_icon.py --preview  (also writes a contact sheet to assets/icon-preview.png)"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

from modapplier import appicon

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets"


def png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def write_ico(path, sizes):
    """ICO container with one PNG-compressed image per size (supported by Windows Vista and later)."""
    images = [(s, png_bytes(appicon.make_image(s))) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    Path(path).write_bytes(head + entries + blobs)


def preview(path):
    """Contact sheet: every size on dark and light backgrounds."""
    sizes = (16, 24, 32, 48, 64, 128, 256)
    W = sum(s + 24 for s in sizes) + 24
    sheet = QImage(W, 2 * 300 + 20, QImage.Format_ARGB32)
    p = QPainter(sheet)
    for row, bg in enumerate(("#101216", "#f2f3f6")):
        p.fillRect(0, row * 310, W, 310, QColor(bg))
        x = 24
        for s in sizes:
            p.drawImage(x, row * 310 + 20 + (256 - s) // 2, appicon.make_image(s))
            x += s + 24
    p.end()
    sheet.save(str(path))


if __name__ == "__main__":
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    OUT.mkdir(exist_ok=True)
    write_ico(OUT / "RimWorldModApplier.ico", appicon.SIZES)
    appicon.make_image(512).save(str(OUT / "icon.png"))
    if "--preview" in sys.argv:
        preview(OUT / "icon-preview.png")
    print("wrote", sorted(f.name for f in OUT.iterdir()))
