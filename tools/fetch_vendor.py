"""Download the third-party programs Subloc runs (not stored in git), pinned and checksum-verified.

    .venv/Scripts/python tools/fetch_vendor.py            # llama.cpp (CUDA + Vulkan) and libmpv
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

from subloc.download import download

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"

PINNED = {
    # llama.cpp b11457 (2026-10-06), MIT — https://github.com/ggml-org/llama.cpp
    "llama-cuda": (
        "https://github.com/ggml-org/llama.cpp/releases/download/b11457/llama-b11457-bin-win-cuda-12.4-x64.zip",
        "c901dbb473c9472288e38ef06bf85e4e13d7de6bb24732b03dbe8aa05fcc483c",
        "llama/cuda",
    ),
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
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                z.extractall(dest)
        else:
            out = Path(tmp) / "x"
            subprocess.run([_seven_zip(), "x", "-y", f"-o{out}", str(archive)], check=True, capture_output=True)
            shutil.copy2(out / "libmpv-2.dll", dest / "libmpv-2.dll")
    print(f"{name}: ready in {dest.relative_to(ROOT)}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", choices=["llama", "mpv"], help="fetch just one of them")
    a = p.parse_args()
    for name in PINNED:
        if a.only is None or name.startswith(a.only):
            fetch(name)


if __name__ == "__main__":
    main()
