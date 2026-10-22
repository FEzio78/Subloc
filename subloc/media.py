"""ffmpeg / ffprobe helpers."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import VENDOR, proc
from .errors import MediaError

SAMPLE_RATE = 16000


def _bin(name: str) -> str:
    """ffmpeg / ffprobe: the copy that comes with Subloc, else the one on PATH."""
    bundled = VENDOR / "ffmpeg" / f"{name}.exe"
    path = str(bundled) if bundled.exists() else shutil.which(name)
    if not path:
        raise MediaError(
            f"{name} is missing. Subloc needs ffmpeg to read videos — reinstall Subloc, "
            f"or install ffmpeg and add it to PATH."
        )
    return path


# ISO 639-2 (container tags) → ISO 639-1 (Whisper / our codes)
ISO3 = {
    "jpn": "ja",
    "eng": "en",
    "kor": "ko",
    "rus": "ru",
    "tur": "tr",
    "ara": "ar",
    "chi": "zh",
    "zho": "zh",
    "spa": "es",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "ita": "it",
    "por": "pt",
    "hin": "hi",
    "tha": "th",
    "vie": "vi",
    "ind": "id",
    "fil": "tl",
    "tgl": "tl",
    "per": "fa",
    "fas": "fa",
    "ukr": "uk",
    "pol": "pl",
}
TEXT_SUBS = {"ass", "ssa", "subrip", "srt", "mov_text", "webvtt", "text"}


@dataclass
class Track:
    index: int  # position among streams of its type (ffmpeg 0:a:N / 0:s:N)
    lang: str | None  # ISO 639-1 if tagged (tags are often wrong — treat as a hint)
    title: str
    codec: str

    @property
    def is_text(self) -> bool:
        return self.codec in TEXT_SUBS


@dataclass
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    audio: list[Track]
    subtitles: list[Track]

    @property
    def has_audio(self) -> bool:
        return bool(self.audio)

    @property
    def text_subtitles(self) -> list[Track]:
        return [s for s in self.subtitles if s.is_text]


def _tracks(streams: list[dict], kind: str) -> list[Track]:
    out: list[Track] = []
    for s in (s for s in streams if s["codec_type"] == kind):
        tags = {k.lower(): v for k, v in s.get("tags", {}).items()}
        lang = tags.get("language", "").lower()
        out.append(
            Track(
                len(out),
                ISO3.get(lang, lang if len(lang) == 2 else None),
                tags.get("title", ""),
                s.get("codec_name", ""),
            )
        )
    return out


def probe(path: Path) -> MediaInfo:
    res = proc.run(
        [_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
    )
    try:
        data = json.loads(res.stdout)
        data["streams"]
    except (ValueError, KeyError) as e:
        raise MediaError(
            "This file couldn't be opened. It may be damaged, still downloading, or not a video.",
            res.stderr.decode(errors="replace")[-300:],
        ) from e
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    fps = None
    if video and video.get("avg_frame_rate", "0/0") != "0/0":
        num, den = video["avg_frame_rate"].split("/")
        fps = int(num) / int(den) if int(den) else None
    return MediaInfo(
        duration=float(data["format"].get("duration", 0)),
        width=video.get("width") if video else None,
        height=video.get("height") if video else None,
        fps=fps,
        audio=_tracks(data["streams"], "audio"),
        subtitles=_tracks(data["streams"], "subtitle"),
    )


def fingerprint(path: Path) -> str:
    """Cheap identity of a file's content: size + three 1 MB samples (start, middle, end). Saved work is
    reused only for the same fingerprint, so a video replaced under the same name (a re-download of a
    damaged file; copies keep their old date) is processed again instead of reusing the old transcript."""
    import hashlib

    size = path.stat().st_size
    h = hashlib.blake2b(str(size).encode(), digest_size=12)
    with path.open("rb") as f:
        for off in (0, max(0, size // 2 - 512 * 1024), max(0, size - 1024 * 1024)):
            f.seek(off)
            h.update(f.read(1024 * 1024))
    return h.hexdigest()


def subtitle_source(info: MediaInfo, target: str) -> int | None:
    """Built-in text subtitles to translate instead of listening (made by people: exact timing, fewer
    mistakes). Skips tracks already in the target language; the first other track wins."""
    for tr in info.text_subtitles:
        if tr.lang != target:
            return tr.index
    return None


def has_target_subtitles(info: MediaInfo, target: str) -> bool:
    return any(tr.lang == target for tr in info.text_subtitles)


def default_audio_track(info: MediaInfo) -> int:
    """Prefer the original-language track: dual-audio releases often put an English dub first."""
    if len(info.audio) > 1 and info.audio[0].lang == "en":
        other = next((t for t in info.audio[1:] if t.lang and t.lang != "en"), None)
        if other:
            return other.index
    return 0


def read_subtitles(path: Path, track: int) -> str:
    """Raw text of a text subtitle track: ASS stays ASS (keeps styles), everything else → SRT."""
    info = probe(path)
    codec = info.subtitles[track].codec
    fmt = ["-c:s", "copy", "-f", "ass"] if codec in ("ass", "ssa") else ["-f", "srt"]
    res = proc.run(
        [_bin("ffmpeg"), "-nostdin", "-v", "error", "-i", str(path), "-map", f"0:s:{track}", *fmt, "-"],
        capture_output=True,
    )
    if res.returncode and not res.stdout:
        raise MediaError("Couldn't read the subtitles inside this file.", res.stderr.decode(errors="replace")[-300:])
    return res.stdout.decode("utf-8", errors="replace")


def iter_frames(path: Path, fps: float, width: int, height: int):
    """Yield (time, gray uint8 HxW frame) sampled at `fps`, scaled to width x height."""
    ff = proc.popen(
        [
            _bin("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},scale={width}:{height}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        stdout=subprocess.PIPE,
    )
    assert ff.stdout is not None
    size = width * height
    i = 0
    try:
        while True:
            buf = ff.stdout.read(size)
            if len(buf) < size:
                break
            # fps filter emits frame i at t = i/fps (plus half-interval rounding); good enough for 4 fps.
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(height, width)
            i += 1
    finally:
        ff.stdout.close()
        ff.wait()


def grab_frame(path: Path, t: float, width: int | None = None) -> bytes:
    """Return one frame at time t as JPEG bytes (optionally scaled to `width`)."""
    vf = ["-vf", f"scale={width}:-2"] if width else []
    return proc.run(
        [
            _bin("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            *vf,
            "-q:v",
            "3",
            "-f",
            "image2",
            "-c:v",
            "mjpeg",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout


def _decode(path: Path, track: int, keep_sync: bool) -> subprocess.CompletedProcess:
    # aresample=async fills unreadable stretches with silence using the file's timestamps. Without it,
    # ffmpeg silently drops broken packets and every later subtitle shifts earlier (a damaged episode
    # decoded to 12 of its 25 minutes and its subtitles came out 3+ minutes early).
    sync = ["-af", "aresample=async=1:first_pts=0"] if keep_sync else []
    return proc.run(
        [_bin("ffmpeg"), "-nostdin", "-v", "error", "-err_detect", "ignore_err", "-i", str(path),
         "-map", f"0:a:{track}", *sync, "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True,
    )  # fmt: skip


@dataclass
class Audio:
    samples: np.ndarray  # 16 kHz mono float32, aligned with the video's timeline
    missing: float = 0.0  # share of the timeline that couldn't be decoded (damaged file)


def load_audio(path: Path, track: int = 0) -> Audio:
    """Decode an audio track to 16 kHz mono float32, staying in sync even when the file is damaged."""
    res = _decode(path, track, keep_sync=True)
    if not res.stdout:
        raise MediaError(
            "Couldn't read the sound from this file. It may be damaged.", res.stderr.decode(errors="replace")[-300:]
        )
    samples = np.frombuffer(res.stdout, np.int16).astype(np.float32) / 32768.0
    missing = 0.0
    if res.stderr.strip():
        # Decoding errors: measure how much was lost by decoding once more without the gap filling.
        raw = len(_decode(path, track, keep_sync=False).stdout) // 2
        missing = max(0.0, 1 - raw / max(len(samples), 1))
    return Audio(samples, missing)
