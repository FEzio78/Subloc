"""Start helper programs (ffmpeg, ffprobe, llama-server, nvidia-smi…) without a console window.

The app runs under pythonw, which has no console. On Windows every console program it starts would then get
a black window of its own that flashes up and closes, many times per video. Every process Subloc starts goes
through `run` or `popen` here; tests/test_ui_guard.py fails on any start that skips them.
"""

import subprocess
from typing import Any

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # 0 off Windows: no effect


def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[Any]:
    """subprocess.run, never showing a console window."""
    return subprocess.run(cmd, creationflags=NO_WINDOW, **kw)


def popen(cmd: list[str], extra_flags: int = 0, **kw: Any) -> subprocess.Popen[Any]:
    """subprocess.Popen, never showing a console window. `extra_flags`: more creation flags (e.g. DETACHED_PROCESS
    for the updater's installer, which must outlive Subloc)."""
    return subprocess.Popen(cmd, creationflags=NO_WINDOW | extra_flags, **kw)
