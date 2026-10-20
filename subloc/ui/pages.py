"""The four screens: Home, Job (ready → working → done/review), Queue, Settings."""

from collections.abc import Sequence
from typing import Any, ClassVar

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..langs import LANGS
from ..translate import MAX_PARALLEL
from . import theme as t
from .i18n import UI_LANGS, rtl, tr
from .lines import LinesModel, LinesView
from .player import Player
from .player import available as player_available
from .widgets import Arrow, DropFrame, FramePreview, RouteBar, RouteField, StageStrip, Timeline, label


def ui_lang() -> str:
    from . import i18n

    return i18n.LANG


SOURCE_LANGS = ["ko", "ja", "en", "ru", "tr", "zh", "es", "fr", "de", "it", "pt", "hi", "th", "vi", "id", "tl", "ar"]
TARGET_LANGS = [("ar", "العربية · Arabic"), ("en", "English")]
SPEECH = [("large-v3", "Best"), ("medium", "Balanced"), ("small", "Light")]


def page() -> QWidget:
    w = QWidget()
    w.setObjectName("page")
    return w


def combo(items: Sequence[tuple[Any, str]]) -> QComboBox:
    c = QComboBox()
    c.setCursor(Qt.CursorShape.PointingHandCursor)
    for data, text in items:
        c.addItem(text, data)
    return c


def select_data(c: QComboBox, data) -> None:
    i = c.findData(data)
    if i < 0 and isinstance(data, str) and data.isdigit():
        i = c.findData(int(data))
    if i >= 0:
        c.setCurrentIndex(i)


# ---------------------------------------------------------------- Home


class HomePage(QWidget):
    files = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(18)
        self.drop = DropFrame()
        self.drop.files.connect(self.files.emit)
        col.addWidget(self.drop, 10)

        self.src = combo([(None, "Detect automatically"), ("mixed", "Mixed (changes during video)")]
                         + [(c, LANGS[c]) for c in SOURCE_LANGS])  # fmt: skip
        self.tgt = combo(TARGET_LANGS)
        self.speech = combo(SPEECH)
        self.model = combo([(None, "Use the model loaded in LM Studio")])
        spoken = RouteField("Spoken language", self.src)
        self.route = RouteBar(
            [spoken, Arrow(), RouteField("Subtitles in", self.tgt), RouteField("Quality", self.speech),
             RouteField("Translator", self.model)], [3, 0, 3, 2, 5])  # fmt: skip
        col.addWidget(self.route)

        trust = QHBoxLayout()
        trust.setSpacing(22)
        trust.addStretch()
        for text in ("🔒  Runs on this PC — nothing is uploaded", "Subtitles are saved next to your video",
                     "Stop anytime — it picks up where it left off"):  # fmt: skip
            trust.addWidget(label(text, "muted"))
        trust.addStretch()
        col.addLayout(trust)

        wrap = QHBoxLayout()
        wrap.addStretch(1)
        holder = QWidget()
        holder.setLayout(col)
        holder.setMaximumWidth(980)
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        wrap.addWidget(holder, 20)
        wrap.addStretch(1)
        outer.addLayout(wrap, 10)
        outer.addStretch(1)

    def set_models(self, models: list[tuple[str, str]], loaded: str | None, saved: str | None) -> None:
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItem(
            tr("Loaded in LM Studio · {model}", model=loaded) if loaded else tr("Use the model loaded in LM Studio"),
            None,
        )
        for mid, text in models:
            self.model.addItem(text, mid)
        select_data(self.model, saved)
        self.model.blockSignals(False)


# ---------------------------------------------------------------- Job


class SegControl(QFrame):
    changed = Signal(str)

    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        self.setObjectName("segGroup")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        for i, (key, text) in enumerate(items):
            b = QPushButton(text)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            lay.addWidget(b)


