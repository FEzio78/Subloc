"""The queue (kept between sessions) and what goes with long work: the busy lock shared with the command line
and agents, keeping the PC awake, notifications, and sleeping or shutting down when it's done.

Part of the main window (MainWindow in app.py inherits it).
"""

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QSystemTrayIcon,
)

from .. import power
from ..batch import BatchReporter, Item, run_batch, save_queue
from ..busy import holder
from .i18n import tr
from .pages import select_data

if TYPE_CHECKING:
    from .app import MainWindow


class QueueMixin:
    queue_job: threading.Thread | None
    tray: QSystemTrayIcon | None

    def add_to_queue_dialog(self: "MainWindow") -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("Add videos"), "", "Videos (*.mp4 *.mkv *.avi *.mov *.webm *.m4v)"
        )
        if paths:
            self.add_to_queue([Path(p) for p in paths])

    def add_to_queue(self: "MainWindow", videos: list[Path]) -> None:
        known = {it.video for it in self.queue}
        new = [Item(v.resolve()) for v in videos if v.resolve() not in known]
        self.queue += new
        self._queue_changed()
        if new:
            self.toast(tr("Added {n} videos to the queue", n=len(new)), "ok")
        else:
            self.toast(tr("Those videos are already in the queue"), "info")

    def clear_queue(self: "MainWindow") -> None:
        self.queue = [it for it in self.queue if it.status not in ("done", "skipped", "failed")]
        self._queue_changed()

    def remove_from_queue(self: "MainWindow", i: int) -> None:
        if self.queue_job is None and 0 <= i < len(self.queue):  # a running queue tracks items by position
            del self.queue[i]
            self.queue_progress.clear()
            self._queue_changed()

    def stop_queue(self: "MainWindow") -> None:
        self.queue_cancel.set()  # (the event is replaced at every start: look it up now, not when wiring)

    def _queue_changed(self: "MainWindow") -> None:
        save_queue(self.queue)
        self._refresh_queue()

    def _refresh_queue(self: "MainWindow") -> None:
        active = {i: f for i, f in self.queue_progress.items()
                  if self.queue[i].status in ("listening", "translating")} if self.queue else {}  # fmt: skip
        self.queuep.set_items([(it.video.name, it.status, it.error) for it in self.queue], active)
        self.top.set_queue_count(sum(1 for it in self.queue if it.status not in ("done", "skipped")))

    def start_queue(self: "MainWindow") -> None:
        todo = [it.video for it in self.queue if it.status in ("waiting", "stopped", "failed")]
        if not todo or self.queue_job is not None:
            return
        if not self._take_gpu(tr("the queue")):
            return
        self._save()
        opt = self.options()
        opt.prefer_builtin_subs = True
        self.queue_cancel = threading.Event()
        index = {it.video: i for i, it in enumerate(self.queue)}
        bus = self.bus

        class R(BatchReporter):
            current = -1

            def item(self, i: int, item: Item) -> None:
                if item.status in ("listening", "translating"):
                    self.current = index[todo[i]]
                bus.queue_item.emit(index[todo[i]], item.status, item.error)

            def stage(self, name: str, frac: float, detail: str = "") -> None:
                if self.current >= 0 and name in ("transcribe", "translate"):
                    bus.queue_progress.emit(self.current, frac)

        def work() -> None:
            try:
                run_batch(todo, opt, R(), self.queue_cancel)
            finally:
                bus.queue_done.emit()

        self.queuep.set_running(True)
        job = threading.Thread(target=work, daemon=True)
        self.queue_job = job
        job.start()
        self._update_awake()
        self._tray_tip()

    def _on_queue_progress(self: "MainWindow", i: int, frac: float) -> None:
        self.queue_progress[i] = frac
        self._refresh_queue()

    def _on_queue_item(self: "MainWindow", i: int, status: str, error: str) -> None:
        self.queue_progress.pop(i, None)
        self.queue[i].status, self.queue[i].error = status, error
        self._queue_changed()
        self._tray_tip()
        if status in ("done", "failed", "stopped"):  # worked on: list it on Home
            self._remember(self.queue[i].video)
            self._library_video_done(self.queue[i].video)

    def _on_queue_done(self: "MainWindow") -> None:
        self.queue_job = None
        self.queuep.set_running(False)
        self._queue_changed()
        self._update_awake()
        if self.queue_cancel.is_set():  # stopped by the user: no message, no sleep or shutdown
            return
        done = sum(it.status in ("done", "skipped") for it in self.queue)
        failed = sum(it.status == "failed" for it in self.queue)
        self._notify(tr("Queue finished"), tr("{d} videos done · {f} failed", d=done, f=failed) if failed
                     else tr("All {d} videos are done.", d=done))  # fmt: skip
        action = self.queuep.when_done.currentData()
        if action in ("sleep", "shutdown"):
            self._after_queue(action)

    def _take_gpu(self: "MainWindow", what: str) -> bool:
        """The busy lock: one heavy job at a time on this PC, also across the command line and agents."""
        if self.busy.acquire(what):
            return True
        who = holder() or tr("the command line")
        who = "\u2068" + who + "\u2069"  # isolated: an English file name inside an Arabic sentence
        self.toast(tr("Another Subloc is working: {who}. Try again when it's done.", who=who), "warning", secs=7)
        return False

    def _update_awake(self: "MainWindow") -> None:
        """Windows mustn't fall asleep in the middle of a long queue (the screen may still turn off)."""
        working = self.job is not None or self.queue_job is not None
        power.keep_awake(working)
        if not working:
            self.busy.release()

    def _tray_icon(self: "MainWindow") -> QSystemTrayIcon | None:
        if self.tray is None and QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(self.windowIcon(), self)
            tray.messageClicked.connect(self._bring_to_front)
            tray.activated.connect(lambda *_: self._bring_to_front())
            self.tray = tray
        if self.tray is not None:
            self.tray.show()
        return self.tray

    def _tray_tip(self: "MainWindow") -> None:
        """The tray icon shows how far the queue is (hover it)."""
        tray = self._tray_icon()
        if tray is not None:
            done = sum(it.status in ("done", "skipped", "failed") for it in self.queue)
            tray.setToolTip(tr("Subloc · queue: {d} of {n} finished", d=done, n=len(self.queue)))

    def _notify(self: "MainWindow", title: str, text: str) -> None:
        """A Windows notification, plus the taskbar button flashing until the window is looked at."""
        tray = self._tray_icon()
        if tray is not None:
            tray.showMessage(title, text, self.windowIcon(), 15000)
        QApplication.alert(self)

    def _bring_to_front(self: "MainWindow") -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _after_queue(self: "MainWindow", action: str) -> None:
        """Sleep or shut down after a finished queue, with a minute to change one's mind."""
        sleep = action == "sleep"
        text = ("The queue is done. The PC will go to sleep in {n} seconds." if sleep
                else "The queue is done. The PC will shut down in {n} seconds.")  # fmt: skip
        box = QMessageBox(QMessageBox.Icon.Information, tr("Queue finished"), "", parent=self)
        now = box.addButton(tr("Sleep now") if sleep else tr("Shut down now"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
        left, fired = [self.countdown_secs], [False]
        timer = QTimer(box, interval=1000)

        def tick() -> None:
            if left[0] <= 0:
                fired[0] = True
                timer.stop()
                box.close()
                return
            box.setText(tr(text, n=left[0]))
            left[0] -= 1

        tick()
        timer.timeout.connect(tick)
        timer.start()
        self._bring_to_front()
        box.exec()
        timer.stop()
        select_data(self.queuep.when_done, "nothing")  # once only: the next queue doesn't inherit it
        if fired[0] or box.clickedButton() is now:
            self._save()
            save_queue(self.queue)
            if sleep:
                power.sleep()
            else:
                if self.engine is not None:
                    self.engine.stop()
                power.shut_down()
