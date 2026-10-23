# PyInstaller recipe for the installed app (run by tools/build.py, not by hand).
# One folder, two programs sharing it: Subloc.exe (the app, no console) and subloc-cli.exe (command line, MCP).
# Bundled: Subloc's assets, llama.cpp (Vulkan), libmpv, ffmpeg, nemo-speech (all from vendor/, see tools/fetch_vendor.py).
# Not bundled: NVIDIA's CUDA libraries (~2 GB) — Setup downloads them on PCs with an NVIDIA card (subloc/cuda.py).
# ruff: noqa

import re
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

ROOT = Path(SPECPATH).parent
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
NUMS = tuple(int(n) for n in re.findall(r"\d+", VERSION)[:3]) + (0,)
ICON = str(ROOT / "subloc" / "assets" / "icon.ico")


def version_info(description: str, filename: str) -> VSVersionInfo:
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=NUMS, prodvers=NUMS),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "Subloc"),
                StringStruct("FileDescription", description),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", filename),
                StringStruct("LegalCopyright", "GPL-3.0-or-later"),
                StringStruct("OriginalFilename", filename),
                StringStruct("ProductName", "Subloc"),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [1033, 1200])]),
        ],
    )


datas = [(str(ROOT / "subloc" / "assets"), "subloc/assets")]
datas += collect_data_files("faster_whisper")  # its voice-detection model (silero_vad_*.onnx)
for part in ("mpv", "ffmpeg", "llama/vulkan", "nemo-speech"):
    if not (ROOT / "vendor" / part).exists():
        raise SystemExit(f"vendor/{part} is missing: run tools/fetch_vendor.py first")
datas += [(str(ROOT / "vendor" / "mpv"), "vendor/mpv"), (str(ROOT / "vendor" / "ffmpeg"), "vendor/ffmpeg")]
# NeMo-Speech.cpp (Vulkan build, ~60 MB): who speaks when (subloc/voices.py); its model comes as a download.
datas += [(str(ROOT / "vendor" / "nemo-speech"), "vendor/nemo-speech")]
# llama.cpp: the Vulkan build only (AMD, Intel, processor), and only llama-server + its libraries. The NVIDIA build
# is downloaded by Setup on NVIDIA PCs that use the built-in translator (subloc/cuda.py).
sys.path.insert(0, str(ROOT))
from subloc.cuda import keep_llama_file

datas += [(str(f), "vendor/llama/vulkan") for f in (ROOT / "vendor" / "llama" / "vulkan").iterdir()
          if keep_llama_file(f.name)]

EXCLUDES = ["tkinter", "unittest", "pydoc", "nvidia", "PyInstaller", "pytest", "mypy", "ruff"]


def no_cuda(binaries):
    """Drop NVIDIA's CUDA libraries if a hook picked them up (Setup downloads them where they are needed), copies of
    llama.cpp's libraries that the analysis found next to llama-server (they're in vendor/llama already), and Qt's
    software OpenGL (opengl32sw.dll, 20 MB: Subloc draws without OpenGL)."""
    names = ("cublas", "cudnn", "cudart", "nvrtc", "nvblas", "opengl32sw")
    top = ("llama", "ggml", "libomp", "mtmd")
    keep = []
    for b in binaries:
        dest, name = b[0].replace("\\", "/"), Path(b[0]).name.lower()
        if "nvidia" in dest.split("/")[0].lower() or any(name.startswith(n) for n in names):
            continue
        if "/" not in dest and name.startswith(top):
            continue
        keep.append(b)
    return keep


def analysis(script: str):
    a = Analysis([str(ROOT / "installer" / script)], pathex=[str(ROOT)], datas=datas, excludes=EXCLUDES,
                 hiddenimports=["PySide6.QtSvg"], runtime_hooks=[str(ROOT / "installer" / "rth_system_path.py")])
    a.binaries = no_cuda(a.binaries)
    return a


app = analysis("app_main.py")
cli = analysis("cli_main.py")

app_exe = EXE(
    PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="Subloc", console=False, icon=ICON,
    version=version_info("Subloc", "Subloc.exe"), upx=False,
)
cli_exe = EXE(
    PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="subloc-cli", console=True, icon=ICON,
    version=version_info("Subloc command line and MCP server", "subloc-cli.exe"), upx=False,
)
COLLECT(app_exe, app.binaries, app.datas, cli_exe, cli.binaries, cli.datas, name="Subloc", upx=False)
