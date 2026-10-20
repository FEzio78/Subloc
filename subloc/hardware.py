"""What this PC can run: graphics card + memory, RAM, free disk. Used to recommend a setup."""

import ctypes
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Hardware:
    nvidia: str | None  # card name when an NVIDIA GPU with a working driver is present
    vram_gb: float  # NVIDIA video memory (0 when none)
    other_gpus: list[str]  # AMD / Intel adapters (usable through Vulkan)
    ram_gb: float
    cores: int

    @property
    def summary(self) -> str:
        gpu = f"{self.nvidia} ({self.vram_gb:.0f} GB)" if self.nvidia else (self.other_gpus[0] if self.other_gpus else
                                                                           "no graphics card found")  # fmt: skip
        return f"{gpu} · {self.ram_gb:.0f} GB RAM · {self.cores} cores"


def _nvidia() -> tuple[str | None, float]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, 0.0
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW).stdout  # fmt: skip
        name, mem = out.strip().splitlines()[0].rsplit(",", 1)
        return name.strip(), float(mem) / 1024
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None, 0.0


def _other_gpus() -> list[str]:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        ).stdout  # fmt: skip
    except (OSError, subprocess.TimeoutExpired):
        return []
    skip = ("nvidia", "virtual", "remote", "basic display", "parsec", "meta")
    return [n.strip() for n in out.splitlines() if n.strip() and not any(s in n.lower() for s in skip)]


def _ram_gb() -> float:
    if sys.platform != "win32":
        return 0.0

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]  # fmt: skip

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))  # type: ignore[attr-defined]
    return stat.ullTotalPhys / 1024**3


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def detect() -> Hardware:
    import os

    name, vram = _nvidia()
    return Hardware(name, vram, _other_gpus(), _ram_gb(), os.cpu_count() or 1)


def free_disk_gb(path: Path) -> float:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free / 1024**3
