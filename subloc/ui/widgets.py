"""Custom-drawn pieces of the interface (see design/mockup.html)."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme as t
from .i18n import rtl, tr


def fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def label(text: str = "", name: str | None = None) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    return lbl


# ---------------------------------------------------------------- brand + top bar


LOGO_TILE = "#1f2327"


def paint_logo(p: QPainter, x: float, y: float, size: float) -> None:
    """The logo: a dark rounded tile, a yellow serif S and two subtitle lines under it, the second shorter.
    Used by the top bar, the setup wizard, the app icon and tools/make_icon.py."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(LOGO_TILE))
    p.drawRoundedRect(QRectF(x, y, size, size), size * 0.22, size * 0.22)
    f = QFont(t.SERIF)
    f.setWeight(QFont.Weight.Medium)
    f.setPixelSize(100)
    f.setPixelSize(max(1, round(100 * size * 0.42 / QFontMetricsF(f).capHeight())))  # the S: 42% of the tile
    s = QPainterPath()
    s.addText(0, 0, f, "S")
    s.translate(x + size / 2 - s.boundingRect().center().x(), y + size * 0.59)  # centred on the letter itself
    p.setBrush(QColor(t.ACCENT))
    p.drawPath(s)
    h = max(1.4, size * 0.065)
    p.drawRoundedRect(QRectF(x + size * 0.22, y + size * 0.69, size * 0.56, h), h / 2, h / 2)
    p.drawRoundedRect(QRectF(x + size * 0.33, y + size * 0.795, size * 0.34, h), h / 2, h / 2)
    p.restore()


class BrandMark(QWidget):
    def __init__(self, size: int = 28):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, e):
        p = QPainter(self)
        paint_logo(p, 0, 0, self.width())


def logo_pixmap(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    paint_logo(p, 0, 0, size)
    p.end()
    return pix


def app_icon() -> QIcon:
    """Window / taskbar / notification icon, drawn crisp at each size."""
    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(size))
    return icon


class StatusDot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self.color = t.FAINT

    def set_color(self, color: str) -> None:
        self.color = color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.qcolor(self.color, 0.18))
        p.drawEllipse(QRectF(0.5, 0.5, 13, 13))
        p.setBrush(QColor(self.color))
        p.drawEllipse(QRectF(3.5, 3.5, 7, 7))


class TopBar(QFrame):
    navigate = Signal(str)  # "home" | "library" | "queue" | "settings"

    def __init__(self):
        super().__init__()
        self.setObjectName("topbar")
        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 20, 0)
        lay.setSpacing(10)
        lay.addWidget(BrandMark())
        lay.addWidget(label("Subloc", "brand"))
        lay.addSpacing(18)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, text in (("home", "Home"), ("library", "Library"), ("queue", "Queue"), ("settings", "Settings")):
            b = QPushButton(tr(text))
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            lay.addWidget(b)
        self.buttons["home"].setChecked(True)
        lay.addStretch()
        self.dot = StatusDot()
        self.engine = label(tr("Checking translator…"), "engine")
        lay.addWidget(self.dot)
        lay.addWidget(self.engine)

    def select(self, key: str) -> None:
        self.buttons[key].setChecked(True)

    def set_queue_count(self, n: int) -> None:
        self.buttons["queue"].setText(tr("Queue  {n}", n=n) if n else tr("Queue"))

    def set_engine(self, text: str, ok: bool | None) -> None:
        self.engine.setText(text)
        self.dot.set_color(t.OK if ok else (t.FAINT if ok is None else t.ERR))


# ---------------------------------------------------------------- new project (drop strip)


