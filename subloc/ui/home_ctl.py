"""The Home screen's recent projects: the list, thumbnails, opening and forgetting.

Part of the main window (MainWindow in app.py inherits it).
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
)

from .. import recent
from .i18n import tr

if TYPE_CHECKING:
    from .app import MainWindow


class HomeMixin:
    _thumb_job: threading.Thread | None

    def _show_recent(self: "MainWindow") -> None:
        """Refresh summaries whose project file changed (edits, CLI runs), then redraw the list."""
        if self._outside_change("recent", recent._file()):
            self.recent = recent.load()
        changed = [r for r in self.recent if recent.summarize(r)]
        if changed:
            recent.save(self.recent)
        self.home.set_recent(self.recent)
        self._make_thumbs()

    def _remember(self: "MainWindow", video: Path, duration: float = 0.0) -> None:
        self.recent = recent.touch(self.recent, video, duration)
        recent.save(self.recent)
        self.home.set_recent(self.recent)
        self._make_thumbs()

    def _make_thumbs(self: "MainWindow") -> None:
        """Grab a frame for list rows without a thumbnail, one video after another, off the UI thread."""
        if self._thumb_job is not None:
            return
        todo = [Path(r.video) for r in self.recent if recent.key(r.video) not in self._thumb_tried
                and not recent.thumb_path(r.video).exists() and r.path.exists()]  # fmt: skip
        if not todo:
            return
        self._thumb_tried.update(recent.key(v) for v in todo)
        bus = self.bus

        def work() -> None:
            for v in todo:
                try:
                    _, duration = recent.make_thumb(v)
                    bus.thumb.emit(str(v), duration)
                except Exception:
                    pass  # unreadable file: the row keeps its placeholder
            bus.thumb.emit("", 0.0)  # finished

        job = threading.Thread(target=work, daemon=True)
        self._thumb_job = job
        job.start()

    def _on_thumb(self: "MainWindow", video: str, duration: float) -> None:
        if not video:
            self._thumb_job = None
            self._make_thumbs()  # videos added while it was working
            return
        item = recent.find(self.recent, video)
        if item and duration and not item.duration:
            item.duration = duration
            recent.save(self.recent)
        self.home.thumb_ready(video)

    def open_recent(self: "MainWindow", video: str) -> None:
        path = Path(video)
        if self.job is not None and self.video and recent.key(self.video) == recent.key(path):
            self.stack.setCurrentWidget(self.jobp)  # back to the video being worked on
            return
        if path.exists():
            self.open_video(path)
            return
        box = QMessageBox(QMessageBox.Icon.Warning, tr("File not found"),
                          tr("{name} was moved, renamed or deleted.", name=path.name), parent=self)  # fmt: skip
        find = box.addButton(tr("Find it…"), QMessageBox.ButtonRole.AcceptRole)
        forget = box.addButton(tr("Remove from list"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is forget:
            self.forget_recent(video)
        elif box.clickedButton() is find:
            start = next((str(d) for d in path.parents if d.exists()), "")
            found, _ = QFileDialog.getOpenFileName(self, tr("Find {name}", name=path.name), start)
            if found:
                self.recent = recent.remove(self.recent, video)
                self.open_video(Path(found))

    def forget_recent(self: "MainWindow", video: str) -> None:
        self.recent = recent.remove(self.recent, video)
        recent.save(self.recent)
        self.home.set_recent(self.recent)
