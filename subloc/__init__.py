"""Subloc — local subtitles: transcribe, read burned-in subs, translate."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN = bool(getattr(sys, "frozen", False))  # the installed app (PyInstaller)
# Bundled programs and libraries (llama.cpp, libmpv, ffmpeg): next to the code when installed, vendor/ in the
# source tree (tools/fetch_vendor.py, tools/build.py fill it).
VENDOR = Path(getattr(sys, "_MEIPASS", ROOT)) / "vendor"


def default_data_dir() -> Path:
    """Where models, logs and settings live: SUBLOC_DATA when set (tests, a portable copy), %LOCALAPPDATA%/Subloc
    for the installed app, the project folder while developing (everything stays in one place)."""
    if os.environ.get("SUBLOC_DATA"):
        return Path(os.environ["SUBLOC_DATA"])
    if FROZEN:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Subloc"
    return ROOT


def _system_path_only() -> None:
    """The installed app takes nothing from the user's PATH: everything it needs is bundled, and other programs'
    folders on PATH can hold DLLs with the same names (old zlib1.dll, OpenSSL…) that crash it when a library loads
    one by name (seen: R6034 from a backup tool's folder). Only Windows and NVIDIA's tool folders stay; this
    changes Subloc's own process only."""
    windir = os.environ.get("SYSTEMROOT", r"C:\Windows").lower()
    keep = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if d.lower().startswith(windir) or "nvidia corporation" in d.lower()]  # fmt: skip
    os.environ["PATH"] = os.pathsep.join(keep)


if FROZEN and sys.platform == "win32":
    _system_path_only()

# Whisper models are downloaded into the data folder too, unless the user points HF_HOME elsewhere.
os.environ.setdefault("HF_HOME", str(default_data_dir() / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