class UploadIcon(QWidget):
    """Rounded box with an arrow going up."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(54, 54)
        self.hover = False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(27, 27)
        p.setPen(QPen(QColor(t.ACCENT if self.hover else "#3a3f46"), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(1, 1, 52, 52), 14, 14)
        color = t.ACCENT if self.hover else t.MUTED
        p.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawLine(QPointF(c.x(), c.y() + 5), QPointF(c.x(), c.y() - 9))
        p.drawPolyline([QPointF(c.x() - 6, c.y() - 3), QPointF(c.x(), c.y() - 9), QPointF(c.x() + 6, c.y() - 3)])
        p.drawPolyline([QPointF(c.x() - 11, c.y() + 3), QPointF(c.x() - 11, c.y() + 9),
                        QPointF(c.x() + 11, c.y() + 9), QPointF(c.x() + 11, c.y() + 3)])  # fmt: skip


class DropStrip(QFrame):
    """'New project': where to drop a video or a folder (the whole Home page accepts drops), or click to choose."""

    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(104)
        self.hover = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 16, 18, 16)
        lay.setSpacing(16)
        self.icon = UploadIcon()
        lay.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addStretch()
        col.addWidget(label("Drop a video or a folder here", "dropTitle"))
        col.addWidget(label("or click to choose · MP4 · MKV · AVI · MOV · WEBM", "muted"))
        col.addStretch()
        lay.addLayout(col, 1)
        self.folder_btn = QPushButton("Choose folder…")
        self.video_btn = QPushButton("Choose video…")
        self.video_btn.setObjectName("primary")
        for b in (self.folder_btn, self.video_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            lay.addWidget(b)

    def set_hover(self, on: bool) -> None:
        self.hover = self.icon.hover = on
        self.icon.update()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(t.qcolor(t.ACCENT, 0.05) if self.hover else QColor("#111316"))
        p.setPen(QPen(QColor(t.ACCENT if self.hover else "#3a3f46"), 1.5, Qt.PenStyle.DashLine))
        p.drawRoundedRect(r, 12, 12)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# ---------------------------------------------------------------- route bar


class RouteField(QWidget):
    def __init__(self, caption: str, combo: QComboBox):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 12, 10)
        lay.setSpacing(1)
        lay.addWidget(label(caption, "fieldLabel"))
        lay.addWidget(combo)
        self.combo = combo


def vline() -> QFrame:
    f = QFrame()
    f.setFixedWidth(1)
    f.setStyleSheet(f"background: {t.LINE};")
    return f


class RouteBar(QFrame):
    """[Spoken language] → [Subtitles in] | [Quality] | [Translator]"""

    def __init__(self, fields: list[QWidget], stretch: list[int]):
        super().__init__()
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for i, (f, s) in enumerate(zip(fields, stretch, strict=True)):
            if i:
                lay.addWidget(vline())
            lay.addWidget(f, s)


class Arrow(QLabel):
    def __init__(self):
        super().__init__("←" if rtl() else "→")
        self.setStyleSheet(f"color: {t.ACCENT}; font-size: 14pt; padding: 0 6px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


# ---------------------------------------------------------------- stages


class StageBox(QFrame):
    def __init__(self, caption: str):
        super().__init__()
        self.caption = caption
        self.state = "waiting"  # waiting | now | done | failed
        self.value = "—"
        self.setMinimumHeight(52)

    def set(self, state: str, value: str) -> None:
        self.state, self.value = state, value
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        now = self.state == "now"
        p.setPen(QPen(t.qcolor(t.ACCENT, 0.45) if now else QColor(t.LINE), 1))
        p.setBrush(t.qcolor(t.ACCENT, 0.06) if now else QColor(t.SURFACE))
        p.drawRoundedRect(r, 9, 9)
        p.setFont(t.font(8))
        p.setPen(QColor(t.MUTED))
        lead, trail = ((Qt.AlignmentFlag.AlignRight, Qt.AlignmentFlag.AlignLeft) if self.isRightToLeft()
                       else (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignRight))  # fmt: skip
        p.drawText(r.adjusted(10, 7, -10, 0), lead | Qt.AlignmentFlag.AlignTop, self.caption)
        mark = {"done": ("✓", t.OK), "failed": ("✕", t.ERR)}.get(self.state)
        if mark:
            p.setPen(QColor(mark[1]))
            p.drawText(r.adjusted(10, 7, -10, 0), trail | Qt.AlignmentFlag.AlignTop, mark[0])
        p.setFont(t.font(10, QFont.Weight.Medium))
        p.setPen(QColor(t.ACCENT if now else (t.TEXT if self.state != "waiting" else t.FAINT)))
        p.drawText(r.adjusted(10, 0, -10, -8), lead | Qt.AlignmentFlag.AlignBottom, self.value)


class StageStrip(QWidget):
    KEYS = ("audio", "transcribe", "names", "translate")

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.boxes = {}
        captions = ("1 · Audio", "2 · Listening", "3 · Names", "4 · Translating")
        for k, cap in zip(self.KEYS, captions, strict=True):
            b = StageBox(tr(cap))
            self.boxes[k] = b
            lay.addWidget(b)

    def reset(self, reading_subtitles: bool = False) -> None:
        """Step 2 is 'Listening', or 'Subtitles' when the file's own subtitles are used."""
        self.boxes["transcribe"].caption = tr("2 · Subtitles" if reading_subtitles else "2 · Listening")
        for b in self.boxes.values():
            b.set("waiting", "—")

    def set(self, key: str, state: str, value: str) -> None:
        if key in self.boxes:
            self.boxes[key].set(state, value)


