"""The Library: folders of movies, series or anime that Subloc keeps an index of (library.json in the data folder).

Adding a folder scans it once, every subfolder included. After that the index changes only when the user presses
Refresh, or, if they turn watching on, when a folder changes on disk (then only that folder is read again).

For each video the index keeps what decides whether it still needs subtitles: subtitle files next to it (language
from the name: Ep 01.ar.srt, Ep 01.ara.srt, Ep 01.Arabic.ass), subtitle tracks inside it (read with ffprobe, and
again only when the file changed) and Subloc's own progress (its project file).
"""

import json
import os
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .batch import VIDEO_EXT, natural, skip_dir
from .config import data_dir
from .langs import LANGS
from .media import ISO3
from .pipeline import project_path
from .recent import key, project_summary

LIBRARY_EXT = VIDEO_EXT - {".mp3", ".wav", ".m4a"}  # music next to films isn't something to subtitle
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
LANG_WORDS = {name.lower(): code for code, name in LANGS.items()}  # "arabic" → "ar"


class Stopped(Exception):
    pass


def natural_path(path: str) -> list:
    """Sort key: Season 2/Ep 10 after Season 1/Ep 9."""
    return [natural(part) for part in Path(path).parts]


def lang_code(tag: str) -> str | None:
    """'ar', 'ara', 'Arabic', 'ar-SA' → 'ar'; anything else (forced, sdh, mixed…) → None."""
    t = tag.lower().replace("_", "-").split("-")[0]
    if len(t) == 2 and t in LANGS:  # LANGS also holds "mixed", Subloc's own source mode
        return t
    return ISO3.get(t) or LANG_WORDS.get(t)


@dataclass
class Video:
    path: str
    size: int = 0
    mtime: float = 0.0
    subs: list[str] = field(default_factory=list)  # subtitle files next to it: languages ("" = not in the name)
    inner: list[str] | None = None  # subtitle tracks inside: languages ("" = untagged); None = not read yet
    inner_text: bool = False  # a track inside is text, so Subloc can translate from it (pictures it can't)
    duration: float = 0.0
    probed: str = ""  # "size:mtime" the tracks were read at
    lines: int = 0  # Subloc's project: lines, translated lines, target language, file time read at
    translated: int = 0
    target: str | None = None
    stamp: float = 0.0

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def status(self, target: str) -> str:
        """done | partial | heard | other | none — for subtitles in `target`."""
        if target in self.subs or target in (self.inner or ()):
            return "done"
        if self.lines and self.target == target:
            if self.translated >= self.lines:
                return "done"
            if self.translated:
                return "partial"
        if self.lines:
            return "heard"
        return "other" if self.subs or self.inner_text else "none"

    @property
    def progress(self) -> float:
        return min(1.0, self.translated / self.lines) if self.lines else 0.0

    def other_language(self, target: str) -> str | None:
        """A language it already has subtitles in (not `target`): translating from those is quick and exact."""
        return next((lang for lang in [*self.subs, *(self.inner or [])] if lang and lang != target), None)


@dataclass
class Library:
    roots: list[str] = field(default_factory=list)
    watch: bool = False
    videos: list[Video] = field(default_factory=list)
    folders: list[str] = field(default_factory=list)  # every folder read (the ones watched when watching is on)

    def index(self) -> dict[str, Video]:
        return {key(v.path): v for v in self.videos}


def _file() -> Path:
    return data_dir() / "library.json"


def load() -> Library:
    try:
        raw = json.loads(_file().read_text(encoding="utf-8"))
        names = {f.name for f in fields(Video)}
        videos = [Video(**{k: v for k, v in d.items() if k in names}) for d in raw.get("videos", [])]
        return Library(list(raw.get("roots", [])), bool(raw.get("watch")), videos, list(raw.get("folders", [])))
    except (OSError, ValueError, TypeError, AttributeError):
        return Library()


def save(lib: Library) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(lib), ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def inside(path_key: str, folder_key: str) -> bool:
    """Is the path (a key()) the folder or anything in it?"""
    return path_key == folder_key or path_key.startswith(folder_key.rstrip(os.sep) + os.sep)


def add_root(lib: Library, folder: Path) -> bool:
    """Add a folder to the library. False when it is already inside one (it's indexed already)."""
    k = key(folder)
    if any(inside(k, key(r)) for r in lib.roots):
        return False
    lib.roots = [r for r in lib.roots if not inside(key(r), k)] + [str(folder)]  # absorbs folders inside it
    return True


def remove_root(lib: Library, root: str) -> None:
    """Forget a folder (nothing on disk is touched)."""
    k = key(root)
    lib.roots = [r for r in lib.roots if key(r) != k]
    lib.videos = [v for v in lib.videos if not inside(key(v.path), k)]
    lib.folders = [d for d in lib.folders if not inside(key(d), k)]


# ---------------------------------------------------------------- reading folders


def _sidecars(names: list[str]) -> dict[str, set[str]]:
    """Video name (lower case, no extension) → languages of the subtitle files named after it."""
    out: dict[str, set[str]] = {}
    for n in names:
        base, ext = os.path.splitext(n)
        if ext.lower() not in SUB_EXT:
            continue
        out.setdefault(base.lower(), set()).add("")  # Ep 01.srt
        parts = base.split(".")
        for k in (1, 2):  # Ep 01.ar.srt, Ep 01.ar.forced.srt
            if len(parts) > k:
                code = lang_code(parts[-k])
                if code or k == 1:  # Ep 01.mixed.srt: subtitles, language not in the name
                    out.setdefault(".".join(parts[:-k]).lower(), set()).add(code or "")
    return out


