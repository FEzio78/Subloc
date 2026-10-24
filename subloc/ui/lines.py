"""The list of subtitle lines: drawn rows, a 'now' marker, and an inline editor for fixing a line."""

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPlainTextEdit,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from . import theme as t
from .i18n import tr
from .widgets import fmt_time


@dataclass
class Row:
    id: int
    start: float
    end: float
    text: str
    translation: str | None
    kind: str = "dialogue"
    speaker: str | None = None  # "S1"… (subloc.voices)
    gender: str | None = None  # "male" | "female" | None
    to: str | None = None  # who the translator thinks the line is spoken to: "S2" | "several"


class LinesModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.rows: list[Row] = []
        self.now_id: int | None = None
        self.mode = "both"  # both | original | translation
        self.rtl = True
        self.working = False  # True while translation runs: empty translation = "Translating…"

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.UserRole:
            return self.rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            r = self.rows[index.row()]
            return f"{r.text}\n{r.translation or ''}"
        return None

    def set_rows(self, rows: list[Row]) -> None:
        """Update in place when only translations changed (keeps scroll position and editor open)."""
        same_shape = len(rows) == len(self.rows) and all(a.id == b.id for a, b in zip(rows, self.rows, strict=True))
        if same_shape:
            changed = [i for i, (a, b) in enumerate(zip(rows, self.rows, strict=True)) if a != b]
            self.rows = rows
            if changed:
                self.dataChanged.emit(self.index(min(changed)), self.index(max(changed)))
            return
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def row_of(self, cue_id: int) -> int | None:
        return next((i for i, r in enumerate(self.rows) if r.id == cue_id), None)

    def set_now(self, cue_id: int | None) -> None:
        old = self.now_id
        self.now_id = cue_id
        for cid in (old, cue_id):
            i = self.row_of(cid) if cid is not None else None
            if i is not None:
                self.dataChanged.emit(self.index(i), self.index(i))


RLM, LRM = chr(0x200F), chr(0x200E)  # right-to-left / left-to-right marks
_RTL_SCRIPT = range(0x0590, 0x08FF)  # Hebrew, Arabic, Syriac, Thaana… (Arabic presentation forms aside)


def with_direction(text: str) -> str:
    """Wrap the text in direction marks matching its first strong letter. The trailing mark matters: end
    punctuation ("\u2026hour?") otherwise takes the surrounding layout's direction and jumps to the front."""
    for ch in text:
        if ch.isalpha():
            mark = RLM if ord(ch) in _RTL_SCRIPT else LRM
            return mark + text + mark
    return text


PAD_X, PAD_Y, TIME_W, GAP = 18, 10, 58, 10
VOICE = {"male": "man", "female": "woman"}  # shown under the speaker; tr() at drawing time


def voice_lines(row: Row) -> list[str]:
    """What the column under the time says about the voice: the speaker, then man / woman (each if known)."""
    out = [row.speaker] if row.speaker else []
    if row.gender in VOICE:
        out.append(tr(VOICE[row.gender]))
    if row.to:
        own = {"several": "to group", "man": "to a man", "woman": "to a woman"}  # "to a man": set by the user
        out.append(tr(own[row.to]) if row.to in own else tr("to {who}", who=row.to))
    return out


