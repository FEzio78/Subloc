"""Burn subtitles into a new video (for phones/TVs that don't load subtitle files).

Renders the styled .ass with libass (same look as the preview and the built-in player). Uses the NVIDIA
encoder when it works, otherwise x264. Audio is re-encoded to AAC so the MP4 plays everywhere.
"""

import contextlib
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from . import proc
from .errors import SublocError
from .media import _bin, probe
from .models import Cue
from .style import SubStyle, write_ass


def _encoders() -> list[list[str]]:
    """Video encoder settings to try, best first."""
    out = proc.run([_bin("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    options = []
    if "h264_nvenc" in out:
        options.append(["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0"])
    options.append(["-c:v", "libx264", "-preset", "medium", "-crf", "20"])
    return options


def burn(
    video: Path,
    cues: list[Cue],
    style: SubStyle,
    lang: str,
    out: Path,
    on_progress: Callable[[float], None] = lambda f: None,
    cancel: threading.Event | None = None,
) -> Path:
    cancel = cancel or threading.Event()
    info = probe(video)
    duration = max(info.duration, 1.0)
    with tempfile.TemporaryDirectory(prefix="subloc-burn-") as tmp:
        # Bare file name + cwd=tmp: avoids filter-path escaping of drive letters and odd folder names.
        write_ass(cues, Path(tmp, "burn.ass"), style, True, lang, info.width or 1920, info.height or 1080)
        partial = out.with_name(out.stem + ".partial" + out.suffix)
        last_error = ""
        for enc in _encoders():
            cmd = [_bin("ffmpeg"), "-nostdin", "-y", "-v", "error", "-progress", "pipe:1", "-i", str(video.resolve()),
                   "-map", "0:v:0", "-map", "0:a:0?", "-vf", "subtitles=burn.ass", *enc, "-pix_fmt", "yuv420p",
                   "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(partial.resolve())]  # fmt: skip
            ff = proc.popen(cmd, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert ff.stdout is not None
            for line in ff.stdout:
                if cancel.is_set():
                    ff.kill()
                    break
                if line.startswith("out_time_us="):
                    with contextlib.suppress(ValueError):  # "N/A" before the first frame
                        on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / duration))
            ff.wait()
            if cancel.is_set():
                partial.unlink(missing_ok=True)
                raise SublocError("Stopped. No video was saved.")
            if ff.returncode == 0:
                shutil.move(partial, out)
                on_progress(1.0)
                return out
            last_error = (ff.stderr.read() if ff.stderr else "")[-400:]
            partial.unlink(missing_ok=True)  # e.g. NVIDIA encoder unavailable: try the next one
    raise SublocError("Couldn't make the video with subtitles.", last_error)
