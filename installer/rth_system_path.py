# PyInstaller runtime hook: runs before anything else in the installed app (before Qt loads any DLL).
# Keep only Windows' and NVIDIA's folders on Subloc's own PATH. Other programs' folders can hold DLLs with the same
# names as ones Windows or Qt look up (an old zlib1.dll, OpenSSL, msvcr90.dll…); one of them crashed the app at
# start with "R6034" on a PC with a backup tool's folder on PATH. See also subloc/__init__.py.
import os

_windir = os.environ.get("SYSTEMROOT", r"C:\Windows").lower()
os.environ["PATH"] = os.pathsep.join(
    d
    for d in os.environ.get("PATH", "").split(os.pathsep)
    if d.lower().startswith(_windir) or "nvidia corporation" in d.lower()
)