class JobPage(QWidget):
    start = Signal()
    stop = Signal()
    play = Signal()  # play/pause inside the app
    open_external = Signal()  # open in the user's own player
    watch = Signal()  # watch while it works
    show_files = Signal()
    edit_style = Signal()
    export = Signal(str)  # "ass" | "srt_as"
    seek = Signal(float)
    name_clicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- left column
        left_w = QWidget()
        left = QVBoxLayout(left_w)
        left.setContentsMargins(20, 18, 20, 18)
        left.setSpacing(12)
        head = QHBoxLayout()
        self.title = label("", "title")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta = label("", "mono")
        head.addWidget(self.title, 1)
        head.addWidget(self.meta)
        left.addLayout(head)
        # The screen: a still frame (before/while working) or the built-in player.
        self.preview = FramePreview()
        self.player = Player()
        self.display = QStackedWidget()
        self.display.addWidget(self.preview)
        self.display.addWidget(self.player)
        left.addWidget(self.display, 1)

        # per-file choices (ready state only)
        self.choices = QFrame()
        self.choices.setObjectName("card")
        grid = QGridLayout(self.choices)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setHorizontalSpacing(14)
        self.source = QComboBox()
        self.source.setObjectName("boxed")
        self.audio = QComboBox()
        self.audio.setObjectName("boxed")
        self.source_lbl = label("Make subtitles from", "fieldLabel")
        self.audio_lbl = label("Audio track", "fieldLabel")
        grid.addWidget(self.source_lbl, 0, 0)
        grid.addWidget(self.source, 1, 0)
        grid.addWidget(self.audio_lbl, 0, 1)
        grid.addWidget(self.audio, 1, 1)
        self.choice_hint = label("", "faint")
        self.choice_hint.setWordWrap(True)
        grid.addWidget(self.choice_hint, 2, 0, 1, 2)
        left.addWidget(self.choices)

        self.stages = StageStrip()
        left.addWidget(self.stages)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek.emit)
        left.addWidget(self.timeline)
        self.banner = label("", "warning")
        self.banner.setWordWrap(True)
        self.banner.hide()
        left.addWidget(self.banner)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumWidth(130)
        self.start_btn.clicked.connect(self.start.emit)
        self.play_btn = QPushButton("▶  Play with subtitles")
        self.play_btn.setObjectName("primary")
        self.play_btn.setMinimumWidth(190)
        self.play_btn.clicked.connect(self.play.emit)
        self.watch_btn = QPushButton("▶  Watch while it works")
        self.watch_btn.clicked.connect(self.watch.emit)
        self.external_btn = QPushButton("Open in my player")
        self.external_btn.setObjectName("ghost")
        self.external_btn.clicked.connect(self.open_external.emit)
        self.style_btn = QPushButton("Subtitle style…")
        self.style_btn.clicked.connect(self.edit_style.emit)
        self.export_btn = QPushButton("Export")
        menu = QMenu(self.export_btn)
        menu.addAction("Styled subtitles (.ass)", lambda: self.export.emit("ass"))
        menu.addAction("Save subtitles as…", lambda: self.export.emit("srt_as"))
        menu.addSeparator()
        menu.addAction("Video with subtitles burned in…", lambda: self.export.emit("burn"))
        self.export_btn.setMenu(menu)
        self.export_btn.setProperty("menu", True)
        self.eta = label("", "muted")
        self.files_btn = QPushButton("Show files")
        self.files_btn.setObjectName("ghost")
        self.files_btn.clicked.connect(self.show_files.emit)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.clicked.connect(self.stop.emit)
        for w in (self.start_btn, self.play_btn, self.watch_btn, self.style_btn, self.export_btn):
            actions.addWidget(w)
        actions.addStretch()
        actions.addWidget(self.eta)
        actions.addWidget(self.external_btn)
        actions.addWidget(self.files_btn)
        actions.addWidget(self.stop_btn)
        left.addLayout(actions)
        root.addWidget(left_w, 135)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background: {t.LINE};")
        root.addWidget(sep)

        # ---- right column: lines + names
        right_w = QWidget()
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        rhead = QHBoxLayout()
        rhead.setContentsMargins(18, 12, 14, 12)
        rhead.addWidget(label("Lines", "title"))
        self.count = label("", "muted")
        rhead.addSpacing(8)
        rhead.addWidget(self.count)
        rhead.addStretch()
        self.mode = SegControl([("both", "Both"), ("original", "Original"), ("translation", "Arabic")])
        rhead.addWidget(self.mode)
        right.addLayout(rhead)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {t.LINE};")
        right.addWidget(line)
        self.lines = LinesModel()
        self.view = LinesView(self.lines)
        self.mode.changed.connect(self._set_mode)
        right.addWidget(self.view, 1)

        self.names = QFrame()
        self.names.setStyleSheet(f"QFrame#names {{ background: {t.SURFACE}; border-top: 1px solid {t.LINE}; }}")
        self.names.setObjectName("names")
        nl = QVBoxLayout(self.names)
        nl.setContentsMargins(18, 10, 18, 12)
        nh = QHBoxLayout()
        nh.addWidget(label("Names in this series", "title"))
        nh.addStretch()
        nh.addWidget(label("click one to change it everywhere", "faint"))
        nl.addLayout(nh)
        self.name_area = QScrollArea()
        self.name_area.setWidgetResizable(True)
        self.name_area.setFrameShape(QFrame.Shape.NoFrame)
        self.name_area.setMaximumHeight(84)
        self.name_holder = QWidget()
        self.name_flow = FlowLayout(self.name_holder)
        self.name_area.setWidget(self.name_holder)
        nl.addWidget(self.name_area)
        right.addWidget(self.names)
        root.addWidget(right_w, 100)

    def _set_mode(self, mode: str) -> None:
        self.lines.mode = mode
        self.view.doItemsLayout()
        self.view.viewport().update()

    # ---------- states

    def set_state(self, state: str) -> None:
        """ready | working | done | failed"""
        ready, working, done = state == "ready", state == "working", state == "done"
        self.choices.setVisible(ready and (self.source.count() > 1 or self.audio.count() > 1))
        self.start_btn.setVisible(ready or state == "failed")
        self.start_btn.setText(tr("Start") if ready else tr("Try again"))
        self.stop_btn.setVisible(working)
        self.watch_btn.setVisible(working and player_available())
        self.external_btn.setVisible(done)
        for w in (self.play_btn, self.style_btn, self.export_btn, self.files_btn):
            w.setVisible(done)
        self.stages.setVisible(not done)
        self.view.editable = done
        self.lines.working = working
        self.names.setVisible(done and self.name_flow.count() > 0)
        self.timeline.show_heard = not done
        self.timeline.title = tr("Translated") if done else tr("Progress across the video")
        self.timeline.update()
        if not done:
            self.view.close_editor()

    def set_names(self, pairs: list[tuple[str, str]]) -> None:
        while self.name_flow.count():
            item = self.name_flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        for src, tgt in pairs:
            b = QPushButton(f"{src}  {'←' if rtl() else '→'}  {tgt}")  # arrow points to the translation
            b.setObjectName("chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=src: self.name_clicked.emit(s))
            self.name_flow.addWidget(b)
        QTimer.singleShot(0, self._fit_names)  # after the layout has given the area its width

    def _fit_names(self) -> None:
        """Size the name area to its chips (up to three rows, then it scrolls)."""
        width = max(200, self.name_area.viewport().width())
        h = self.name_flow.heightForWidth(width)
        self.name_holder.setMinimumHeight(h)
        self.name_area.setFixedHeight(min(h, 96) + 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_names)


# ---------------------------------------------------------------- Queue


class QueuePage(QWidget):
    add = Signal()
    start = Signal()
    stop = Signal()
    clear = Signal()
    open_item = Signal(int)

    STATUS: ClassVar[dict[str, tuple[str, str]]] = {
        "waiting": ("Waiting", t.FAINT),
        "listening": ("Listening…", t.ACCENT),
        "listened": ("Heard — waiting to translate", t.MUTED),
        "translating": ("Translating…", t.ACCENT),
        "done": ("Done", t.OK),
        "skipped": ("Already done", t.MUTED),
        "failed": ("Failed", t.ERR),
        "stopped": ("Stopped", t.MUTED),
    }

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label("Queue", "title"))
        self.summary = label("Drop several videos or a whole folder on the Home screen.", "muted")
        head.addWidget(self.summary)
        head.addStretch()
        self.add_btn = QPushButton("Add videos…")
        self.add_btn.clicked.connect(self.add.emit)
        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.clicked.connect(self.clear.emit)
        self.start_btn = QPushButton("Start queue")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start.emit)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop.emit)
        for b in (self.add_btn, self.clear_btn, self.stop_btn, self.start_btn):
            head.addWidget(b)
        lay.addLayout(head)
        hint = label("Every video is listened to first, then all are translated — names stay the same across "
                     "episodes in a folder.", "faint")  # fmt: skip
        lay.addWidget(hint)
        self.list = QListWidget()
        self.list.setStyleSheet(
            f"QListWidget {{ background: {t.SURFACE}; border: 1px solid {t.LINE}; border-radius: 12px; padding: 6px; }}"
        )
        self.list.setItemDelegate(QueueDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setToolTip("Double-click a finished video to review it")
        self.list.itemDoubleClicked.connect(lambda it: self.open_item.emit(self.list.row(it)))
        lay.addWidget(self.list, 1)
        self.set_running(False)

    def set_items(self, items: list[tuple[str, str, str]], progress: dict[int, float] | None = None) -> None:
        """(file name, status, detail); progress: row → 0..1 for the item being worked on."""
        progress = progress or {}
        if self.list.count() != len(items):
            self.list.clear()
            for _ in items:
                self.list.addItem(QListWidgetItem())
        for i, (name, status, detail) in enumerate(items):
            text, color = self.STATUS.get(status, (status, t.MUTED))
            if detail.lower() == text.lower():
                detail = ""
            text, detail = tr(text), tr(detail)
            it = self.list.item(i)
            it.setData(Qt.ItemDataRole.UserRole, (name, text, color, detail, progress.get(i)))
            it.setToolTip(detail or text)
        self.list.viewport().update()
        waiting = sum(1 for _, s, _ in items if s == "waiting")
        done = sum(1 for _, s, _ in items if s in ("done", "skipped"))
        self.summary.setText(
            tr("{n} videos · {d} done · {w} waiting", n=len(items), d=done, w=waiting)
            if items
            else tr("Drop several videos or a whole folder on the Home screen.")
        )

    def set_running(self, running: bool) -> None:
        self.start_btn.setVisible(not running)
        self.stop_btn.setVisible(running)
        self.add_btn.setEnabled(not running)
        self.clear_btn.setEnabled(not running)


class QueueDelegate(QStyledItemDelegate):
    """A queue row: status pill, file name, detail, and a thin progress bar while it's being worked on."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 58)

    def paint(self, p: QPainter, option, index) -> None:
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        name, text, color, detail, progress = data
        r = option.rect.adjusted(6, 2, -6, -2)
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.SURFACE_2))
            p.drawRoundedRect(QRectF(r), 8, 8)
        p.setFont(t.font(8.5, QFont.Weight.Medium))
        fm = p.fontMetrics()
        mirrored = option.widget is not None and option.widget.isRightToLeft()
        pw = fm.horizontalAdvance(text) + 18
        pill = QRectF(r.right() - 10 - pw if mirrored else r.left() + 10, r.top() + 10, pw, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.qcolor(color, 0.14))
        p.drawRoundedRect(pill, 10, 10)
        p.setPen(QColor(color))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)
        name_w = r.width() - 300
        x = r.left() + 150  # names in one column whatever the status (pill sits left or right of it)
        p.setFont(t.font(10, QFont.Weight.Medium))
        p.setPen(QColor(t.TEXT))
        lead = Qt.AlignmentFlag.AlignRight if mirrored else Qt.AlignmentFlag.AlignLeft
        p.drawText(QRect(x, r.top() + 8, name_w, 22), lead | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, name_w))  # fmt: skip
        if detail:
            p.setFont(t.font(9))
            p.setPen(QColor(t.ERR if color == t.ERR else t.MUTED))
            p.drawText(QRect(x, r.top() + 30, name_w, 20), lead | Qt.AlignmentFlag.AlignVCenter,
                       p.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, name_w))  # fmt: skip
        if progress is not None:
            bar = QRectF(r.left() + 20 if mirrored else r.right() - 130, r.top() + 18, 110, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t.SURFACE_3))
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(QColor(t.ACCENT))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.02, progress), 4), 2, 2)
            p.setFont(t.font(8, family=t.MONO))
            p.setPen(QColor(t.MUTED))
            p.drawText(QRectF(bar.left(), bar.bottom() + 4, bar.width(), 14), Qt.AlignmentFlag.AlignRight,
                       f"{progress:.0%}")  # fmt: skip
        p.setPen(QColor("#1f2226"))
        p.drawLine(r.left() + 8, r.bottom(), r.right() - 8, r.bottom())
        p.restore()


# ---------------------------------------------------------------- Settings


class SettingsPage(QWidget):
    changed = Signal()
    edit_style = Signal()
    language = Signal(str)
    run_setup = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(16)
        outer.addWidget(label("Settings", "title"))

        card = QFrame()
        card.setObjectName("card")
        form = QGridLayout(card)
        form.setContentsMargins(20, 18, 20, 18)
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(14)
        r = 0

        def row(title: str, hint: str, widget: QWidget) -> None:
            nonlocal r
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(label(title))
            h = label(hint, "faint")
            h.setWordWrap(True)
            box.addWidget(h)
            form.addLayout(box, r, 0)
            form.addWidget(widget, r, 1, Qt.AlignmentFlag.AlignVCenter)
            r += 1

        self.lang = QComboBox()
        self.lang.setObjectName("boxed")
        for code, name in UI_LANGS:
            self.lang.addItem(name, code)
        select_data(self.lang, ui_lang())
        self.lang.currentIndexChanged.connect(lambda *_: self.language.emit(self.lang.currentData()))
        row("Interface language", "The app restarts its window to switch.", self.lang)
        setup = QPushButton("Run setup again…")
        setup.clicked.connect(self.run_setup.emit)
        self.translator_info = label("", "muted")
        tb = QHBoxLayout()
        tb.addWidget(self.translator_info, 1)
        tb.addWidget(setup)
        tbw = QWidget()
        tbw.setLayout(tb)
        row("Translator", "Choose the language, translator and models again.", tbw)
        self.parallel = QComboBox()
        self.parallel.setObjectName("boxed")
        for n in range(1, MAX_PARALLEL + 1):
            self.parallel.addItem(tr("{n} at once  (recommended)" if n == 2 else "{n} at once", n=n), n)
        self.parallel.currentIndexChanged.connect(lambda *_: self.changed.emit())
        row("Translation speed", "Requests sent to LM Studio at the same time. More is faster only if your "
            "graphics card has free memory.", self.parallel)  # fmt: skip
        self.glossary = QComboBox()
        self.glossary.setObjectName("boxed")
        self.glossary.addItem("On (recommended)", True)
        self.glossary.addItem("Off", False)
        self.glossary.currentIndexChanged.connect(lambda *_: self.changed.emit())
        row("Keep names consistent", "Finds names first so each is spelled the same way in every line and "
            "episode.", self.glossary)  # fmt: skip
        style = QPushButton("Change…")
        style.clicked.connect(self.edit_style.emit)
        self.style_name = label("", "muted")
        sb = QHBoxLayout()
        sb.addWidget(self.style_name)
        sb.addWidget(style)
        sbw = QWidget()
        sbw.setLayout(sb)
        row("Subtitle look", "Used for styled .ass subtitles and burned-in videos. Plain .srt files are always "
            "saved too.", sbw)  # fmt: skip
        form.setColumnStretch(0, 3)
        form.setColumnStretch(1, 2)
        outer.addWidget(card)

        about = label("Subloc runs entirely on this computer. Your videos and subtitles are never uploaded.", "muted")
        outer.addWidget(about)
        outer.addStretch()


# ---------------------------------------------------------------- small flow layout for name chips


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self.items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _place(self, rect: QRect, dry: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self.items:
            w = it.sizeHint()
            if x + w.width() > rect.right() and line_h:
                x, y, line_h = rect.x(), y + line_h + self.spacing(), 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + self.spacing()
            line_h = max(line_h, w.height())
        return y + line_h - rect.y()
