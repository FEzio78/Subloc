"""Build the Windows app and its installer.

    .venv/Scripts/python tools/build.py                 # dist/Subloc/ and dist/Subloc-<version>-setup.exe
    .venv/Scripts/python tools/build.py --no-installer  # only the app folder (quicker, for testing)

1. vendor/ must hold llama.cpp, libmpv and ffmpeg (tools/fetch_vendor.py gets them, pinned and verified).
2. PyInstaller (installer/subloc.spec) makes dist/Subloc: Subloc.exe (the app) and subloc-cli.exe (command line,
   MCP server), sharing one folder. NVIDIA's CUDA libraries are left out: Setup downloads them on NVIDIA PCs.
3. Inno Setup (installer/subloc.iss) packs that folder into one installer: per-user, no admin rights, English and
   Arabic. Needs Inno Setup 6 (https://jrsoftware.org/isinfo.php).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def iscc() -> str:
    for c in (
        shutil.which("ISCC"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if c and Path(c).exists():
            return str(c)
    sys.exit("Inno Setup 6 is needed for the installer (https://jrsoftware.org/isinfo.php), or use --no-installer.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-installer", action="store_true", help="stop after the app folder")
    a = p.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    for part in ("llama", "mpv", "ffmpeg"):
        if not (ROOT / "vendor" / part).exists():
            sys.exit(f"vendor/{part} is missing: run .venv/Scripts/python tools/fetch_vendor.py first.")

    print(f"Subloc {version}: building the app (PyInstaller)…")
    spec = str(ROOT / "installer" / "subloc.spec")
    out = ["--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build")]
    subprocess.run([sys.executable, "-m", "PyInstaller", spec, "--noconfirm", *out], check=True, cwd=ROOT)
    app = ROOT / "dist" / "Subloc"
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1e9
    print(f"  {app} ({size:.1f} GB)")
    if a.no_installer:
        return

    print("Packing the installer (Inno Setup)…")
    subprocess.run([iscc(), f"/DAppVersion={version}", "/Q", str(ROOT / "installer" / "subloc.iss")], check=True)
    setup = ROOT / "dist" / f"Subloc-{version}-setup.exe"
    print(f"  {setup} ({setup.stat().st_size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
