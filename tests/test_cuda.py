"""The CUDA libraries Setup downloads for the installed app (subloc/cuda.py). No network: a fake wheel is served."""

import hashlib
import io
import tomllib
import zipfile
from pathlib import Path

import pytest

from subloc import cuda

ROOT = Path(__file__).resolve().parent.parent


def test_pins_match_uv_lock():
    """Setup downloads exactly the versions the app is developed and tested with."""
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {}
    for p in lock["package"]:
        for w in p.get("wheels", []):
            if p["name"].startswith("nvidia-") and "win_amd64" in w["url"]:
                locked[p["name"]] = (p["version"], w["url"], w["hash"].split(":")[1], w["size"])
    assert {w.name: (w.version, w.url, w.sha256, w.size) for w in cuda.WHEELS} == locked


def test_install_keeps_only_the_dlls(tmp_path, monkeypatch):
    monkeypatch.setattr(cuda, "data_dir", lambda: tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("nvidia/cublas/bin/cublas64_12.dll", b"dll")
        z.writestr("nvidia/cublas/include/cublas.h", b"header")
        z.writestr("nvidia_cublas_cu12-12.9.dist-info/METADATA", b"meta")
    data = buf.getvalue()
    wheel = cuda.Wheel("nvidia-test", "1", "https://example.invalid/nvidia_test-1-win_amd64.whl",
                       hashlib.sha256(data).hexdigest(), len(data))  # fmt: skip
    monkeypatch.setattr(cuda, "WHEELS", [wheel])

    def fake_download(url, dest, sha256, on_progress, cancel):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        on_progress(len(data), len(data))
        return dest

    monkeypatch.setattr(cuda, "download", fake_download)
    seen = []
    assert not cuda.installed()
    cuda.install(lambda done, total: seen.append((done, total)))
    assert sorted(p.name for p in (tmp_path / "cuda").iterdir()) == ["cublas64_12.dll", "installed.json"]
    assert cuda.installed() and seen[-1] == (len(data), len(data))
    assert not list((tmp_path / "downloads").iterdir())  # the package itself isn't kept


def test_not_needed_from_source():
    assert not cuda.needed()  # the source tree uses the packages in .venv


@pytest.mark.parametrize("frozen", [True])
def test_needed_when_installed_without_them(tmp_path, monkeypatch, frozen):
    monkeypatch.setattr(cuda, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(cuda, "FROZEN", frozen)
    monkeypatch.setattr(cuda, "system_dirs", lambda: [])  # a PC without NVIDIA's own CUDA install
    assert cuda.needed()


def test_llama_release_trimmed_to_the_server():
    keep = [n for n in ("llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "ggml-cuda.dll",
                        "ggml-cpu-zen4.dll", "libomp.dll", "LICENSE-LLVM-OpenMP", "llama-cli.exe",
                        "llama-bench-impl.dll", "llama-quantize.exe") if cuda.keep_llama_file(n)]  # fmt: skip
    assert keep == ["llama-server.exe", "llama-server-impl.dll", "llama-common.dll", "ggml-cuda.dll",
                    "ggml-cpu-zen4.dll", "libomp.dll", "LICENSE-LLVM-OpenMP"]  # fmt: skip


def test_cuda_installed_by_nvidia_is_used(tmp_path, monkeypatch):
    toolkit = tmp_path / "CUDA" / "v12.6" / "bin"
    toolkit.mkdir(parents=True)
    for n in ("cublas64_12.dll", "cudart64_12.dll"):
        (toolkit / n).write_bytes(b"x")
    cudnn = tmp_path / "NVIDIA" / "CUDNN" / "v9.12" / "bin" / "12.9"
    cudnn.mkdir(parents=True)
    monkeypatch.setattr(cuda, "data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(cuda, "FROZEN", True)
    for k in [k for k in __import__("os").environ if k.upper().startswith("CUDA_PATH")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    monkeypatch.setenv("CUDA_PATH_V12_6", str(tmp_path / "CUDA" / "v12.6"))
    assert cuda.system_dirs() == [] and cuda.needed()  # no cuDNN yet
    (cudnn / "cudnn64_9.dll").write_bytes(b"x")
    assert cuda.system_dirs() == [toolkit, cudnn] and not cuda.needed()


def test_whisper_found_in_the_standard_cache(tmp_path, monkeypatch):
    from subloc import asr

    monkeypatch.setenv("HF_HOME", str(tmp_path / "subloc-models"))
    monkeypatch.setattr(asr.Path, "home", classmethod(lambda cls: tmp_path))
    assert asr.local_model("large-v3") is None
    snap = (
        tmp_path / ".cache" / "huggingface" / "hub" / "models--Systran--faster-whisper-large-v3" / "snapshots" / "abc"
    )
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    assert asr.local_model("large-v3") == snap
