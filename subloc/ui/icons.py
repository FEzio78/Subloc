"""Icons: Lucide (ISC licence; the SVGs and the licence are in subloc/assets/icons), drawn in any theme colour, sharp
on scaled screens. icon("play", t.ACCENT) → QIcon; pixmap(...) → QPixmap."""

from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme as t

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"


@cache
def _svg(name: str) -> bytes:
    return (ICONS_DIR / f"{name}.svg").read_bytes()


def _ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return max(1.0, screen.devicePixelRatio()) if screen else 1.0


@cache
def pixmap(name: str, color: str = t.MUTED, size: int = 16, ratio: float = 0.0) -> QPixmap:
    ratio = ratio or _ratio()
    renderer = QSvgRenderer(QByteArray(_svg(name).replace(b"currentColor", color.encode())))
    side = round(size * ratio)
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, side, side))
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


@cache
def nav_icon(name: str, size: int = 16) -> QIcon:
    """Top-bar icon: dim, bright when hovered or when its page is shown."""
    qi = QIcon()
    for ratio in (1.0, 2.0):
        qi.addPixmap(pixmap(name, t.MUTED, size, ratio), QIcon.Mode.Normal, QIcon.State.Off)
        qi.addPixmap(pixmap(name, t.TEXT, size, ratio), QIcon.Mode.Normal, QIcon.State.On)
        qi.addPixmap(pixmap(name, t.TEXT, size, ratio), QIcon.Mode.Active, QIcon.State.Off)
    return qi


@cache
def icon(name: str, color: str = t.MUTED, size: int = 16) -> QIcon:
    """With a dimmed version for disabled buttons."""
    qi = QIcon()
    for ratio in (1.0, 2.0):
        qi.addPixmap(pixmap(name, color, size, ratio), QIcon.Mode.Normal)
        qi.addPixmap(pixmap(name, t.FAINT, size, ratio), QIcon.Mode.Disabled)
    return qi