# ---------------------------------------------------------------- timeline


class Timeline(QWidget):
    """Progress drawn on the video's own timeline: speech found (grey) and translated (yellow)."""

    seek = Signal(float)

    def __init__(self):
        super().__init__()
        self.duration = 1.0
        self.heard: list[tuple[float, float]] = []
        self.done_spans: list[tuple[float, float]] = []
        self.playhead: float | None = None
        self.title = tr("Progress across the video")
        self.right = ""
        self.show_heard = True
        self.setMinimumHeight(118)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, duration: float, heard, done, right: str = "") -> None:
        self.duration = max(duration, 1.0)
        self.heard, self.done_spans, self.right = heard, done, right
        self.update()

    def set_playhead(self, sec: float | None) -> None:
        self.playhead = sec
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(14, 40, self.width() - 28, 12)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Time runs left-to-right on every video player, Arabic included; positions below are absolute.
        p.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(t.LINE), 1))
        p.setBrush(QColor(t.SURFACE))
        p.drawRoundedRect(r, 10, 10)

        p.setFont(t.font(9))
        p.setPen(QColor(t.MUTED))
        left_text, right_text = (self.right, self.title) if self.isRightToLeft() else (self.title, self.right)
        p.drawText(QRectF(14, 10, r.width() / 2, 18), Qt.AlignmentFlag.AlignLeft, left_text)
        p.setPen(QColor(t.TEXT))
        p.drawText(QRectF(r.width() / 2, 10, r.width() / 2 - 14, 18), Qt.AlignmentFlag.AlignRight, right_text)

        x0, w = 14.0, self.width() - 28.0

        def span(a: float, b: float) -> tuple[float, float]:
            return x0 + w * a / self.duration, max(1.5, w * (b - a) / self.duration)

        rows = [(36.0, 16.0, self.heard, QColor("#6f7884"))] if self.show_heard else []
        rows.append((58.0 if self.show_heard else 40.0, 9.0, self.done_spans, QColor(t.ACCENT)))
        for y, h, segs, color in rows:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.SURFACE_3))
            p.drawRoundedRect(QRectF(x0, y, w, h), 3, 3)
            p.setBrush(color)
            for a, b in segs:
                sx, sw = span(a, b)
                p.drawRect(QRectF(sx, y, sw, h))
        if self.playhead is not None:
            px = x0 + w * min(self.playhead, self.duration) / self.duration
            top, bottom = rows[0][0] - 4, rows[-1][0] + rows[-1][1] + 4
            p.setPen(QPen(QColor(0, 0, 0, 120), 5))
            p.drawLine(QPointF(px, top), QPointF(px, bottom))
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.drawLine(QPointF(px, top), QPointF(px, bottom))

        p.setFont(t.font(8, family=t.MONO))
        p.setPen(QColor(t.FAINT))
        ticks = 5
        scale_y = rows[-1][0] + rows[-1][1] + 8
        for i in range(ticks + 1):
            sec = self.duration * i / ticks
            tx = x0 + w * i / ticks
            align = Qt.AlignmentFlag.AlignLeft if i == 0 else (
                Qt.AlignmentFlag.AlignRight if i == ticks else Qt.AlignmentFlag.AlignHCenter)  # fmt: skip
            rect = QRectF(tx - 40 if 0 < i < ticks else (tx if i == 0 else tx - 80), scale_y, 80, 14)
            p.drawText(rect, align, fmt_time(sec))

        # legend: starts on the reading side (right in Arabic)
        ly = scale_y + 20
        p.setFont(t.font(8.5))
        items = ([(tr("Speech found"), QColor("#6f7884"))] if self.show_heard else []) + [
            (tr("Translated"), QColor(t.ACCENT)), (tr("Preview position"), QColor("#ffffff"))]  # fmt: skip
        mirrored = self.isRightToLeft()
        lx = x0 + w if mirrored else x0
        for text, color in items:
            tw = p.fontMetrics().horizontalAdvance(text)
            swatch_x = lx - 9 if mirrored else lx
            text_x = swatch_x - 5 - tw if mirrored else lx + 14
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(swatch_x, ly + 3, 9, 9), 2, 2)
            p.setPen(QColor(t.MUTED))
            p.drawText(
                QRectF(text_x, ly, tw + 2, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute, text
            )
            lx += -(14 + tw + 18) if mirrored else 14 + tw + 18

    def mousePressEvent(self, e):
        x0, w = 14.0, self.width() - 28.0
        frac = (e.position().x() - x0) / w
        if 0 <= frac <= 1:
            self.seek.emit(frac * self.duration)


# ---------------------------------------------------------------- frame preview


class FramePreview(QWidget):
    """A video frame (or a placeholder) with the current subtitle drawn in the default style."""

    def __init__(self):
        super().__init__()
        self.pix: QPixmap | None = None
        self.text = ""
        self.rtl = True
        self.stamp = ""
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_frame(self, pix: QPixmap | None) -> None:
        self.pix = pix
        self.update()

    def set_caption(self, text: str, stamp: str = "", rtl: bool = True) -> None:
        # A leading right-to-left mark makes the line RTL, so end punctuation lands on the left.
        self.text = f"\u200f{text}" if rtl and text else text
        self.stamp, self.rtl = stamp, rtl
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        p.fillRect(r, QColor("#0a0b0d"))
        pic = r
        if self.pix and not self.pix.isNull():
            s = self.pix.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
            pic = QRectF((r.width() - s.width()) / 2, (r.height() - s.height()) / 2, s.width(), s.height())
            p.drawPixmap(pic.toRect(), self.pix)
        else:
            p.fillRect(r, QColor("#16191d"))
        if self.stamp:
            p.setFont(t.font(8, family=t.MONO))
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(self.stamp) + 14
            box = QRectF(self.width() - 12 - bw if self.isRightToLeft() else 12, 10, bw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(255, 255, 255, 220))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.stamp)
        if self.text:
            # Plain drawText (full Arabic shaping + bidi); the outline is the same text drawn around it.
            size = max(11.0, pic.height() / 22)
            p.setFont(t.font(size, QFont.Weight.DemiBold, t.ARABIC if self.rtl else t.SANS))
            area = QRectF(pic.left() + pic.width() * 0.06, pic.top(), pic.width() * 0.88, pic.height() * 0.93)
            flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap
            o = max(1.0, size / 9)
            if self.rtl:  # the painter lays text out left-to-right unless told otherwise
                p.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            p.setPen(QColor(0, 0, 0, 235))
            for dx, dy in ((-o, 0), (o, 0), (0, -o), (0, o), (-o, -o), (o, o), (-o, o), (o, -o)):
                p.drawText(area.translated(dx, dy), flags, self.text)
            p.setPen(QColor("#ffffff"))
            p.drawText(area, flags, self.text)
