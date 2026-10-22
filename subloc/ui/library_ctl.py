"""The Library: adding and removing folders, scans on a background thread, watching folders, and statuses
after Subloc worked on a video.

Part of the main window (MainWindow in app.py inherits it).
"""

import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QMessageBox,
)

from .. import library, recent
from .i18n import tr

if TYPE_CHECKING:
    from .app import MainWindow


class LibraryMixin:
    lib_job: threading.Thread | None

    def _library_changed(self: "MainWindow", save: bool = True) -> None:
        if save:
            library.save(self.lib)
        if self.stack.currentWidget() is self.libp:  # otherwise it's drawn when the page is shown
            self.libp.set_library(self.lib, self.home.tgt.currentData())

    def add_library_folder(self: "MainWindow", folder: str) -> None:
        folder = os.path.normpath(folder)
        if not library.add_root(self.lib, Path(folder)):
            msg = tr("{folder} is inside a folder that's already in the library.", folder=folder)
            self.toast(msg, "warning")
            return
        self._library_changed()
        self._scan(folder, deep=True)  # the first scan; after that only Refresh (or watching) reads it again

    def refresh_library(self: "MainWindow", folder: str) -> None:
        for f in [folder] if folder else self.lib.roots:
            self._scan(os.path.normpath(f), deep=True)

    def remove_library_root(self: "MainWindow", root: str) -> None:
        if QMessageBox.question(self, tr("Remove from library?"),
                                tr("{folder} won't be listed any more. Nothing is deleted from your disk.",
                                   folder=root)) != QMessageBox.StandardButton.Yes:  # fmt: skip
            return
        k = recent.key(root)
        self._scans = [s for s in self._scans if not library.inside(recent.key(s[0]), k)]
        library.remove_root(self.lib, root)
        self._library_changed()
        self._update_watcher()
        self.toast(tr("Removed from the library. Nothing was deleted from your disk."), "ok")

    def queue_from_library(self: "MainWindow", videos: list[str]) -> None:
        self.add_to_queue([Path(v) for v in videos])
        self.show_page("queue")

    def _scan(self: "MainWindow", folder: str, deep: bool) -> None:
        if (folder, deep) not in self._scans:
            self._scans.append((folder, deep))
        self._next_scan()

    def _next_scan(self: "MainWindow") -> None:
        while self.lib_job is None and self._scans:
            folder, deep = self._scans.pop(0)
            if os.path.isdir(folder):
                self._start_scan(folder, deep)
            elif deep:  # unplugged drive or deleted: keep what the index knows
                msg = tr("{folder} can't be reached. Is the drive connected?", folder=folder)
                self.toast(msg, "warning", secs=7)

    def _start_scan(self: "MainWindow", folder: str, deep: bool) -> None:
        name = os.path.basename(folder.rstrip("\\/")) or folder
        bus, cancel, lib, last = self.bus, self.lib_cancel, self.lib, [0.0]

        def progress(stage: str, n: int, total: int) -> None:
            if time.time() - last[0] > 0.2:
                last[0] = time.time()
                bus.lib_progress.emit(
                    tr("Reading {folder}… {n} videos found", folder=name, n=n) if stage == "files"
                    else tr("Checking the subtitles inside new videos… {n} of {total}", n=n, total=total))  # fmt: skip

        def work() -> None:
            try:
                bus.lib_scanned.emit(library.scan_folder(folder, lib, deep, cancel, progress if deep else None))
            except Exception:  # stopped, or the folder vanished midway
                bus.lib_scanned.emit(None)

        if deep:
            self.libp.set_progress(tr("Reading {folder}…", folder=name))
        job = threading.Thread(target=work, daemon=True)
        self.lib_job = job
        job.start()

    def _on_lib_scanned(self: "MainWindow", s: library.Scan | None) -> None:
        self.lib_job = None
        self.libp.set_progress("")
        if s is not None and any(library.inside(recent.key(s.folder), recent.key(r)) for r in self.lib.roots):
            library.apply(self.lib, s)  # (skipped when its folder was removed from the library meanwhile)
            self._library_changed()
            self._update_watcher()
            if s.deep:  # a scan the user asked for (watching reads folders quietly)
                name = os.path.basename(s.folder.rstrip("\\/")) or s.folder
                self.toast(tr("{folder}: {n} videos found", folder=name, n=len(s.videos)), "ok")
        self._next_scan()

    def set_library_watch(self: "MainWindow", on: bool) -> None:
        self.lib.watch = on
        library.save(self.lib)
        self._update_watcher()

    def _update_watcher(self: "MainWindow") -> None:
        want = {recent.key(f): f for f in self.lib.folders if os.path.isdir(f)} if self.lib.watch else {}
        have = {recent.key(f): f for f in self.watcher.directories()}
        if old := [p for k, p in have.items() if k not in want]:
            self.watcher.removePaths(old)
        if new := [p for k, p in want.items() if k not in have]:
            self.watcher.addPaths(new)

    def _on_dir_changed(self: "MainWindow", folder: str) -> None:
        self._changed.add(os.path.normpath(folder))
        self._change_timer.start()

    def _flush_changes(self: "MainWindow") -> None:
        for folder in sorted(self._changed):
            self._scan(folder, deep=False)  # its own files, plus any new subfolders
        self._changed.clear()

    def _library_video_done(self: "MainWindow", video: Path) -> None:
        """Subloc wrote subtitles or progress next to a video: update its line in the library."""
        if library.refresh_video(self.lib, video):
            self._library_changed()
