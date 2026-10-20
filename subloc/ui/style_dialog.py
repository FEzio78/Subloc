"""Subtitle style editor: presets + custom options, previewed exactly (libass on a real frame)."""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontDatabase, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..style import DEFAULT, PRESETS, SubStyle, render_preview, with_changes
from . import theme as t
from .i18n import tr, translate_tree
from .widgets import fmt_time, label


class _Bridge(QObject):
    rendered = Signal(int, bytes)  # request number, PNG
    failed = Signal(int, str)


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str):
        super().__init__()
        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def set_color(self, color: str) -> None:
        self.color = color
        self.setStyleSheet(f"QPushButton {{ background: {color}; border: 1px solid {t.LINE}; border-radius: 6px; }}")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self.color), self, tr("Choose a colour"))
        if c.isValid():
            self.set_color(c.name().upper())
            self.changed.emit(self.color)


def _slider(lo: int, hi: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    return s


class StyleDialog(QDialog):
    """The chosen style is in .chosen after exec() == Accepted. Nothing changes until Apply.
    (Not .style/.size: those would hide QWidget.style()/size().)"""

    def __init__(self, parent: QWidget, style: SubStyle, video: Path | None, duration: float,
                 sample_text: str, sample_at: float, lang: str | None):  # fmt: skip
        super().__init__(parent)
        self.setWindowTitle("Subtitle style")
        self.resize(1120, 640)
        self.setStyleSheet(f"QDialog {{ background: {t.BG}; }}")
        self.chosen = style
        self.video, self.duration, self.lang = video, max(duration, 1.0), lang
        self.sample_text = sample_text or "هذا مثال على شكل الترجمة على الشاشة."  # sample subtitle, not UI text
        self.request = 0
        self.bridge = _Bridge()
        self.bridge.rendered.connect(self._show_png)
        self.bridge.failed.connect(self._show_error)
        self.debounce = QTimer(self, singleShot=True, interval=120)
        self.debounce.timeout.connect(self._render)

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        # ---- left: preview
        left = QVBoxLayout()
        left.setSpacing(10)
        self.image = QLabel()
        self.image.setMinimumSize(640, 360)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet(f"background: #0a0b0d; border-radius: 10px; border: 1px solid {t.LINE};")
        left.addWidget(self.image, 1)
        scrub = QHBoxLayout()
        self.when = label(fmt_time(sample_at), "mono")
        self.scrub = _slider(0, int(self.duration), int(sample_at))
        self.scrub.setEnabled(video is not None)
        self.scrub.valueChanged.connect(self._scrubbed)
        scrub.addWidget(label("Check other scenes", "muted"))
        scrub.addWidget(self.scrub, 1)
        scrub.addWidget(self.when)
        left.addLayout(scrub)
        self.note = label(
            "This is exactly how VLC, MPV and burned-in videos will show it." if video else
            "Open a video to preview on a real frame.", "faint")  # fmt: skip
        left.addWidget(self.note)
        root.addLayout(left, 3)

        # ---- right: controls
        panel = QFrame()
        panel.setObjectName("card")
        right = QVBoxLayout(panel)
        right.setContentsMargins(18, 16, 18, 16)
        right.setSpacing(12)
        right.addWidget(label("Look", "title"))
        presets = QHBoxLayout()
        presets.setSpacing(6)
        self.preset_group = QButtonGroup(self)
        for name in PRESETS:
            b = QPushButton(name)
            b.setProperty("preset", name)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, n=name: self._apply_preset(n))
            self.preset_group.addButton(b)
            presets.addWidget(b)
        presets.addStretch()
        seg = QFrame()
        seg.setObjectName("segGroup")
        seg.setLayout(presets)
        presets.setContentsMargins(3, 3, 3, 3)
        right.addWidget(seg)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.font_box = QFontComboBox()
        self.font_box.setObjectName("boxed")
        self.font_box.setWritingSystem(QFontDatabase.WritingSystem.Arabic)  # fonts that can show Arabic
        self.size_box = QSpinBox()
        self.size_box.setRange(24, 110)
        self.size_box.setSuffix(" px")
        self.bold = QCheckBox("Bold")
        self.text_color = ColorButton(style.text_color)
        self.outline_color = ColorButton(style.outline_color)
        self.outline = _slider(0, 80, 0)  # tenths of a pixel
        self.shadow = _slider(0, 60, 0)
        self.box = QCheckBox("Background box")
        self.box_color = ColorButton(style.box_color)
        self.box_opacity = _slider(10, 100, 60)
        self.position = QComboBox()
        self.position.setObjectName("boxed")
        self.position.addItem("Bottom", "bottom")
        self.position.addItem("Top", "top")
        self.margin = _slider(10, 200, 60)

        row = QHBoxLayout()
        row.addWidget(self.size_box)
        row.addWidget(self.bold)
        row.addStretch()
        form.addRow(label("Font", "muted"), self.font_box)
        form.addRow(label("Size", "muted"), row)
        colors = QHBoxLayout()
        colors.addWidget(self.text_color)
        colors.addWidget(label("text", "faint"))
        colors.addSpacing(10)
        colors.addWidget(self.outline_color)
        colors.addWidget(label("outline", "faint"))
        colors.addStretch()
        form.addRow(label("Colours", "muted"), colors)
        form.addRow(label("Outline", "muted"), self.outline)
        form.addRow(label("Shadow", "muted"), self.shadow)
        boxrow = QHBoxLayout()
        boxrow.addWidget(self.box)
        boxrow.addWidget(self.box_color)
        boxrow.addStretch()
        form.addRow(label("Box", "muted"), boxrow)
        form.addRow(label("Box opacity", "muted"), self.box_opacity)
        form.addRow(label("Position", "muted"), self.position)
        form.addRow(label("From edge", "muted"), self.margin)
        right.addLayout(form)
        right.addStretch()

        buttons = QHBoxLayout()
        reset = QPushButton("Reset to Classic")
        reset.setObjectName("ghost")
        reset.clicked.connect(lambda: self._apply_preset("Classic"))
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        apply = QPushButton("Apply")
        apply.setObjectName("primary")
        apply.clicked.connect(self.accept)
        buttons.addWidget(reset)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(apply)
        right.addLayout(buttons)
        root.addWidget(panel, 2)

        self._load(style)
        for sig in (self.size_box.valueChanged, self.outline.valueChanged, self.shadow.valueChanged,
                    self.box_opacity.valueChanged, self.margin.valueChanged, self.bold.toggled, self.box.toggled,
                    self.position.currentIndexChanged, self.font_box.currentFontChanged, self.text_color.changed,
                    self.outline_color.changed, self.box_color.changed):  # fmt: skip
            sig.connect(self._changed)
        translate_tree(self)
        self._render()

    # ---------- state <-> controls

    def _load(self, s: SubStyle) -> None:
        self._loading = True
        self.font_box.setCurrentFont(t.font(10, family=s.font))
        self.size_box.setValue(s.size)
        self.bold.setChecked(s.bold)
        self.text_color.set_color(s.text_color)
        self.outline_color.set_color(s.outline_color)
        self.outline.setValue(round(s.outline * 10))
        self.shadow.setValue(round(s.shadow * 10))
        self.box.setChecked(s.box)
        self.box_color.set_color(s.box_color)
        self.box_opacity.setValue(round(s.box_opacity * 100))
        self.position.setCurrentIndex(0 if s.position == "bottom" else 1)
        self.margin.setValue(s.margin)
        self._loading = False
        self._sync_presets(s)

    def _read(self) -> SubStyle:
        return with_changes(
            DEFAULT,
            font=self.font_box.currentFont().family(),
            size=self.size_box.value(),
            bold=self.bold.isChecked(),
            text_color=self.text_color.color,
            outline_color=self.outline_color.color,
            outline=self.outline.value() / 10,
            shadow=self.shadow.value() / 10,
            box=self.box.isChecked(),
            box_color=self.box_color.color,
            box_opacity=self.box_opacity.value() / 100,
            position=self.position.currentData(),
            margin=self.margin.value(),
        )

    def _sync_presets(self, s: SubStyle) -> None:
        for b in self.preset_group.buttons():
            b.setChecked(PRESETS[b.property("preset")] == s)
        self.box_color.setEnabled(s.box)
        self.box_opacity.setEnabled(s.box)

    def _apply_preset(self, name: str) -> None:
        self.chosen = PRESETS[name]
        self._load(self.chosen)
        self._render()

    def _changed(self, *_) -> None:
        if self._loading:
            return
        self.chosen = self._read()
        self._sync_presets(self.chosen)
        self.debounce.start()

    # ---------- preview (rendered off the UI thread; only the latest request is shown)

    def _render(self) -> None:
        if self.video is None:
            return
        self.request += 1
        n, style, at = self.request, self.chosen, float(self.scrub.value())

        def work() -> None:
            try:
                png = render_preview(self.video, at, self.sample_text, style, self.lang, out_width=1280)  # type: ignore[arg-type]
                self.bridge.rendered.emit(n, png)
            except Exception as e:
                self.bridge.failed.emit(n, tr("Preview unavailable: {e}", e=e))

        threading.Thread(target=work, daemon=True).start()

    def _scrubbed(self, sec: int) -> None:
        self.when.setText(fmt_time(sec))
        self.debounce.start()

    def _show_error(self, n: int, msg: str) -> None:
        if n == self.request:
            self.note.setText(msg)

    def _show_png(self, n: int, png: bytes) -> None:
        if n != self.request:
            return
        pix = QPixmap()
        pix.loadFromData(png)
        self.image.setPixmap(pix.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))  # fmt: skip

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.debounce.start()
