"""Windows power: keep the PC awake while Subloc works, and sleep or shut down after a queue when the user asks.

Keeping awake uses SetThreadExecutionState, which holds only while the calling thread lives: call it from the UI
thread. The screen may still turn off; only the system stays on.
"""

import ctypes
import sys

from . import proc

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def keep_awake(on: bool) -> None:
    if sys.platform == "win32":
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]


def sleep() -> None:
    """Sleep (not hibernate: rundll32 SetSuspendState passes wrong arguments and hibernates when it's enabled)."""
    if sys.platform == "win32":
        ctypes.windll.powrprof.SetSuspendState(False, False, False)  # type: ignore[attr-defined]


def shut_down() -> None:
    if sys.platform == "win32":
        proc.run(["shutdown", "/s", "/t", "0"])
