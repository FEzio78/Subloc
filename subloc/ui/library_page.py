"""The Library screen: the user's movie / series / anime folders as a tree, showing what still needs subtitles."""

import os
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..batch import natural
from ..langs import LANGS
from ..library import Library, Video
from ..recent import key
from . import icons
from . import theme as t
from .i18n import tr
from .pages import SegControl
from .widgets import fmt_time, label

ROLE = Qt.ItemDataRole.UserRole  # ("folder" | "video", path)
STATUS = {
    "done": ("Done", t.OK),
    "partial": ("{p}% translated", t.ACCENT),
    "heard": ("Not translated yet", t.MUTED),
    "other": ("Has {lang} subtitles", t.MUTED),
    "none": ("No subtitles", t.FAINT),
}


def fmt_size(n: float) -> str:
    """'1.4 GB', kept left-to-right in the Arabic interface (it would read 'GB 1.4' otherwise)."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "\u2066" + (f"{n:.1f} {unit}" if unit in ("GB", "TB") else f"{n:.0f} {unit}") + "\u2069"
        n /= 1024
    return ""


class _Node:
    def __init__(self, path: str):
        self.path = path
        self.folders: dict[str, _Node] = {}
        self.videos: list[Video] = []


class LibraryPage(QWidget):
    add_folder = Signal(str)
    refresh = Signal(str)  # a folder; "" = every library folder
    remove_root = Signal(str)
    watch = Signal(bool)
    open_video = Signal(str)
    translate = Signal(list)  # video paths to put in the queue
    reveal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("page")
        self.lib = Library()
        self.target = "ar"
        self.scope: dict[str, list[Video]] = {}  # folder key → every video under it
        self.built = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 18)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label("Library", "title"))
        head.addSpacing(4)
        self.summary = label("", "muted")
        head.addWidget(self.summary)
        head.addStretch()
        self.search = QLineEdit()
        self.search.addAction(icons.icon("search", t.FAINT), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setPlaceholderText(tr("Search"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._apply_filter)
        self.filter = SegControl([("all", "All"), ("missing", "Untranslated")])
        self.missing_only = False
        self.filter.changed.connect(self._set_filter)
        self.watch_box = QCheckBox("Watch for changes")
        self.watch_box.setObjectName("watch")
        self.watch_box.setToolTip("Update the list by itself when videos are added, removed or renamed in these "
                                  "folders. Network drives may not report changes.")  # fmt: skip
        self.watch_box.toggled.connect(self.watch.emit)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setIcon(icons.icon("refresh-cw", t.TEXT))
        self.refresh_btn.setToolTip("Read every library folder again")
        self.refresh_btn.clicked.connect(lambda: self.refresh.emit(""))
        self.add_btn = QPushButton("Add folder…")
        self.add_btn.setObjectName("primary")
        self.add_btn.setIcon(icons.icon("folder-plus", t.ACCENT_INK))
        self.add_btn.clicked.connect(self.choose_folder)
        for w in (self.search, self.filter, self.watch_box, self.refresh_btn, self.add_btn):
            head.addWidget(w)
        lay.addLayout(head)
        self.progress = label("", "muted")
        self.progress.hide()
        lay.addWidget(self.progress)

        self.body = QStackedWidget()
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(2)
        intro = ("Point Subloc at the folders where you keep movies, series or anime. It finds every video inside "
                 "them, in all subfolders, and shows which ones still need subtitles.")  # fmt: skip
        hero, about = label("Add your video folders", "hero"), label(intro, "muted")
        hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about.setWordWrap(True)
        about.setFixedWidth(560)
        el.addWidget(hero)
        centred = QHBoxLayout()  # centred with stretches: an aligned layout item would ignore the wrapped height
        centred.addStretch()
        centred.addWidget(about)
        centred.addStretch()
        el.addLayout(centred)
        el.addSpacing(10)
        first = QPushButton("Add folder…")
        first.setObjectName("primary")
        first.setIcon(icons.icon("folder-plus", t.ACCENT_INK))
        first.clicked.connect(self.choose_folder)
        el.addWidget(first, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addStretch(3)
        self.body.addWidget(empty)

        self.tree = QTreeWidget()
        self.tree.setObjectName("library")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("Name"), tr("Subtitles"), tr("Length"), tr("Size")])
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(20)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.itemSelectionChanged.connect(self._selected)
        self.body.addWidget(self.tree)
        lay.addWidget(self.body, 1)

        bar = QHBoxLayout()
        self.selection = label("", "muted")
        bar.addWidget(self.selection, 1)
        self.open_btn = QPushButton("Open")
        self.open_btn.setIcon(icons.icon("square-play", t.TEXT))
        self.open_btn.clicked.connect(self._open_selected)
        self.translate_btn = QPushButton("")
        self.translate_btn.setObjectName("primary")
        self.translate_btn.setIcon(icons.icon("captions", t.ACCENT_INK))
        self.translate_btn.clicked.connect(self._translate_selected)
        bar.addWidget(self.open_btn)
        bar.addWidget(self.translate_btn)
        lay.addLayout(bar)
        self.set_library(self.lib, self.target)

    # ---------- data

    def set_library(self, lib: Library, target: str) -> None:
        self.lib, self.target = lib, target
        self.watch_box.blockSignals(True)
        self.watch_box.setChecked(lib.watch)
        self.watch_box.blockSignals(False)
        self.body.setCurrentIndex(1 if lib.roots else 0)
        for w in (self.search, self.filter, self.watch_box, self.refresh_btn, self.add_btn):
            w.setVisible(bool(lib.roots))  # the empty page has its own Add folder button
        self._rebuild()
        done = sum(v.status(target) == "done" for v in lib.videos)
        self.summary.setText(tr("{n} videos · {d} done", n=len(lib.videos), d=done) if lib.roots else "")

    def set_progress(self, text: str) -> None:
        self.progress.setText(text)
        self.progress.setVisible(bool(text))
        self.refresh_btn.setEnabled(not text)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("Choose a library folder"))
        if folder:
            self.add_folder.emit(folder)

    def _rebuild(self) -> None:
        tree = self.tree
        expanded = set()
        selected = ""
        if self.built:
            for it in self._all_items():
                if it.isExpanded():
                    expanded.add(key(it.data(0, ROLE)[1]))
            cur = tree.currentItem()
            selected = key(cur.data(0, ROLE)[1]) if cur else ""
        scroll = tree.verticalScrollBar().value()
        tree.clear()
        self.scope = {}

        roots = sorted(self.lib.roots, key=natural)
        nodes = {key(r): _Node(r) for r in roots}
        for v in self.lib.videos:
            k = key(v.path)
            root = next((r for r in roots if k.startswith(key(r).rstrip(os.sep) + os.sep)), None)
            if root is None:
                continue
            node = nodes[key(root)]
            here = root
            for part in Path(os.path.relpath(v.path, root)).parts[:-1]:
                here = os.path.join(here, part)
                node = node.folders.setdefault(part, _Node(here))
            node.videos.append(v)

        bold = QFont(tree.font())
        bold.setWeight(QFont.Weight.DemiBold)

        def make(node: _Node, name: str) -> tuple[QTreeWidgetItem, list[Video]]:
            item = QTreeWidgetItem([name, "", "", ""])
            item.setData(0, ROLE, ("folder", node.path))
            item.setToolTip(0, node.path)
            item.setFont(0, bold)
            under: list[Video] = []
            children = []
            for sub in sorted(node.folders, key=natural):
                child, vids = make(node.folders[sub], sub)
                children.append(child)
                under += vids
            for v in sorted(node.videos, key=lambda v: natural(v.name)):
                children.append(self._video_item(v))
                under.append(v)
            item.addChildren(children)
            done = sum(v.status(self.target) == "done" for v in under)
            item.setText(1, tr("{d} of {n} done", d=done, n=len(under)) if under else tr("No videos found"))
            item.setForeground(1, QColor(t.OK if under and done == len(under) else t.MUTED))
            length = sum(v.duration for v in under)
            item.setText(2, fmt_time(length) if length else "")
            item.setText(3, fmt_size(sum(v.size for v in under)) if under else "")
            for c in (2, 3):
                item.setForeground(c, QColor(t.FAINT))
            self.scope[key(node.path)] = under
            return item, under

        for r in roots:
            item, _ = make(nodes[key(r)], r)
            tree.addTopLevelItem(item)
            item.setExpanded(not self.built or key(r) in expanded)
        if self.built:
            for it in self._all_items():
                k = key(it.data(0, ROLE)[1])
                if k in expanded:
                    it.setExpanded(True)
                if k == selected:
                    tree.setCurrentItem(it)
        self.built = True
        self._apply_filter()
        tree.verticalScrollBar().setValue(scroll)
        self._selected()

    def _video_item(self, v: Video) -> QTreeWidgetItem:
        status = v.status(self.target)
        text, color = STATUS[status]
        if status == "partial":
            text = tr(text, p=round(v.progress * 100))
        elif status == "other":
            lang = v.other_language(self.target)
            text = tr("Has {lang} subtitles", lang=tr(LANGS[lang])) if lang in LANGS else tr("Has subtitles")
        else:
            text = tr(text)
        item = QTreeWidgetItem([v.name, text, fmt_time(v.duration) if v.duration else "", fmt_size(v.size)])
        item.setData(0, ROLE, ("video", v.path))
        item.setToolTip(0, v.path)
        item.setForeground(1, QColor(color))
        for c in (2, 3):
            item.setForeground(c, QColor(t.FAINT))
        return item

    def _roots(self) -> list[QTreeWidgetItem]:
        items = (self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount()))
        return [it for it in items if it is not None]

    def _all_items(self) -> list[QTreeWidgetItem]:
        out: list[QTreeWidgetItem] = []
        stack = self._roots()
        while stack:
            it = stack.pop()
            out.append(it)
            stack += [c for c in (it.child(i) for i in range(it.childCount())) if c is not None]
        return out

    # ---------- filter

    def _set_filter(self, mode: str) -> None:
        self.missing_only = mode == "missing"
        self._apply_filter()

    def _apply_filter(self, *_) -> None:
        text = self.search.text().strip().lower()
        statuses = {key(v.path): v.status(self.target) for v in self.lib.videos} if self.missing_only else {}

        def show(item: QTreeWidgetItem, name_ok: bool) -> bool:
            kind, path = item.data(0, ROLE)
            name_ok = name_ok or not text or text in item.text(0).lower()
            if kind == "video":
                ok = name_ok and (not self.missing_only or statuses.get(key(path)) != "done")
            else:
                ok = False
                for child in (item.child(i) for i in range(item.childCount())):
                    if child is not None:
                        ok = show(child, name_ok) or ok
                if text and ok:
                    item.setExpanded(True)
            item.setHidden(not ok and (bool(text) or self.missing_only))
            return ok

        for root in self._roots():
            show(root, False)

    # ---------- selection and actions

    def _current(self) -> tuple[str, str] | None:
        it = self.tree.currentItem()
        return it.data(0, ROLE) if it and it.isSelected() else None

    def _videos_of(self, cur: tuple[str, str] | None) -> list[Video]:
        if cur is None:
            return self.lib.videos
        kind, path = cur
        if kind == "video":
            v = self.lib.index().get(key(path))
            return [v] if v else []
        return self.scope.get(key(path), [])

    def _missing(self, cur: tuple[str, str] | None) -> list[Video]:
        return [v for v in self._videos_of(cur) if v.status(self.target) != "done"]

    def _selected(self) -> None:
        cur = self._current()
        videos = self._videos_of(cur)
        missing = self._missing(cur)
        if cur is None:
            where = tr("Everything")
        else:
            where = os.path.basename(cur[1].rstrip("\\/")) or cur[1]
        self.selection.setText(tr("{where} · {d} of {n} done", where=where, d=len(videos) - len(missing),
                                  n=len(videos)) if videos else "")  # fmt: skip
        self.open_btn.setVisible(cur is not None and cur[0] == "video")
        if cur is not None and cur[0] == "video":
            self.translate_btn.setText(tr("Translate"))
        else:
            self.translate_btn.setText(tr("Translate {n} untranslated", n=len(missing)))
        self.translate_btn.setEnabled(bool(missing))
        self.translate_btn.setVisible(bool(videos))

    def _open_selected(self) -> None:
        cur = self._current()
        if cur and cur[0] == "video":
            self.open_video.emit(cur[1])

    def _translate_selected(self) -> None:
        missing = self._missing(self._current())
        if missing:
            self.translate.emit([v.path for v in missing])

    def _double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        kind, path = item.data(0, ROLE)
        if kind == "video":
            self.open_video.emit(path)

    def _menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        if item is None:
            return
        kind, path = item.data(0, ROLE)
        menu = QMenu(self)
        if kind == "video":
            menu.addAction(tr("Open"), lambda: self.open_video.emit(path))
        missing = self._missing((kind, path))
        if missing:
            text = tr("Translate") if kind == "video" else tr("Translate {n} untranslated", n=len(missing))
            menu.addAction(text, lambda: self.translate.emit([v.path for v in missing]))
        menu.addAction(tr("Show in folder"), lambda: self.reveal.emit(path))
        if kind == "folder":
            menu.addSeparator()
            menu.addAction(tr("Refresh this folder"), lambda: self.refresh.emit(path))
            if any(key(r) == key(path) for r in self.lib.roots):
                menu.addAction(tr("Remove from library"), lambda: self.remove_root.emit(path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))
