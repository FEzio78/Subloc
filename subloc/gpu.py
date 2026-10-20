"""Make the CUDA libraries installed inside the venv (nvidia-* wheels) visible on Windows."""

import os
import sys
from pathlib import Path

_done = False


def setup_cuda_dlls() -> None:
    global _done
    if _done or sys.platform != "win32":
        return
    _done = True
    import site

    for sp in site.getsitepackages():
        nvidia = Path(sp) / "nvidia"
        if not nvidia.is_dir():
            continue
        for bin_dir in nvidia.glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]


def cuda_available() -> bool:
    setup_cuda_dlls()
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False
