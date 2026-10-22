"""NVIDIA CUDA libraries for the installed app (Whisper and the built-in translator on NVIDIA graphics cards).

In the source tree they come as Python packages (nvidia-* in pyproject.toml, installed in .venv). The installed app
doesn't carry them: about 2 GB that only NVIDIA cards can use. Setup downloads the same packages from PyPI, checks
each against the sha256 pinned below (the versions in uv.lock; tests/test_cuda.py keeps the two in step) and keeps
only their DLLs, in <data folder>/cuda, where subloc.gpu and the built-in translator look for them.
"""

import json
import os
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import FROZEN
from .config import data_dir
from .download import download


@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    url: str
    sha256: str
    size: int  # bytes


WHEELS = [
    Wheel("nvidia-cublas-cu12", "12.9.2.10",
          "https://files.pythonhosted.org/packages/20/e2/fc9a0e985249d873150276d5afb02e39a66817fedbf1a385724393e505ed/nvidia_cublas_cu12-12.9.2.10-py3-none-win_amd64.whl",
          "623f43027d40d44ceadf0043f002bd25cf353e8f13ce90b9a87057019f560661", 553162896),
    Wheel("nvidia-cuda-nvrtc-cu12", "12.9.86",
          "https://files.pythonhosted.org/packages/52/de/823919be3b9d0ccbf1f784035423c5f18f4267fb0123558d58b813c6ec86/nvidia_cuda_nvrtc_cu12-12.9.86-py3-none-win_amd64.whl",
          "72972ebdcf504d69462d3bcd67e7b81edd25d0fb85a2c46d3ea3517666636349", 76408187),
    Wheel("nvidia-cuda-runtime-cu12", "12.9.79",
          "https://files.pythonhosted.org/packages/59/df/e7c3a360be4f7b93cee39271b792669baeb3846c58a4df6dfcf187a7ffab/nvidia_cuda_runtime_cu12-12.9.79-py3-none-win_amd64.whl",
          "8e018af8fa02363876860388bd10ccb89eb9ab8fb0aa749aaf58430a9f7c4891", 3591604),
    Wheel("nvidia-cudnn-cu12", "9.27.0.42",
          "https://files.pythonhosted.org/packages/aa/38/f856579877f7c1c5066e61182e7de7bc27bf35a78c8d1b0fa592e6985bc4/nvidia_cudnn_cu12-9.27.0.42-py3-none-win_amd64.whl",
          "06e9b0026f3bad97d2b58666330fabec04fe1672f776661ecb0ce0029c27f142", 743068852),
]  # fmt: skip

DOWNLOAD_GB = sum(w.size for w in WHEELS) / 1e9

# llama.cpp's NVIDIA build of the built-in translator (b11457, MIT; tools/fetch_vendor.py uses the same pin).
# Only for NVIDIA cards with the built-in translator, so the installer carries just the Vulkan/processor build.
LLAMA_CUDA_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11457/llama-b11457-bin-win-cuda-12.4-x64.zip"
LLAMA_CUDA_SHA256 = "c901dbb473c9472288e38ef06bf85e4e13d7de6bb24732b03dbe8aa05fcc483c"
LLAMA_CUDA_SIZE = 264528387


def cuda_dir() -> Path:
    return data_dir() / "cuda"


def _marker() -> Path:
    return cuda_dir() / "installed.json"


def installed() -> bool:
    """The pinned versions are unpacked (a newer Subloc with newer pins downloads again)."""
    try:
        have = json.loads(_marker().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return have == {w.name: w.version for w in WHEELS}


def system_dirs() -> list[Path]:
    """CUDA 12 and cuDNN 9 installed system-wide with NVIDIA's own installers (CUDA Toolkit, cuDNN): the folders
    holding cuBLAS + the CUDA runtime and cuDNN, or [] when either is missing. Then nothing needs downloading."""
    toolkits = sorted((v for k, v in os.environ.items() if k.upper().startswith("CUDA_PATH_V12")), reverse=True)
    cuda = next((Path(t) / "bin" for t in toolkits
                 if (Path(t) / "bin" / "cublas64_12.dll").exists() and (Path(t) / "bin" / "cudart64_12.dll").exists()),
                None)  # fmt: skip
    root = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "NVIDIA" / "CUDNN"
    cudnn = sorted(root.glob("v9.*/bin/12.*/cudnn64_9.dll")) + sorted(root.glob("v9.*/bin/cudnn64_9.dll"))
    return [cuda, cudnn[-1].parent] if cuda and cudnn else []


def needed() -> bool:
    """Only the installed app downloads them (the source tree has them in .venv), and only when the PC doesn't
    already have them."""
    return FROZEN and not installed() and not system_dirs()


def keep_llama_file(name: str) -> bool:
    """Of a llama.cpp release, what the translator needs: llama-server and the libraries (not the other tools)."""
    n = name.lower()
    if n.endswith("-impl.dll"):
        return n == "llama-server-impl.dll"
    return n.endswith(".dll") or n == "llama-server.exe" or n.startswith("license")


def llama_dir() -> Path:
    return data_dir() / "llama" / "cuda"


def llama_installed() -> bool:
    return (llama_dir() / "llama-server.exe").exists()


def install_llama(on_progress: Callable[[int, int], None] = lambda done, total: None,
                  cancel: threading.Event | None = None) -> None:  # fmt: skip
    """Download llama.cpp's NVIDIA build (resumable, verified) and keep what the translator needs."""
    archive = data_dir() / "downloads" / Path(LLAMA_CUDA_URL).name
    download(LLAMA_CUDA_URL, archive, LLAMA_CUDA_SHA256, on_progress, cancel)
    target = llama_dir()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if not info.is_dir() and keep_llama_file(name):
                (target / name).write_bytes(z.read(info))
    archive.unlink(missing_ok=True)


def install(on_progress: Callable[[int, int], None] = lambda done, total: None,
            cancel: threading.Event | None = None) -> None:  # fmt: skip
    """Download every package (resumable, verified) and keep its DLLs. on_progress(bytes done, bytes total)."""
    total = sum(w.size for w in WHEELS)
    done_before = 0
    cache = data_dir() / "downloads"
    target = cuda_dir()
    target.mkdir(parents=True, exist_ok=True)
    for w in WHEELS:
        wheel = cache / Path(w.url).name

        def progress(done: int, _total: int, before: int = done_before) -> None:
            on_progress(before + done, total)

        download(w.url, wheel, w.sha256, progress, cancel)
        with zipfile.ZipFile(wheel) as z:
            for info in z.infolist():
                name = Path(info.filename)
                if name.suffix.lower() == ".dll" and name.parent.name == "bin":  # nvidia/<part>/bin/*.dll
                    (target / name.name).write_bytes(z.read(info))
        wheel.unlink(missing_ok=True)
        done_before += w.size
    _marker().write_text(json.dumps({w.name: w.version for w in WHEELS}), encoding="utf-8")
    on_progress(total, total)
