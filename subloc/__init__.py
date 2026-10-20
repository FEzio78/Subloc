"""Subloc — local subtitles: transcribe, read burned-in subs, translate."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Keep model downloads inside the project folder unless the user overrides it.
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