def _video(path: str, st: os.stat_result, subs: list[str], old: Video | None) -> Video:
    v = Video(path, st.st_size, st.st_mtime, subs)
    if old:  # keep what was read before; the tracks are read again only if the file changed
        v.inner, v.inner_text, v.duration, v.probed = old.inner, old.inner_text, old.duration, old.probed
        v.lines, v.translated, v.target, v.stamp = old.lines, old.translated, old.target, old.stamp
    try:
        stamp = project_path(Path(path)).stat().st_mtime
    except OSError:
        stamp = 0.0
    if stamp != v.stamp:
        v.lines, v.translated, v.target = project_summary(project_path(Path(path))) if stamp else (0, 0, None)
        v.stamp = stamp
    return v


def scan(folder: Path, old: dict[str, Video], descend: Callable[[str], bool] = lambda d: True,
         cancel: threading.Event | None = None, found: Callable[[int], None] | None = None,
         ) -> tuple[list[Video], list[str]]:  # fmt: skip
    """Videos in `folder` and in the subfolders `descend` allows (all, by default), and the folders read."""
    videos: list[Video] = []
    folders: list[str] = []
    stack = [str(folder)]
    while stack:
        if cancel and cancel.is_set():
            raise Stopped
        here = stack.pop()
        try:
            entries = list(os.scandir(here))
        except OSError:  # gone, or no permission
            continue
        folders.append(here)
        files = [e for e in entries if e.is_file()]
        subs = _sidecars([e.name for e in files])
        for e in files:
            stem, ext = os.path.splitext(e.name)
            if ext.lower() not in LIBRARY_EXT:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            videos.append(_video(e.path, st, sorted(subs.get(stem.lower(), ())), old.get(key(e.path))))
        stack += [e.path for e in entries
                  if e.is_dir(follow_symlinks=False) and not skip_dir(e.name) and descend(e.path)]  # fmt: skip
        if found:
            found(len(videos))
    return videos, folders


def needs_tracks(v: Video) -> bool:
    return v.probed != f"{v.size}:{v.mtime}"


def read_tracks(v: Video) -> None:
    """Subtitle tracks inside the file and its length (ffprobe)."""
    from .media import probe

    try:
        info = probe(Path(v.path))
        v.inner = sorted({t.lang or "" for t in info.subtitles})
        v.inner_text = any(t.is_text for t in info.subtitles)
        v.duration = info.duration
    except Exception:  # unreadable or still downloading: try again when it changes
        v.inner, v.inner_text = [], False
    v.probed = f"{v.size}:{v.mtime}"


@dataclass
class Scan:
    folder: str
    deep: bool  # True: everything under `folder` was read; False: its own files and any new subfolders
    videos: list[Video]
    folders: list[str]


def scan_folder(folder: str, lib: Library, deep: bool = True, cancel: threading.Event | None = None,
                progress: Callable[[str, int, int], None] | None = None) -> Scan:  # fmt: skip
    """Read a folder (for a background thread; `apply` the result on the main one). progress(stage, done, total):
    stage 'files' while listing, 'tracks' while reading subtitle tracks of new or changed videos."""
    known = {key(d) for d in lib.folders}
    old = lib.index()
    descend: Callable[[str], bool] = (lambda d: True) if deep else (lambda d: key(d) not in known)
    videos, folders = scan(Path(folder), old, descend, cancel,
                           (lambda n: progress("files", n, 0)) if progress else None)  # fmt: skip
    todo = [v for v in videos if needs_tracks(v)]
    for i, v in enumerate(todo):
        if cancel and cancel.is_set():
            raise Stopped
        if progress:
            progress("tracks", i, len(todo))
        read_tracks(v)
    return Scan(folder, deep, videos, folders)


def apply(lib: Library, s: Scan) -> None:
    """Put a scan's result into the index, replacing what it held for that folder."""
    f = key(s.folder)
    if s.deep:
        lib.videos = [v for v in lib.videos if not inside(key(v.path), f)]
        lib.folders = [d for d in lib.folders if not inside(key(d), f)]
    else:  # only this folder's own files were read again; subfolders that disappeared are dropped
        gone = [k for k in map(key, lib.folders) if os.path.dirname(k) == f and not os.path.isdir(k)]
        lib.videos = [v for v in lib.videos if os.path.dirname(key(v.path)) != f
                      and not any(inside(key(v.path), g) for g in gone)]  # fmt: skip
        lib.folders = [d for d in lib.folders if not any(inside(key(d), g) for g in gone)]
    have_v, have_f = {key(v.path) for v in lib.videos}, {key(d) for d in lib.folders}
    lib.videos += [v for v in s.videos if key(v.path) not in have_v]
    lib.folders += [d for d in s.folders if key(d) not in have_f]


def refresh_video(lib: Library, video: Path) -> bool:
    """Read again the folder of a video Subloc just worked on (its new subtitle files, its progress), quickly and
    without ffprobe. False when the video isn't in the library."""
    if not any(inside(key(video), key(r)) for r in lib.roots):
        return False
    apply(lib, Scan(str(video.parent), False, *scan(video.parent, lib.index(), lambda d: False)))
    return True