class LineDelegate(QStyledItemDelegate):
    edit_save = Signal(int, str)
    edit_retranslate = Signal(int)
    edit_play = Signal(int)
    edit_listener = Signal(int, str)  # cue id, "man" | "woman" | "several": translate again for that listener

    def __init__(self, model: LinesModel, view: "LinesView"):
        super().__init__(view)
        self.model = model
        self.view = view

    # ---------- layout helpers

    def _fonts(self) -> tuple[QFont, QFont, QFont]:
        return (
            t.font(8.5, family=t.MONO),
            t.font(9.5),
            t.font(11, family=t.ARABIC if self.model.rtl else t.SANS),
        )

    def _text_width(self, total: int) -> int:
        return max(100, total - PAD_X * 2 - TIME_W - GAP)

    def _height(self, row: Row, width: int, editing: bool) -> int:
        _time_font, f_src, f_tr = self._fonts()
        w = self._text_width(width)
        h = PAD_Y * 2
        if self.model.mode != "translation":
            h += QFontMetrics(f_src).boundingRect(QRect(0, 0, w, 10000), Qt.TextFlag.TextWordWrap, row.text).height()
        if self.model.mode != "original" and not editing:
            if self.model.mode == "both":
                h += 3
            tr_text = row.translation or tr("Translating…")
            h += QFontMetrics(f_tr).boundingRect(QRect(0, 0, w, 10000), Qt.TextFlag.TextWordWrap, tr_text).height()
        if editing:
            h += LineEditor.EXTRA
        return max(h, 40, PAD_Y * 2 + 20 + 13 * len(voice_lines(row)))

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        row = index.data(Qt.ItemDataRole.UserRole)
        editing = self.view.editing_id == row.id
        return QSize(option.rect.width(), self._height(row, self.view.viewport().width(), editing))

    # ---------- painting

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index) -> None:
        row: Row = index.data(Qt.ItemDataRole.UserRole)
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = row.id == self.model.now_id
        editing = self.view.editing_id == row.id
        if editing:
            p.fillRect(r, QColor(t.SURFACE_2))
        elif now:
            p.fillRect(r, t.qcolor(t.ACCENT, 0.09))
        if now or editing:
            p.fillRect(QRect(r.left(), r.top(), 2, r.height()), QColor(t.ACCENT))
        p.setPen(QColor("#1f2226"))
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())

        f_time, f_src, f_tr = self._fonts()
        p.setFont(f_time)
        p.setPen(QColor(t.ACCENT if now or editing else t.FAINT))
        mirrored = self.view.isRightToLeft()
        time_x = r.right() - PAD_X - TIME_W if mirrored else r.left() + PAD_X
        p.drawText(QRect(time_x, r.top() + PAD_Y + 2, TIME_W, 18),
                   Qt.AlignmentFlag.AlignRight if mirrored else Qt.AlignmentFlag.AlignLeft,
                   fmt_time(row.start))  # fmt: skip
        vy = r.top() + PAD_Y + 20
        for i, text in enumerate(voice_lines(row)):
            p.setPen(QColor(t.MUTED if i == 0 and row.speaker else t.FAINT))
            p.drawText(QRect(time_x, vy, TIME_W, 14),
                       Qt.AlignmentFlag.AlignRight if mirrored else Qt.AlignmentFlag.AlignLeft, text)  # fmt: skip
            vy += 13

        w = self._text_width(r.width())
        x = r.left() + PAD_X if mirrored else r.left() + PAD_X + TIME_W + GAP
        y = r.top() + PAD_Y
        if self.model.mode != "translation":
            p.setFont(f_src)
            p.setPen(QColor(t.MUTED if self.model.mode == "both" else t.TEXT))
            src_align = Qt.AlignmentFlag.AlignRight if mirrored else Qt.AlignmentFlag.AlignLeft
            br = p.fontMetrics().boundingRect(QRect(x, y, w, 10000), Qt.TextFlag.TextWordWrap, row.text)
            # The original keeps its own direction (English stays LTR inside the Arabic layout).
            p.drawText(QRect(x, y, w, br.height()), int(src_align) | int(Qt.TextFlag.TextWordWrap),
                       with_direction(row.text))  # fmt: skip
            y += br.height() + (3 if self.model.mode == "both" else 0)
        if self.model.mode != "original" and not editing:
            if row.translation:
                f = QFont(f_tr)
                f.setItalic(row.kind == "song")
                p.setFont(f)
                p.setPen(QColor("#d9cfa8" if row.kind == "song" else t.TEXT))
                opt = QTextOption()
                opt.setWrapMode(QTextOption.WrapMode.WordWrap)
                if self.model.rtl:
                    # AlignAbsolute: in right-to-left text, plain AlignRight is mirrored to the left
                    opt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
                    opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
                text = f"\u200f{row.translation}" if self.model.rtl else row.translation
                p.drawText(QRectF(x, y, w, r.bottom() - y), text, opt)
            else:
                f = t.font(9)
                f.setItalic(True)
                p.setFont(f)
                p.setPen(QColor(t.FAINT))
                p.drawText(QRect(x, y, w, 20), Qt.AlignmentFlag.AlignLeft,
                           tr("Translating…") if self.model.working else tr("Not translated"))  # fmt: skip
        p.restore()

    # ---------- inline editor

    def createEditor(self, parent, option, index):
        row: Row = index.data(Qt.ItemDataRole.UserRole)
        ed = LineEditor(parent, row, self.model.rtl)
        ed.save.connect(lambda text, cid=row.id: self.edit_save.emit(cid, text))
        ed.retranslate.connect(lambda cid=row.id: self.edit_retranslate.emit(cid))
        ed.play.connect(lambda cid=row.id: self.edit_play.emit(cid))
        ed.listener.connect(lambda who, cid=row.id: self.edit_listener.emit(cid, who))
        ed.cancel.connect(self.view.close_editor)
        return ed

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        mirrored = self.view.isRightToLeft()
        x = r.left() + PAD_X if mirrored else r.left() + PAD_X + TIME_W + GAP
        editor.setGeometry(x, r.bottom() - LineEditor.EXTRA - 2, self._text_width(r.width()), LineEditor.EXTRA)

    def setModelData(self, editor, model, index):  # saving happens through the Save button
        pass


