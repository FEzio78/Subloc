"""Subloc's own translation engine: a llama-server (llama.cpp) it starts and stops itself.

Speaks the same OpenAI-compatible API as LM Studio, so the translator code doesn't change; only where it
connects does. Started when translation begins (after Whisper has freed the graphics card), stopped before
the next transcription and when the app exits.
"""

import atexit
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from . import proc
from .config import data_dir
from .errors import SublocError


def _vendor() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "vendor" / "llama"


def _backend_dir(backend: str) -> Path | None:
    """vendor/llama/<backend> (source tree, and the installer's Vulkan build), or the data folder (the NVIDIA build,
    which the installed app downloads in Setup)."""
    for base in (_vendor(), data_dir() / "llama"):
        if (base / backend / "llama-server.exe").exists():
            return base / backend
    return None


def _nvidia_dirs() -> list[str]:
    """CUDA runtime DLLs installed with the app's Python packages (shared with Whisper)."""
    import site

    from .cuda import system_dirs

    downloaded = data_dir() / "cuda"  # the installed app: downloaded by Setup, or NVIDIA's own install
    dirs = [str(downloaded)] if downloaded.is_dir() else [str(d) for d in system_dirs()]
    for sp in site.getsitepackages():
        for name in ("cuda_runtime", "cublas"):
            d = Path(sp) / "nvidia" / name / "bin"
            if d.is_dir():
                dirs.append(str(d))
    return dirs


def available_backends() -> list[str]:
    return [b for b in ("cuda", "vulkan") if _backend_dir(b) is not None]


def pick_backend(has_nvidia: bool, has_other_gpu: bool) -> tuple[str, bool]:
    """(build, use_gpu). NVIDIA → CUDA; AMD/Intel → Vulkan; otherwise the processor."""
    backends = available_backends()
    if not backends:
        raise SublocError("The built-in translator isn't installed. Run Setup again, or use your own server.")
    if has_nvidia and "cuda" in backends:
        return "cuda", True
    if has_other_gpu and "vulkan" in backends:
        return "vulkan", True
    return backends[0], False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BuiltinEngine:
    def __init__(self, model: Path, backend: str = "auto", use_gpu: bool = True, parallel: int = 2,
                 ctx_per_request: int = 8192):  # fmt: skip
        self.model, self.backend, self.use_gpu = model, backend, use_gpu
        self.parallel, self.ctx = parallel, ctx_per_request
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self._lock = threading.Lock()
        atexit.register(self.stop)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure_running(self, timeout: float = 300.0) -> str:
        """Start if needed and wait until the model is loaded. Returns the server address."""
        with self._lock:
            if self.running():
                return self.url
            if not self.model.exists():
                raise SublocError(f"The translator model is missing ({self.model.name}). Run Setup again.")
            if self.backend == "auto":  # decided once, on first start (hardware check takes a moment)
                from .hardware import detect

                hw = detect()
                self.backend, self.use_gpu = pick_backend(bool(hw.nvidia), bool(hw.other_gpus))
            exe = (_backend_dir(self.backend) or _vendor() / self.backend) / "llama-server.exe"
            self.port = _free_port()
            log_dir = data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = log_dir / "translator-engine.log"
            env = dict(os.environ)
            env["PATH"] = ";".join([str(exe.parent), *_nvidia_dirs(), env.get("PATH", "")])
            cmd = [str(exe), "-m", str(self.model), "--host", "127.0.0.1", "--port", str(self.port),
                   "-ngl", "99" if self.use_gpu else "0", "-c", str(self.ctx * self.parallel),
                   "--parallel", str(self.parallel), "--jinja", "--no-webui"]  # fmt: skip
            log = self.log_path.open("w", encoding="utf-8", errors="replace")
            self.proc = proc.popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    raise SublocError(self._why_it_stopped(), self._log_tail())
                try:
                    if httpx.get(f"{self.url}/health", timeout=2).status_code == 200:
                        return self.url
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            self.stop()
            raise SublocError("The built-in translator took too long to start.", self._log_tail())

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _log_tail(self) -> str:
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        except OSError:
            return ""

    def _why_it_stopped(self) -> str:
        tail = self._log_tail().lower()
        if "out of memory" in tail or "failed to allocate" in tail:
            return ("Not enough graphics memory for the translator model. Close other programs using the GPU, "
                    "or choose a lighter setup in Setup.")  # fmt: skip
        if "failed to load model" in tail or "invalid" in tail:
            return "The translator model file couldn't be loaded. It may be damaged — run Setup again."
        return "The built-in translator stopped unexpectedly."
