"""Built-in player: libmpv drawn into a Qt widget, showing the video with our subtitles.

mpv renders subtitles with libass, the same engine as the style preview and burn-in, so what plays here
is what the files look like in VLC/MPV. Position changes come back as a Qt signal (mpv calls back on its
own thread; the signal hops onto the UI thread).
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QSizePolicy, QWidget


def _vendor_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))  # frozen app or source tree
    return base / "vendor" / "mpv"


def available() -> bool:
    return (_vendor_dir() / "libmpv-2.dll").exists() or bool(_import_mpv())


_mpv_module = None


def _import_mpv():
    """Import python-mpv with our bundled libmpv on the DLL search path. None if it can't be loaded."""
    global _mpv_module
    if _mpv_module is not None:
        return _mpv_module
    d = _vendor_dir()
    if d.is_dir():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(d))
    try:
        import mpv  # type: ignore[import-untyped]
    except OSError:
        return None
    _mpv_module = mpv
    return mpv


class _Events(QObject):
    position = Signal(float)
    playing = Signal(bool)
    duration = Signal(float)


class Player(QWidget):
    """A native surface mpv draws into. Call load() once the widget is shown."""

    position = Signal(float)  # seconds
    playing = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)  # mpv needs a real window handle
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(160)
        self.setStyleSheet("background: #0a0b0d;")
        self.mpv = None
        self.video: Path | None = None
        self.events = _Events()
        self.events.position.connect(self.position.emit)
        self.events.playing.connect(self.playing.emit)

    def _ensure(self) -> bool:
        if self.mpv is not None:
            return True
        mpv = _import_mpv()
        if mpv is None:
            return False
        self.mpv = mpv.MPV(
            wid=str(int(self.winId())),
            vo="gpu",
            hwdec="auto-safe",
            keep_open="yes",
            idle="yes",
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            sub_auto="no",  # we add exactly our subtitle file
            sub_font="Segoe UI",
            pause=True,
            terminal=False,
            load_scripts=False,  # no OSC/ytdl Lua scripts: not needed, and they start LuaJIT
        )

        @self.mpv.property_observer("time-pos")
        def _pos(_name, value):
            if value is not None:
                self.events.position.emit(float(value))

        @self.mpv.property_observer("pause")
        def _pause(_name, value):
            self.events.playing.emit(not bool(value))

        return True

    # ---------- control

    def load(self, video: Path, subtitles: Path | None = None, start: float = 0.0) -> bool:
        if not self._ensure():
            return False
        self.video = video
        assert self.mpv is not None
        self.mpv.pause = True
        self.mpv.loadfile(str(video), start=f"{max(0.0, start):.3f}")
        if subtitles:
            self.mpv.wait_for_property("duration", lambda v: v is not None, timeout=10)
            self.set_subtitles(subtitles)
        return True

    def set_subtitles(self, path: Path) -> None:
        """Show this subtitle file (replaces the previous one); re-call after the file changes."""
        if self.mpv is None or not path.exists():
            return
        for tr in list(self.mpv.track_list or []):
            if tr.get("type") == "sub" and tr.get("external"):
                self.mpv.command("sub-remove", tr["id"])
        self.mpv.command("sub-add", str(path), "select")

    def toggle(self) -> None:
        if self.mpv is not None:
            self.mpv.pause = not self.mpv.pause

    def play(self) -> None:
        if self.mpv is not None:
            self.mpv.pause = False

    def pause(self) -> None:
        if self.mpv is not None:
            self.mpv.pause = True

    def seek(self, sec: float) -> None:
        if self.mpv is not None and self.video is not None:
            self.mpv.command("seek", f"{max(0.0, sec):.3f}", "absolute+exact")

    def is_playing(self) -> bool:
        return self.mpv is not None and not self.mpv.pause

    def snapshot(self, path: Path) -> None:
        """Save the current frame with subtitles (used by tests)."""
        if self.mpv is not None:
            self.mpv.command("screenshot-to-file", str(path), "subtitles")

    def shutdown(self) -> None:
        if self.mpv is not None:
            self.mpv.terminate()
            self.mpv = None

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)
