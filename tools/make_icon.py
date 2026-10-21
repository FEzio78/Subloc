"""Write the logo as icon files: subloc/assets/icon.ico (Windows: the .exe, installer, shortcuts) and icon.png.

    .venv/Scripts/python tools/make_icon.py

Drawn by the same code as the app (subloc.ui.widgets.paint_logo), each size on its own so small ones stay sharp.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent.parent / "subloc" / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def png_bytes(pix) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    return bytes(buf.data().data())


def main() -> None:
    from subloc.ui import theme
    from subloc.ui.widgets import logo_pixmap

    app = QApplication([])  # noqa: F841 (painting needs one)
    theme.load_fonts()
    images = [png_bytes(logo_pixmap(s)) for s in SIZES]
    # ICO: header, one directory entry per size, then the PNG images (Windows Vista and later read PNG entries).
    head = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = len(head) + 16 * len(SIZES)
    entries = b""
    for size, data in zip(SIZES, images, strict=True):
        side = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    (ASSETS / "icon.ico").write_bytes(head + entries + b"".join(images))
    logo_pixmap(512).save(str(ASSETS / "icon.png"))
    print("wrote", ASSETS / "icon.ico", "and icon.png")


if __name__ == "__main__":
    main()