class LineEditor(QWidget):
    EXTRA = 136  # extra row height while editing

    save = Signal(str)
    retranslate = Signal()
    play = Signal()
    cancel = Signal()
    listener = Signal(str)

    def __init__(self, parent, row: Row, rtl: bool):
        super().__init__(parent)
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(6)
        self.box = QPlainTextEdit(row.translation or "")
        self.box.setFont(t.font(11, family=t.ARABIC if rtl else t.SANS))
        self.box.setFixedHeight(58)
        if rtl:
            self.box.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            opt = self.box.document().defaultTextOption()
            opt.setTextDirection(Qt.LayoutDirection.RightToLeft)
            opt.setAlignment(Qt.AlignmentFlag.AlignRight)
            self.box.document().setDefaultTextOption(opt)
        lay.addWidget(self.box)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        actions = [
            (tr("Save"), "chipAccent", self._save),
            (tr("Translate again"), "chip", self.retranslate.emit),
            (tr("Play from here"), "chip", self.play.emit),
            (tr("Cancel"), "chip", self.cancel.emit),
        ]
        for text, name, sig in actions:
            b = QPushButton(text)
            b.setObjectName(name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(sig)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        # Wrong "you" (man / woman / several)? Say who the line is spoken to: it is translated again for them.
        who = QHBoxLayout()
        who.setSpacing(6)
        lab = QLabel(tr("Spoken to:"))
        lab.setStyleSheet(f"color: {t.MUTED};")
        who.addWidget(lab)
        for text, value in ((tr("a man"), "man"), (tr("a woman"), "woman"), (tr("several people"), "several")):
            b = QPushButton(text)
            b.setObjectName("chipAccent" if row.to == value else "chip")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(tr("Translate this line again as spoken to {who}", who=text))
            b.clicked.connect(lambda _=False, v=value: self.listener.emit(v))
            who.addWidget(b)
        who.addStretch()
        lay.addLayout(who)

    def _save(self) -> None:
        self.save.emit(self.box.toPlainText().strip())

    def showEvent(self, e):
        super().showEvent(e)
        self.box.setFocus()


class LinesView(QListView):
    line_clicked = Signal(int)

    def __init__(self, model: LinesModel):
        super().__init__()
        self.lines = model
        self.setModel(model)
        self.editing_id: int | None = None
        self.delegate = LineDelegate(model, self)
        self.setItemDelegate(self.delegate)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setUniformItemSizes(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMouseTracking(True)
        self.editable = False
        self.clicked.connect(self._on_click)

    def _on_click(self, index) -> None:
        row: Row = index.data(Qt.ItemDataRole.UserRole)
        self.line_clicked.emit(row.id)
        if self.editable and self.editing_id != row.id:
            self.open_editor(row.id)

    def open_editor(self, cue_id: int) -> None:
        self.close_editor()
        i = self.lines.row_of(cue_id)
        if i is None:
            return
        self.editing_id = cue_id
        idx = self.lines.index(i)
        self.lines.dataChanged.emit(idx, idx)  # re-measure with editor height
        self.doItemsLayout()
        self.openPersistentEditor(idx)
        self.scrollTo(idx)

    def close_editor(self) -> None:
        if self.editing_id is None:
            return
        i = self.lines.row_of(self.editing_id)
        self.editing_id = None
        if i is not None:
            idx = self.lines.index(i)
            self.closePersistentEditor(idx)
            self.lines.dataChanged.emit(idx, idx)
        self.doItemsLayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.doItemsLayout()  # wrapped heights depend on width
