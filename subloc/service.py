"""Subloc without its window: what the command line (subloc.cli) and the MCP server for agents (subloc.mcp_server)
share.

- settings(): the choices made in the app (subtitle language, speech model, translator, style…), so a command
  does what the window would do; anything can be overridden per call.
- Jobs: work that takes minutes (subtitles for videos, re-translating lines, burn-in, reading a library folder)
  runs one job after another on a worker thread, under the busy lock shared with the window, with progress to poll.
- JSON-ready descriptions of videos, their lines, folders and the library.
"""

import glob
import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import library, recent
from .batch import BatchReporter, Item, find_videos, run_batch
from .busy import BusyLock, holder
from .config import Config
from .pipeline import Cancelled, Options, project_path, retranslate_lines, run, update_line
from .style import DEFAULT, PRESETS, SubStyle


def version() -> str:
    try:
        from importlib.metadata import version as installed

        return installed("subloc")
    except Exception:  # not installed as a package: the source tree's pyproject.toml says it
        import tomllib

        from . import ROOT

        try:
            return str(tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"])
        except (OSError, ValueError, KeyError):
            return "unknown"


SPEECH_QUALITY = {"best": "large-v3", "balanced": "medium", "light": "small"}


# ---------------------------------------------------------------- settings


@dataclass
class Settings:
    target: str = "ar"
    source: str | None = None  # None = detect; "mixed" = changes during the video
    asr_model: str = "large-v3"
    llm_model: str | None = None  # translator on a server: model id (None = the one loaded there)
    parallel: int = 2
    glossary: bool = True
    voices: bool = True  # speakers and voices (Settings → Speakers and voices)
    scene_pass: bool = False  # read each scene first to find who is spoken to (Settings → Who is spoken to)
    style: SubStyle | None = None  # None = the default look (plain .srt)
    provider: str = "server"  # "builtin" (Subloc runs llama-server) | "server" (LM Studio, Ollama…)
    server_url: str = "http://localhost:1234"
    builtin_model: Path | None = None


def settings() -> Settings:
    """The app's current choices (config.json + the window's saved settings)."""
    cfg = Config.load()
    st = Settings(asr_model=cfg.speech_model, provider=cfg.provider, server_url=cfg.server_url,
                  builtin_model=cfg.builtin_model_path() if cfg.provider == "builtin" else None)  # fmt: skip
    try:
        from PySide6.QtCore import QSettings

        q = QSettings("Subloc", "Subloc")

        def val(k: str) -> str | None:
            v = q.value(k)
            return None if v in (None, "", "@Invalid()") else str(v)

        st.target = val("target") or st.target
        st.source = val("source")
        st.asr_model = val("speech") or st.asr_model
        st.llm_model = val("model")
        st.parallel = max(1, min(4, int(val("parallel") or 2)))
        st.glossary = (val("glossary") or "true").lower() != "false"
        st.voices = (val("voices") or "true").lower() != "false"
        st.scene_pass = (val("scene_pass") or "false").lower() == "true"
        raw = val("style")
        style = SubStyle.from_dict(json.loads(raw)) if raw else DEFAULT
        st.style = None if style == DEFAULT else style
    except Exception:  # no saved window settings (or unreadable): config.json and defaults
        pass
    return st


def style_named(name: str | None, st: Settings) -> SubStyle | None:
    """A preset by name ('none' = plain), or the app's current style when no name is given."""
    if not name:
        return st.style
    if name.lower() == "none":
        return None
    for preset, style in PRESETS.items():
        if preset.lower() == name.lower():
            return None if style == DEFAULT else style
    raise ValueError(f"No style called {name!r}. Styles: {', '.join(PRESETS)}, none")


def make_options(st: Settings, **overrides: Any) -> Options:
    from .engine import BuiltinEngine

    builtin = st.builtin_model if st.provider == "builtin" else None
    engine = BuiltinEngine(builtin, parallel=st.parallel) if builtin else None
    opt = Options(
        target=st.target, source=st.source, asr_model=st.asr_model, llm_model=None if engine else st.llm_model,
        llm_url=st.server_url, engine=engine, parallel=st.parallel, auto_glossary=st.glossary, style=st.style,
        voices=st.voices, scene_pass=st.scene_pass,
        prefer_builtin_subs=True,
    )  # fmt: skip
    return replace(opt, **overrides)


def translator_status(st: Settings) -> dict:
    if st.provider == "builtin":
        ok = bool(st.builtin_model and st.builtin_model.exists())
        return {"kind": "built-in", "model": st.builtin_model.stem if st.builtin_model else None, "ready": ok,
                "problem": "" if ok else "The built-in translator isn't installed: run Setup in the app."}  # fmt: skip
    from .llm import LMStudio

    try:
        models = LMStudio(st.server_url, timeout=4).list_models()
    except Exception:
        return {"kind": "server", "url": st.server_url, "ready": False,
                "problem": f"No translator answers at {st.server_url}: start LM Studio's server."}  # fmt: skip
    loaded = next((m.id for m in models if m.loaded), None)
    chosen = st.llm_model or loaded
    return {"kind": "server", "url": st.server_url, "model": chosen, "loaded": loaded, "ready": bool(chosen),
            "available": [m.id for m in models],
            "problem": "" if chosen else "LM Studio runs but has no model loaded: load one, or pick one."}  # fmt: skip


def settings_report(st: Settings) -> dict:
    style = next((n for n, s in PRESETS.items() if s == st.style), "Custom") if st.style else "Classic"
    return {"target": st.target, "source": st.source or "auto", "speech_model": st.asr_model,
            "translator": st.provider, "parallel": st.parallel, "name_list": st.glossary,
            "style": style}  # fmt: skip


# ---------------------------------------------------------------- describing things


def video_entry(path: Path, tracks: bool = True) -> library.Video:
    """What the library would know about this video (subtitle files, Subloc's progress; tracks inside if asked)."""
    videos, _ = library.scan(path.parent, {}, lambda d: False)
    v = next((v for v in videos if recent.key(v.path) == recent.key(path)), None)
    if v is None:
        raise FileNotFoundError(f"Not a video Subloc can read: {path}")
    if tracks:
        library.read_tracks(v)
    return v


def subtitle_files(video: Path) -> list[str]:
    """Subtitle files next to the video that carry its name (Video.ar.srt, Video.en.srt, Video.ar.ass…)."""
    pattern = glob.escape(str(video.with_suffix(""))) + ".*"
    return sorted(p for p in glob.glob(pattern) if Path(p).suffix.lower() in (".srt", ".ass", ".ssa", ".vtt"))


def status_text(v: library.Video, target: str) -> str:
    s = v.status(target)
    if s == "partial":
        return f"{round(v.progress * 100)}% translated"
    if s == "other":
        lang = v.other_language(target)
        return f"has {lang} subtitles" if lang else "has subtitles"
    return {"done": "done", "heard": "transcribed, not translated", "none": "no subtitles"}[s]


def video_report(path: Path, target: str) -> dict:
    from .media import probe

    path = path.resolve()
    info = probe(path)
    v = video_entry(path, tracks=False)
    return {
        "path": str(path), "duration": round(info.duration, 1), "size": v.size,
        "audio_tracks": [{"number": t.index + 1, "language": t.lang, "title": t.title} for t in info.audio],
        "subtitle_tracks": [{"number": t.index + 1, "language": t.lang, "title": t.title, "text": t.is_text}
                            for t in info.subtitles],
        "subtitle_files": subtitle_files(path),
        "target": target, "status": _with_tracks(v, info).status(target), "status_text": status_text(v, target),
        "lines": v.lines, "translated": v.translated, "project_language": v.target,
    }  # fmt: skip


def _with_tracks(v: library.Video, info: Any) -> library.Video:
    v.inner = sorted({t.lang or "" for t in info.subtitles})
    v.inner_text = any(t.is_text for t in info.subtitles)
    return v


def read_lines(video: Path, offset: int = 0, limit: int = 200) -> dict:
    from .models import Project

    if not video.exists():
        raise FileNotFoundError(f"Not found: {video}")
    path = project_path(video.resolve())
    if not path.exists():
        raise FileNotFoundError(f"Subloc hasn't made subtitles for this video yet: {video}")
    proj = Project.load(path)
    lines = proj.cues[offset : offset + limit]
    return {"video": str(video.resolve()), "language": proj.language, "target": proj.target_language,
            "total": len(proj.cues), "offset": offset,
            "speakers": proj.meta.get("voices", {}).get("speakers", {}),
            "lines": [{"id": c.id, "start": round(c.start, 2), "end": round(c.end, 2), "text": c.text,
                       "translation": c.translation, "speaker": c.speaker, "gender": c.gender, "to": c.to}
                      for c in lines]}  # fmt: skip


def edit_line(video: Path, line_id: int, text: str, st: Settings) -> dict:
    """Correct one translated line by hand; the subtitle files are written again."""
    proj = update_line(video, line_id, text, make_options(st))
    c = next(c for c in proj.cues if c.id == line_id)
    return {"id": c.id, "text": c.text, "translation": c.translation, "files": subtitle_files(video.resolve())}


def folder_report(folder: Path, target: str, missing_only: bool = False, limit: int = 500) -> dict:
    """Every video under a folder with its status, from the files alone (quick: no ffprobe)."""
    videos, folders = library.scan(folder, {})
    rows = [v for v in videos if not missing_only or v.status(target) != "done"]
    rows.sort(key=lambda v: library.natural_path(v.path))
    return {"folder": str(folder.resolve()), "target": target, "videos": len(videos), "folders": len(folders),
            "done": sum(v.status(target) == "done" for v in videos), "shown": min(len(rows), limit),
            "items": [{"path": v.path, "status": v.status(target), "status_text": status_text(v, target)}
                      for v in rows[:limit]]}  # fmt: skip


def library_report(target: str, missing_only: bool = False, folder: str | None = None, limit: int = 500) -> dict:
    lib = library.load()
    vids = [v for v in lib.videos if folder is None or library.inside(recent.key(v.path), recent.key(folder))]
    rows = [v for v in vids if not missing_only or v.status(target) != "done"]
    rows.sort(key=lambda v: library.natural_path(v.path))
    return {"folders": lib.roots, "watching": lib.watch, "target": target, "videos": len(vids),
            "done": sum(v.status(target) == "done" for v in vids), "shown": min(len(rows), limit),
            "items": [{"path": v.path, "status": v.status(target), "status_text": status_text(v, target),
                       "duration": round(v.duration, 1)} for v in rows[:limit]]}  # fmt: skip


# ---------------------------------------------------------------- jobs


@dataclass
class JobVideo:
    path: str
    status: str = "waiting"  # as in the queue: waiting | listening | listened | translating | done | skipped |
    # failed | stopped
    error: str = ""
    progress: float = 0.0
    files: list[str] = field(default_factory=list)


@dataclass
class Job:
    id: str
    kind: str  # subtitles | transcribe | retranslate | burn | scan
    title: str
    videos: list[JobVideo] = field(default_factory=list)
    status: str = "queued"  # queued | waiting (another Subloc is busy) | running | done | failed | stopped
    stage: str = ""
    progress: float = 0.0
    error: str = ""
    result: dict = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    finished: float = 0.0
    cancel: threading.Event = field(default_factory=threading.Event)
    work: Callable[["Job"], None] | None = None

    @property
    def over(self) -> bool:
        return self.status in ("done", "failed", "stopped")

    def note(self, msg: str) -> None:
        self.log = [*self.log[-40:], msg]

    def report(self) -> dict:
        return {"job_id": self.id, "kind": self.kind, "title": self.title, "status": self.status,
                "stage": self.stage, "progress": round(self.progress, 3), "error": self.error,
                "videos": [vars(v) for v in self.videos], "result": self.result,
                "seconds": round((self.finished or time.time()) - self.created)}  # fmt: skip


class Jobs:
    """Runs jobs one after another (the graphics card takes one at a time), on a worker thread."""

    def __init__(self, who: str, on_log: Callable[[Job, str], None] | None = None):
        self.lock = BusyLock(who)
        self.on_log = on_log
        self.items: dict[str, Job] = {}
        self._todo: list[Job] = []
        self._wake = threading.Condition()
        self._thread: threading.Thread | None = None

    def submit(self, kind: str, title: str, work: Callable[[Job], None], videos: list[Path] | None = None) -> Job:
        job = Job(uuid.uuid4().hex[:8], kind, title, [JobVideo(str(v)) for v in videos or []], work=work)
        self.items[job.id] = job
        with self._wake:
            self._todo.append(job)
            self._wake.notify()
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.items[job_id]
        job.cancel.set()
        if job.status == "queued":
            job.status, job.finished = "stopped", time.time()
        return job

    def wait(self, job: Job, poll: float = 0.25, on_tick: Callable[[Job], None] | None = None) -> Job:
        while not job.over:
            time.sleep(poll)
            if on_tick:
                on_tick(job)
        return job

    def _run(self) -> None:
        while True:
            with self._wake:
                while not self._todo:
                    self._wake.wait()
                job = self._todo.pop(0)
            if job.over:
                continue
            while not job.cancel.is_set() and not self.lock.acquire(job.title):
                job.status, job.stage = "waiting", f"waiting: Subloc is busy ({holder() or 'another Subloc'})"
                time.sleep(2)
            if job.cancel.is_set():
                job.status, job.finished = "stopped", time.time()
                continue
            job.status, job.stage = "running", ""
            try:
                assert job.work is not None
                job.work(job)
                if job.status == "running":
                    job.status = "stopped" if job.cancel.is_set() else "done"
            except (Cancelled, library.Stopped):
                job.status = "stopped"
            except Exception as e:
                job.status, job.error = "failed", str(e) or type(e).__name__
            finally:
                self.lock.release()
                job.finished = time.time()
                if job.status == "done":
                    job.progress = 1.0

    def log(self, job: Job, msg: str) -> None:
        job.note(msg)
        if self.on_log:
            self.on_log(job, msg)


def submit_subtitles(jobs: Jobs, paths: list[Path], st: Settings, translate: bool = True, **overrides: Any) -> Job:
    """Subtitles for videos and folders (every subfolder): listen (or read built-in subtitles), then translate.
    With translate=False only the original-language subtitles are made."""
    videos = find_videos(paths)
    if not videos:
        raise FileNotFoundError("No videos found there.")
    kind = "subtitles" if translate else "transcribe"
    title = videos[0].name if len(videos) == 1 else f"{len(videos)} videos"

    def work(job: Job) -> None:
        opt = make_options(st, **overrides)
        current = [-1]

        class R(BatchReporter):
            def item(self, i: int, item: Item) -> None:
                jv = job.videos[i]
                jv.status, jv.error = item.status, item.error
                if item.status in ("listening", "translating"):
                    current[0] = i
                if item.status in ("done", "skipped", "listened"):
                    jv.progress = 1.0 if item.status != "listened" else 0.5
                _overall()

            def stage(self, name: str, frac: float, detail: str = "") -> None:
                job.stage = name
                i = current[0]
                if i >= 0:
                    first = name in ("audio", "transcribe") and translate
                    job.videos[i].progress = frac * 0.5 if first else (0.5 + frac * 0.5 if translate else frac)
                    _overall()

            def log(self, msg: str) -> None:
                jobs.log(job, msg)

            def warn(self, msg: str) -> None:
                jobs.log(job, "warning: " + msg)

        def _overall() -> None:
            job.progress = sum(v.progress for v in job.videos) / max(1, len(job.videos))

        try:
            if translate:
                run_batch(videos, opt, R(), job.cancel)
            else:
                _transcribe(videos, opt, R(), job)
        finally:
            if opt.engine is not None:
                opt.engine.stop()
            _after(job, videos, opt.target)

    return jobs.submit(kind, title, work, videos)


def _transcribe(videos: list[Path], opt: Options, rep: BatchReporter, job: Job) -> None:
    from .asr import unload_model

    try:
        for i, v in enumerate(videos):
            if job.cancel.is_set():
                rep.item(i, Item(v, "stopped"))
                continue
            rep.item(i, Item(v, "listening"))
            try:
                run(v, replace(opt, transcribe_only=True, keep_asr_loaded=True), rep, job.cancel)
                rep.item(i, Item(v, "done"))
            except Cancelled:
                rep.item(i, Item(v, "stopped"))
            except Exception as e:
                rep.item(i, Item(v, "failed", str(e) or type(e).__name__))
    finally:
        unload_model()


def _after(job: Job, videos: list[Path], target: str) -> None:
    """Files written, the job's outcome, and the app's lists (Home, Library) told about the work."""
    for jv, v in zip(job.videos, videos, strict=True):
        jv.files = subtitle_files(v)
    worked = [v for jv, v in zip(job.videos, videos, strict=True) if jv.status in ("done", "failed", "stopped")]
    if worked:
        items = recent.load()
        for v in worked:
            items = recent.touch(items, v)
        recent.save(items)
        lib = library.load()
        if any([library.refresh_video(lib, v) for v in worked]):
            library.save(lib)
    statuses = [jv.status for jv in job.videos]
    if job.cancel.is_set():
        job.status = "stopped"
    elif statuses and all(s == "failed" for s in statuses):
        job.status, job.error = "failed", job.videos[0].error
    failed = sum(s == "failed" for s in statuses)
    job.result = {"done": sum(s == "done" for s in statuses), "skipped": statuses.count("skipped"), "failed": failed,
                  "target": target}  # fmt: skip


def submit_retranslate(jobs: Jobs, video: Path, line_ids: list[int], st: Settings, listener: str | None = None) -> Job:
    video = video.resolve()

    def work(job: Job) -> None:
        opt = make_options(st)
        try:
            job.stage = "translating"
            proj = retranslate_lines(video, line_ids, opt, listener=listener)
        finally:
            if opt.engine is not None:
                opt.engine.stop()
        wanted = set(line_ids)
        job.result = {"lines": [{"id": c.id, "text": c.text, "translation": c.translation}
                                for c in proj.cues if c.id in wanted], "files": subtitle_files(video)}  # fmt: skip

    return jobs.submit("retranslate", f"{video.name}: {len(line_ids)} lines", work, [video])


def submit_burn(jobs: Jobs, video: Path, st: Settings, style: SubStyle | None, out: Path | None = None) -> Job:
    from .burn import burn
    from .models import Project

    video = video.resolve()
    proj_path = project_path(video)
    if not proj_path.exists():
        raise FileNotFoundError(f"Make subtitles for this video first: {video}")
    target = Project.load(proj_path).target_language or st.target
    dest = (out or video.with_name(f"{video.stem}.{target}.subtitled.mp4")).resolve()

    def work(job: Job) -> None:
        proj = Project.load(proj_path)
        job.stage = "burning"

        def progress(f: float) -> None:
            job.progress = job.videos[0].progress = f

        burn(video, proj.cues, style or DEFAULT, target, dest, progress, job.cancel)
        job.videos[0].status, job.videos[0].files = "done", [str(dest)]
        job.result = {"output": str(dest)}

    return jobs.submit("burn", f"burn-in: {video.name}", work, [video])


def submit_scan(jobs: Jobs, folder: Path | None, add: bool = False) -> Job:
    """Read a library folder (every subfolder; tracks inside new or changed videos). folder None = every one."""
    lib = library.load()
    if add:
        assert folder is not None
        if not folder.is_dir():
            raise FileNotFoundError(f"Not a folder: {folder}")
        if not library.add_root(lib, folder.resolve()):
            raise ValueError(f"{folder} is already in the library (inside {', '.join(lib.roots)}).")
        library.save(lib)
    roots = [str(folder.resolve())] if folder else list(lib.roots)

    def work(job: Job) -> None:
        current = library.load()
        for i, root in enumerate(roots):
            job.stage = f"reading {root}"

            def progress(stage: str, n: int, total: int, i: int = i) -> None:
                job.progress = (i + (n / total if stage == "tracks" and total else 0.0)) / len(roots)

            s = library.scan_folder(root, current, True, job.cancel, progress)
            library.apply(current, s)
        library.save(current)
        job.result = {"folders": roots, "videos": len(current.videos)}

    return jobs.submit("scan", "library: " + (Path(roots[0]).name if len(roots) == 1 else "all folders"), work)
