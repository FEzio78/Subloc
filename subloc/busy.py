"""One heavy job at a time on this PC: Subloc's window, its command line and its MCP server (agents) share the
graphics card, and two Whisper or translator runs at once would crowd it out.

An operating-system lock on a file in the data folder: it is released when the holder finishes, and also when
its process ends in any way (a crash can't leave Subloc locked). Who holds it is written next to it, so the
others can say "busy in Subloc's window: Episode 3".
"""

import contextlib
import json
import os
import sys
import time
from pathlib import Path
from typing import IO, Any

from .config import data_dir


def _paths() -> tuple[Path, Path]:
    return data_dir() / "busy.lock", data_dir() / "busy.json"


def _try_lock(f: IO[bytes]) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(f: IO[bytes]) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


class BusyLock:
    def __init__(self, who: str):
        self.who = who  # "Subloc's window", "the command line", "an agent (MCP)"
        self._f: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._f is not None

    def acquire(self, what: str = "", wait: float = 0.0, on_wait: Any = None) -> bool:
        """Take the lock; with `wait` > 0 keep trying for that many seconds (on_wait(holder) is called once)."""
        if self._f is not None:
            self.describe(what)
            return True
        lock, _ = _paths()
        lock.parent.mkdir(parents=True, exist_ok=True)
        f = open(lock, "a+b")  # noqa: SIM115 (kept open while held)
        deadline, told = time.monotonic() + wait, False
        while not _try_lock(f):
            if time.monotonic() >= deadline:
                f.close()
                return False
            if on_wait and not told:
                on_wait(holder())
                told = True
            time.sleep(1.0)
        self._f = f
        self.describe(what)
        return True

    def describe(self, what: str) -> None:
        """Say what the holder is doing (shown to whoever waits)."""
        _, info = _paths()
        data = {"who": self.who, "what": what, "pid": os.getpid(), "since": time.time()}
        with contextlib.suppress(OSError):
            info.write_text(json.dumps(data), encoding="utf-8")

    def release(self) -> None:
        if self._f is None:
            return
        _, info = _paths()
        with contextlib.suppress(OSError):
            info.unlink(missing_ok=True)
        _unlock(self._f)
        self._f.close()
        self._f = None


def holder() -> str:
    """Who is busy, in words ('' when nobody is or it can't be told)."""
    lock, info = _paths()
    if not lock.exists():
        return ""
    with open(lock, "a+b") as f:  # free? then nobody holds it, whatever busy.json says
        if _try_lock(f):
            _unlock(f)
            return ""
    try:
        d = json.loads(info.read_text(encoding="utf-8"))
        return f"{d.get('who', 'another Subloc')}" + (f": {d['what']}" if d.get("what") else "")
    except (OSError, ValueError):
        return "another Subloc"
