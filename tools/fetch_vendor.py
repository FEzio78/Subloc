"""Download the third-party programs Subloc runs (not stored in git), pinned and checksum-verified.

    .venv/Scripts/python tools/fetch_vendor.py            # llama.cpp (CUDA + Vulkan), libmpv, ffmpeg, nemo-speech
    .venv/Scripts/python tools/fetch_vendor.py --only mpv

Puts them in vendor/, which the app and the installer use. Needs 7-Zip for the libmpv archive.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from subloc.cuda import LLAMA_CUDA_SHA256, LLAMA_CUDA_URL
from subloc.download import download

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"

PINNED = {
    # llama.cpp b11457 (2026-10-06), MIT — https://github.com/ggml-org/llama.cpp
    "llama-cuda": (LLAMA_CUDA_URL, LLAMA_CUDA_SHA256, "llama/cuda"),  # pin shared with Setup (subloc/cuda.py)
    "llama-vulkan": (
        "https://github.com/ggml-org/llama.cpp/releases/download/b11457/llama-b11457-bin-win-vulkan-x64.zip",
        "d01301582c711a69b9747b5984710d6ca99e57d95f680d3d33753cec570b4cb6",
        "llama/vulkan",
    ),
    # libmpv 2026-10-06 (shinchiro/mpv-winbuild-cmake), GPL — https://mpv.io
    "mpv": (
        "https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20261006/"
        "mpv-dev-x86_64-20261006-git-6c092d978b.7z",
        "bc0e016bdf6573bada824873d4746ab58d9bfac0ddd59c046f160312f81f9548",
        "mpv",
    ),
    # FFmpeg 9.0.2 "essentials" (gyan.dev), GPL-3.0 (x264, libass) — https://ffmpeg.org, https://www.gyan.dev/ffmpeg/
    "ffmpeg": (
        "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip",
        "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
        "ffmpeg",
    ),
    # NeMo-Speech.cpp v0.2.0 (NVIDIA), Apache-2.0, Vulkan build — https://github.com/NVIDIA/NeMo-Speech.cpp
    # Finds who speaks when (subloc.voices); the model itself is downloaded by Setup.
    "nemo-speech": (
        "https://github.com/NVIDIA/NeMo-Speech.cpp/releases/download/v0.2.0/nemo-speech-0.2.0-windows-x86_64-vulkan.zip",
        "edf15a04ba98740aa0ab75ae4681ac7ad0a488b22b35ce2cbebd10590bb1c1e1",
        "nemo-speech",
    ),
}


def _seven_zip() -> str:
    for c in (shutil.which("7z"), r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
        if c and Path(c).exists():
            return c
    sys.exit("7-Zip is needed to unpack libmpv (https://www.7-zip.org).")


def fetch(name: str) -> None:
    url, sha, target = PINNED[name]
    dest = VENDOR / target
    with tempfile.TemporaryDirectory(prefix="subloc-vendor-") as tmp:
        archive = Path(tmp) / url.rsplit("/", 1)[1]
        print(f"{name}: downloading {archive.name}…")
        last = [0]

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / max(total, 1))
            if pct >= last[0] + 10:
                last[0] = pct
                print(f"  {pct}%")

        download(url, archive, sha, progress)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        if name == "ffmpeg":  # only the two programs and the licence, flat
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    base = info.filename.rsplit("/", 1)[-1]
                    if info.filename.endswith(("/bin/ffmpeg.exe", "/bin/ffprobe.exe")) or base == "LICENSE":
                        (dest / base).write_bytes(z.read(info))
        elif name == "nemo-speech":  # the program and its DLLs flat, NVIDIA's licence + notices in licenses/
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    parts = info.filename.split("/")
                    if info.is_dir() or len(parts) < 3:
                        continue
                    if parts[1] == "bin":
                        (dest / parts[-1]).write_bytes(z.read(info))
                    elif parts[1:4] == ["share", "licenses", "nemo-speech"]:
                        out = dest / "licenses" / Path(*parts[4:])
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(z.read(info))
        elif archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
        else:
            out = Path(tmp) / "x"
            subprocess.run([_seven_zip(), "x", "-y", f"-o{out}", str(archive)], check=True, capture_output=True)
            shutil.copy2(out / "libmpv-2.dll", dest / "libmpv-2.dll")
    print(f"{name}: ready in {dest.relative_to(ROOT)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", choices=["llama", "mpv", "ffmpeg", "nemo-speech"], help="fetch just one of them")
    a = p.parse_args()
    for name in PINNED:
        if a.only is None or name.startswith(a.only):
            fetch(name)


if __name__ == "__main__":
    main()
