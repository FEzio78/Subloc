"""Many videos in one go (a season folder, a dropped selection).

Two phases so the GPU is used well:
  1. transcribe every video with Whisper loaded once,
  2. unload Whisper, then find names + translate every video (LLM gets the whole GPU,
     and the folder glossary grows episode by episode so names stay consistent).
One failing file never stops the rest.
"""

import os
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from .asr import unload_model
from .media import fingerprint, has_target_subtitles, probe, subtitle_source
from .models import Project
from .pipeline import Cancelled, Options, Reporter, project_path, run

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".ts", ".flv", ".wmv", ".mp3", ".wav", ".m4a"}
SKIP_DIRS = {"$recycle.bin", "system volume information", "sample", "samples", "@eadir", "#recycle"}


def natural(text: str) -> list:
    """'Ep 2' before 'Ep 10'."""
    return [int(s) if s.isdigit() else s.lower() for s in re.split(r"(\d+)", text)]


def natural_key(p: Path) -> list:
    return natural(p.name)


def skip_dir(name: str) -> bool:
    """System and hidden folders, and the 'Sample' clips that come with releases: nothing to translate there."""
    return name.lower() in SKIP_DIRS or name.startswith((".", "$"))


def walk_videos(folder: Path, ext: set[str] = VIDEO_EXT) -> list[Path]:
    """Every video in `folder` and all its subfolders, in reading order (Season 2 / Ep 10 after Season 1 / Ep 9)."""
    out: list[Path] = []
    for here, dirs, files in os.walk(folder):  # doesn't follow links, so no loops
        dirs[:] = [d for d in dirs if not skip_dir(d)]
        out += [Path(here, f) for f in files if os.path.splitext(f)[1].lower() in ext]
    return sorted(out, key=lambda p: [natural(part) for part in p.relative_to(folder).parts])


def find_videos(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out += walk_videos(p)
        elif p.suffix.lower() in VIDEO_EXT:
            out.append(p)
    seen, unique = set(), []
    for p in out:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def is_done(video: Path, target: str) -> bool:
    """Target subtitles exist and every line was translated."""
    if not video.with_name(f"{video.stem}.{target}.srt").exists():
        return False
    try:
        proj = Project.load(project_path(video))
    except Exception:
        return False
    same_file = proj.meta.get("source", {}).get("file") == fingerprint(video)  # not replaced since
    return same_file and proj.target_language == target and bool(proj.cues) and all(c.translation for c in proj.cues)


@dataclass
class Item:
    video: Path
    status: str = "waiting"  # waiting | listening | listened | translating | done | skipped | failed | stopped
    error: str = ""


class BatchReporter(Reporter):
    """Extra hook so a UI can show which file is being worked on."""

    def item(self, index: int, item: Item) -> None:
        pass


def run_batch(
    videos: list[Path], opt: Options, rep: BatchReporter | None = None, cancel: threading.Event | None = None
) -> list[Item]:
    rep = rep or BatchReporter()
    cancel = cancel or threading.Event()
    items = [Item(v) for v in videos]

    def set_status(i: int, status: str, error: str = "") -> None:
        items[i].status, items[i].error = status, error
        rep.item(i, items[i])
        rep.log(f"[{i + 1}/{len(items)}] {items[i].video.name}: {status}" + (f" — {error}" if error else ""))

    for i, it in enumerate(items):
        if not opt.retranslate and not opt.retranscribe and is_done(it.video, opt.target):
            set_status(i, "skipped", "already done")

    # Per-file source: its own subtitles when wanted and available, otherwise listening.
    opts = [opt] * len(items)
    if opt.prefer_builtin_subs and opt.subs_track is None:
        for i, it in enumerate(items):
            if it.status != "waiting":
                continue
            try:
                info = probe(it.video)
            except Exception as e:
                set_status(i, "failed", str(e) or type(e).__name__)
                continue
            track = subtitle_source(info, opt.target)
            if track is not None:
                opts[i] = replace(opt, subs_track=track)
            elif has_target_subtitles(info, opt.target):
                set_status(i, "skipped", "already has subtitles in that language")

    try:
        # Phase 1: transcribe all (Whisper stays loaded between files)
        if any(o.subs_track is None for o in opts):
            for i, it in enumerate(items):
                if it.status != "waiting" or opts[i].subs_track is not None:
                    continue
                if cancel.is_set():
                    break
                set_status(i, "listening")
                try:
                    run(it.video, replace(opts[i], transcribe_only=True, keep_asr_loaded=True), rep, cancel)
                    set_status(i, "listened")
                except Cancelled:
                    set_status(i, "stopped")
                    break
                except Exception as e:
                    set_status(i, "failed", str(e) or type(e).__name__)
            unload_model()

        # Phase 2: names + translation
        for i, it in enumerate(items):
            if it.status not in ("waiting", "listened"):
                continue
            if cancel.is_set():
                set_status(i, "stopped")
                continue
            set_status(i, "translating")
            try:
                run(it.video, opts[i], rep, cancel)
                set_status(i, "done")
            except Cancelled:
                set_status(i, "stopped")
            except Exception as e:
                set_status(i, "failed", str(e) or type(e).__name__)
    finally:
        unload_model()

    done = sum(it.status == "done" for it in items)
    failed = [it for it in items if it.status == "failed"]
    rep.log(f"Batch finished: {done} done, {sum(it.status == 'skipped' for it in items)} skipped, {len(failed)} failed")
    for it in failed:
        rep.log(f"  ✗ {it.video.name}: {it.error}")
    return items
