"""Recently opened videos, listed on the Home screen (recent.json + thumbs/ in the data folder).

A video's work lives next to it (Video.subloc.json). This list only remembers which videos were opened and when,
plus a short summary of each project, so Home draws at once without reading every project file. A summary is
read again only when its project file changed.
"""

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import data_dir
from .pipeline import project_path

LIMIT = 60


@dataclass
class Recent:
    video: str
    opened: float = 0.0  # time.time() when last opened
    target: str | None = None  # language the subtitles are in
    lines: int = 0
    translated: int = 0
    duration: float = 0.0  # seconds; 0 = not known yet
    stamp: float = 0.0  # modification time of the project file the summary was read from

    @property
    def path(self) -> Path:
        return Path(self.video)

    def status(self) -> str:
        """missing | new | heard | partial | done"""
        if not self.path.exists():
            return "missing"
        if not self.lines:
            return "new"
        if self.translated >= self.lines:
            return "done"
        return "partial" if self.translated else "heard"

    @property
    def progress(self) -> float:
        return min(1.0, self.translated / self.lines) if self.lines else 0.0


def _file() -> Path:
    return data_dir() / "recent.json"


def key(video: Path | str) -> str:
    return os.path.normcase(os.path.abspath(video))


def load() -> list[Recent]:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        names = {f.name for f in fields(Recent)}
        return [Recent(**{k: v for k, v in r.items() if k in names}) for r in raw]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def save(items: list[Recent]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(r) for r in items], ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def find(items: list[Recent], video: Path | str) -> Recent | None:
    k = key(video)
    return next((r for r in items if key(r.video) == k), None)


def touch(items: list[Recent], video: Path, duration: float = 0.0) -> list[Recent]:
    """Put `video` first, opened now, with a fresh summary of its project."""
    item = find(items, video) or Recent(str(video))
    item.video, item.opened = str(video), time.time()
    if duration:
        item.duration = duration
    summarize(item)
    return [item, *(r for r in items if r is not item)][:LIMIT]


def remove(items: list[Recent], video: Path | str) -> list[Recent]:
    k = key(video)
    return [r for r in items if key(r.video) != k]


def summarize(item: Recent) -> bool:
    """Re-read the project summary if the project file changed since last time. True when anything changed."""
    proj = project_path(item.path)
    try:
        stamp = proj.stat().st_mtime
    except OSError:
        stamp = 0.0
    if stamp == item.stamp:
        return False
    lines, translated, target = project_summary(proj) if stamp else (0, 0, None)
    item.lines, item.translated, item.target, item.stamp = lines, translated, target or item.target, stamp
    return True


def project_summary(proj: Path) -> tuple[int, int, str | None]:
    """(lines, translated lines, target language) of a project file; zeros when it can't be read."""
    try:  # plain JSON is enough for counting; building every Cue object would be slower
        data = json.loads(proj.read_text(encoding="utf-8"))
        cues = data.get("cues") or []
        return len(cues), sum(1 for c in cues if c.get("translation")), data.get("target_language")
    except (OSError, ValueError, AttributeError):
        return 0, 0, None


def thumb_path(video: Path | str) -> Path:
    return data_dir() / "thumbs" / (hashlib.sha1(key(video).encode("utf-8")).hexdigest()[:20] + ".jpg")


def make_thumb(video: Path) -> tuple[Path | None, float]:
    """Save a small frame from 10% into the video (at most a minute in). Returns (thumbnail or None for audio,
    duration). Runs ffmpeg: call it off the UI thread."""
    from .media import grab_frame, probe

    info = probe(video)
    if not info.width:
        return None, info.duration
    out = thumb_path(video)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(grab_frame(video, min(info.duration * 0.1, 60.0), width=320))
    return out, info.duration
