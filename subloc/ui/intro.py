"""Opening animation (about 2.6 s), played over the main window as it opens.

"Subloc" appears, the letters after the S fold into it, the S moves to the centre, and the logo tile and its two
subtitle lines grow around it; then the layer fades away and the app is there. A click or any key skips it.
The last frame is the logo exactly as paint_logo draws it.
"""

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from . import theme as t
from .widgets import LOGO_TILE

DURATION = 2600  # ms
LOGO = 150.0  # final tile size, px

_ease = QEasingCurve(QEasingCurve.Type.InOutCubic)
_out = QEasingCurve(QEasingCurve.Type.OutCubic)


def _phase(ms: float, start: float, end: float, curve: QEasingCurve = _ease) -> float:
    """0 before `start`, 1 after `end`, eased in between."""
    if ms <= start:
        return 0.0
    if ms >= end:
        return 1.0
    return curve.valueForProgress((ms - start) / (end - start))


def _mix(a: float, b: float, f: float) -> float:
    return a + (b - a) * f


class Intro(QWidget):
    finished = Signal()

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.ms = 0.0
        self.setGeometry(window.rect())
        window.installEventFilter(self)  # follow the window's size
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        f = QFont(t.SERIF)
        f.setWeight(QFont.Weight.Medium)
        f.setPixelSize(100)
        f.setPixelSize(max(1, round(100 * LOGO * 0.42 / QFontMetricsF(f).capHeight())))  # same S as the logo
        self.s = QPainterPath()
        self.s.addText(0, 0, f, "S")
        self.rest = QPainterPath()  # "ubloc", placed after the S with the word's own spacing
        self.rest.addText(QFontMetricsF(f).horizontalAdvance("S"), 0, f, "ubloc")
        self.word_w = QFontMetricsF(f).horizontalAdvance("Subloc")

        self.anim = QVariantAnimation(self, startValue=0.0, endValue=float(DURATION), duration=DURATION)
        self.anim.valueChanged.connect(self._tick)
        self.anim.finished.connect(self._done)

    def start(self) -> None:
        self.raise_()
        self.show()
        self.setFocus()
        self.anim.start()

    def _tick(self, ms: float) -> None:
        self.ms = ms
        self.update()

    def _done(self) -> None:
        self.hide()
        self.deleteLater()
        self.finished.emit()

    def skip(self) -> None:
        if self.anim.state() == QVariantAnimation.State.Running:
            self.anim.stop()
            self._done()

    def mousePressEvent(self, e):
        self.skip()

    def keyPressEvent(self, e):
        self.skip()

    def eventFilter(self, obj: QObject, e: QEvent) -> bool:
        if e.type() == QEvent.Type.Resize and isinstance(obj, QWidget):
            self.setGeometry(obj.rect())
        return False

    def paintEvent(self, e):
        ms = self.ms
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fade_out = _phase(ms, 2250, 2600)  # the layer goes, the app shows through
        p.setOpacity(1.0 - fade_out)
        p.fillRect(self.rect(), QColor(t.BG))

        cx, cy = self.width() / 2, self.height() / 2
        top = cy - LOGO / 2
        baseline = top + LOGO * 0.59
        sb = self.s.boundingRect()
        s_final_x = cx - sb.center().x()  # S centred, as in the logo
        s_word_x = cx - self.word_w / 2  # S where it stands in the centred word

        appear = _phase(ms, 0, 700, _out)
        fold = _phase(ms, 900, 1500)
        grow = _phase(ms, 1400, 2000, _out)

        # The tile, growing in behind the S.
        if grow > 0:
            size = LOGO * _mix(0.55, 1.0, grow)
            tile = QRectF(cx - size / 2, top + (LOGO - size) / 2, size, size)
            c = QColor(LOGO_TILE)
            c.setAlphaF(grow)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(tile, size * 0.22, size * 0.22)

        accent = QColor(t.ACCENT)
        p.setPen(Qt.PenStyle.NoPen)
        rise = (1 - appear) * 10
        s_x = _mix(s_word_x, s_final_x, fold)

        # "ubloc": folds into the S (slides onto it, narrows, fades).
        if fold < 1:
            p.save()
            c = QColor(accent)
            c.setAlphaF(appear * (1 - fold) ** 1.5)
            p.setBrush(c)
            p.translate(s_x + sb.right() * 0.6, baseline + rise)
            p.scale(_mix(1.0, 0.15, fold), 1.0)
            p.translate(-sb.right() * 0.6, 0)
            p.drawPath(self.rest)
            p.restore()

        # The S.
        c = QColor(accent)
        c.setAlphaF(appear)
        p.setBrush(c)
        p.drawPath(self.s.translated(s_x, baseline + rise))

        # The two subtitle lines, drawn out from the middle (the short one a beat later).
        h = LOGO * 0.065
        for y, w, start in ((0.69, 0.56, 1650), (0.795, 0.34, 1780)):
            f = _phase(ms, start, start + 400, _out)
            if f > 0:
                lw = LOGO * w * f
                p.drawRoundedRect(QRectF(cx - lw / 2, top + LOGO * y, lw, h), h / 2, h / 2)
        p.end()


def play(window: QWidget) -> Intro:
    """Start the opening animation over `window` (already shown)."""
    intro = Intro(window)
    intro.start()
    return intro
