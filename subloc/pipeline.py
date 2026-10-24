"""Orchestrates: audio → ASR → segmentation → translation → SRT, with caching/resume."""

import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .asr import transcribe, unload_model
from .errors import SublocError, friendly_os_error
from .glossary import Glossary, Term, merge_into
from .glossary import extract as extract_names
from .glossary import folder_path as glossary_path
from .llm import LMStudio
from .media import default_audio_track, fingerprint, load_audio, probe, read_subtitles
from .models import Cue, Project
from .segment import SEGMENT_VERSION, segment
from .style import SubStyle, write_ass
from .subparse import guess_language
from .subparse import parse as parse_subs
from .subtitles import write_srt
from .translate import MAX_PARALLEL, PARALLEL, lang_name, translate


class Cancelled(Exception):
    pass


@dataclass
class Options:
    target: str = "ar"
    source: str | None = None  # None = auto-detect
    asr_model: str = "large-v3"
    llm_model: str | None = None  # None = whatever is loaded in LM Studio
    llm_url: str = "http://localhost:1234"
    audio_track: int | None = None  # None = original-language track (see default_audio_track)
    subs_track: int | None = None  # set = translate this built-in subtitle track instead of listening
    parallel: int = PARALLEL  # translation requests sent to LM Studio at once (1–4)
    retranscribe: bool = False
    retranslate: bool = False
    auto_glossary: bool = True  # find names first; keep spellings consistent (folder glossary file)
    transcribe_only: bool = False  # batch phase 1: stop after the source subtitles
    keep_asr_loaded: bool = False  # batch phase 1: don't unload Whisper between files
    style: SubStyle | None = None  # set = also write a styled Video.<lang>.ass
    engine: Any = None  # BuiltinEngine when Subloc runs its own translator (else llm_url is used)
    prefer_builtin_subs: bool = False  # batch: per file, translate its own subtitles when it has them
    voices: bool = True  # who speaks each line + man/woman voice, when those models are installed (subloc.voices)
    scene_pass: bool = True  # with voices: first read whole scenes to decide who each line is to (subloc.addressee)


class Reporter:
    """Progress sink. The CLI uses this as-is (prints); the GUI overrides it with Qt signals."""

    def log(self, msg: str) -> None:
        print(msg)

    def warn(self, msg: str) -> None:
        """Something the user should know about the result (not an error: the job continues)."""
        self.log(f"WARNING: {msg}")

    def stage(self, name: str, frac: float, detail: str = "") -> None:
        """name: audio | transcribe | voices | names | listeners | translate | done"""

    def cues(self, cues: list[Cue]) -> None:
        """Called whenever subtitle lines change (after transcription, after each translation batch)."""


def _write(cues, path: Path, translated: bool, lang: str | None) -> None:
    try:
        write_srt(cues, path, translated=translated, lang=lang)
    except OSError as e:
        raise friendly_os_error(e, path.name) from e


def project_path(video: Path) -> Path:
    return video.with_name(video.stem + ".subloc.json")


def run(
    video: Path, opt: Options, rep: Reporter | None = None, cancel: threading.Event | None = None
) -> tuple[Project, list[Path]]:
    rep = rep or Reporter()
    cancel = cancel or threading.Event()

    def check() -> None:
        if cancel.is_set():
            raise Cancelled()

    video = video.resolve()
    ppath = project_path(video)
    proj = Project.load(ppath) if ppath.exists() else Project(video=str(video))

    def save() -> None:
        try:
            proj.save(ppath)
        except OSError as e:
            raise friendly_os_error(e, "progress") from e

    outputs: list[Path] = []

    info = probe(video)
    file_id = fingerprint(video)

    # 1a. Existing subtitles: read them instead of listening (exact timing, written by people)
    if opt.subs_track is not None:
        track = info.subtitles[opt.subs_track]
        src_key = {"subs": opt.subs_track, "file": file_id}
        if opt.retranscribe or proj.meta.get("source") != src_key or not proj.cues:
            rep.stage("audio", 0, "Reading built-in subtitles…")
            proj.cues = parse_subs(read_subtitles(video, opt.subs_track))
            if not proj.cues:
                raise RuntimeError("That subtitle track is empty or couldn't be read.")
            proj.asr_cues = []
            proj.language = guess_language(proj.cues, track.lang)
            proj.meta["source"] = src_key
            proj.target_language = None
            save()
        rep.log(
            f"Using built-in subtitles: track {opt.subs_track + 1} "
            f"({track.title or track.lang or 'untitled'}), {len(proj.cues)} lines, "
            f"language={proj.language or 'unknown'}"
        )
        if info.has_audio:
            _voices(video, opt, proj, save, rep, cancel, track=default_audio_track(info))
        return _translate_and_write(video, opt, proj, save, rep, cancel, outputs)

    # 1b. Transcribe (cached unless track/model/language changed or forced)
    audio_track = opt.audio_track if opt.audio_track is not None else default_audio_track(info)
    # "v" bumps when transcription changes in a way that makes old saved results wrong
    # (v2: timing stays in sync on damaged files).
    asr_key = {"model": opt.asr_model, "language": opt.source, "audio": audio_track, "v": 2, "file": file_id}
    if opt.retranscribe or not proj.asr_cues or proj.meta.get("source") != asr_key:
        if opt.engine is not None:  # free the graphics card for Whisper
            opt.engine.stop()
        if not info.has_audio:
            raise SublocError("This video has no sound track to listen to.")
        rep.stage("audio", 0)
        t = info.audio[audio_track]
        rep.log(
            f"Extracting audio track {audio_track + 1} ({t.title or t.lang or 'untitled'}), "
            f"{info.duration / 60:.1f} min…"
        )
        decoded = load_audio(video, audio_track)
        audio = decoded.samples
        proj.meta["audio_missing"] = round(decoded.missing, 3)
        if decoded.missing >= 0.02:
            rep.warn(
                f"This file is damaged: about {decoded.missing:.0%} of the sound couldn't be read. "
                f"Subtitles will be missing in those parts (timing of the rest is correct)."
            )
        check()
        rep.log(f"Transcribing with Whisper {opt.asr_model}…")
        rep.stage("transcribe", 0, "Loading speech model…")
        t0 = time.time()
        last = [0.0]
        shown = [0.0]

        def prog(frac: float, text: str, so_far: list[Cue]) -> None:
            check()
            rep.stage("transcribe", frac, text)
            if time.time() - shown[0] > 1.0:  # live preview of heard lines, ~1 update/s
                shown[0] = time.time()
                rep.cues(so_far)
            if frac - last[0] >= 0.1 or frac >= 1.0:
                last[0] = frac
                rep.log(f"  {frac:4.0%}  {text[:60]}")

        try:
            proj.asr_cues, proj.language = transcribe(audio, opt.asr_model, opt.source, prog, rep.log)
        finally:
            if not opt.keep_asr_loaded:
                unload_model()
        proj.meta["source"] = asr_key
        proj.cues = segment(list(proj.asr_cues))
        proj.meta["segment_v"] = SEGMENT_VERSION
        if not proj.cues:
            raise SublocError(
                "No speech was found in this video. If people do talk in it, try choosing the "
                "spoken language instead of Auto-detect."
            )
        proj.target_language = None
        rep.log(f"  {len(proj.cues)} subtitles, language={proj.language}, {time.time() - t0:.0f}s")
        save()
        _voices(video, opt, proj, save, rep, cancel, audio=audio)
    else:
        if proj.meta.get("segment_v") != SEGMENT_VERSION:
            # Line-splitting rules changed since this was saved: re-split the kept raw transcript
            # (no need to listen again) and translate afresh.
            proj.cues = segment(list(proj.asr_cues))
            proj.meta["segment_v"] = SEGMENT_VERSION
            proj.target_language = None
            save()
            rep.log("Re-split saved transcript with updated line rules")
        rep.log(f"Using saved transcript ({len(proj.cues)} subtitles, language={proj.language})")
        _voices(video, opt, proj, save, rep, cancel, track=audio_track)

    src_srt = video.with_name(f"{video.stem}.{proj.language}.srt")
    _write(proj.cues, src_srt, translated=False, lang=proj.language)
    outputs.append(src_srt)
    rep.log(f"Wrote {src_srt.name}")
    if opt.transcribe_only:
        return proj, outputs
    return _translate_and_write(video, opt, proj, save, rep, cancel, outputs)


def _voices(video: Path, opt: Options, proj: Project, save, rep: Reporter, cancel: threading.Event,
            audio=None, track: int = 0) -> None:  # fmt: skip
    """Step 1c: who speaks each line and whether the voice is a man's or a woman's (subloc.voices). Saved with
    the project and redone only when the lines change. Skipped when its models aren't installed; a failure here
    is a warning, never the end of the job (the subtitles don't need it)."""
    from . import voices

    if not opt.voices or not voices.ready():
        return
    key = {"v": voices.VERSION, "source": proj.meta.get("source"), "segment_v": proj.meta.get("segment_v")}
    if proj.meta.get("voices", {}).get("key") == key:
        return
    rep.stage("voices", 0, "Finding speakers…")
    rep.log("Finding speakers and their voices…")
    t0 = time.time()
    try:
        if audio is None:
            audio = load_audio(video, track).samples
        turns = voices.diarize(audio, cancel.is_set, rep.log)
        if cancel.is_set():
            raise Cancelled()
        speakers = voices.label(proj.cues, audio, turns, voices.GenderModel(), cancel.is_set,
                                lambda f: rep.stage("voices", f, "Voices…"), prints=voices.Fingerprints())  # fmt: skip
    except voices.Cancelled as e:
        raise Cancelled() from e
    except Cancelled:
        raise
    except Exception as e:  # optional step: report and carry on
        rep.warn(f"Couldn't tell the speakers apart ({e}). The subtitles are not affected.")
        return
    proj.meta["voices"] = {"key": key, "speakers": speakers}
    save()
    rep.cues(proj.cues)
    known = sum(1 for c in proj.cues if c.gender)
    kinds = [s["gender"] for s in speakers.values()]
    rep.log(f"  {len(speakers)} speakers ({kinds.count('female')} women, {kinds.count('male')} men, "
            f"{kinds.count(None)} not sure), voice known on {known}/{len(proj.cues)} lines, "
            f"{time.time() - t0:.0f}s")  # fmt: skip
    rep.stage("voices", 1, f"{len(speakers)} speakers")


def _translate_and_write(video, opt, proj, save, rep, cancel, outputs):
    def check() -> None:
        if cancel.is_set():
            raise Cancelled()

    if opt.target == proj.language:  # subtitles in the spoken language: the transcript is the result
        for c in proj.cues:
            c.translation = c.text
        proj.target_language = opt.target
        save()
        for path in write_outputs(video, proj, opt.target, opt.style):
            outputs.append(path)
        rep.cues(proj.cues)
        rep.stage("done", 1)
        return proj, outputs

    # 2. Translate (resumes partially translated projects)
    client = _client(opt)
    model = _resolve_model(client, opt)
    tr_key = {"target": opt.target, "model": model}
    if opt.retranslate or proj.target_language != opt.target or proj.meta.get("translation") != tr_key:
        for c in proj.cues:
            c.translation = None
    proj.target_language = opt.target
    proj.meta["translation"] = tr_key
    rep.cues(proj.cues)
    workers = max(1, min(opt.parallel, MAX_PARALLEL))

    # 2a. Names: one spelling per name, shared with other videos in the folder (subloc.glossary.json)
    glossary = None
    if opt.auto_glossary:
        gpath = glossary_path(video)
        glossary = Glossary.load(gpath, opt.target)  # re-read every run so the user's edits apply
        if opt.retranslate or proj.meta.get("glossary") != tr_key:
            rep.stage("names", 0, "Finding names…")
            rep.log("Finding names and terms…")
            found = extract_names(
                proj.cues,
                client,
                model,
                lang_name(proj.language),
                lang_name(opt.target),
                glossary,
                workers,
                rep.log,
                tgt_code=opt.target,
            )
            proj.meta["glossary_terms"] = [asdict(t) for t in found.terms]
            proj.meta["glossary"] = tr_key
            save()
            rep.stage("names", 1, f"{len(found.terms)} found")
            rep.log(
                f"  {len(found.terms)} names/terms: "
                + ", ".join(f"{t.source}→{t.target}" for t in found.terms[:12])
                + ("…" if len(found.terms) > 12 else "")
            )
        check()
        # This video's names go into the folder file (existing / user entries are never changed).
        own = Glossary(opt.target, [Term(**t) for t in proj.meta.get("glossary_terms", [])])
        merge_into(glossary, own)
        try:
            glossary.save(gpath)
        except OSError as e:  # read-only folder: still use it for this run
            rep.log(f"  couldn't save {gpath.name}: {e}")

    decided = _listeners(video, opt, proj, save, rep, cancel, client, model, tr_key, workers, glossary)
    listeners = _with_fixed(decided, proj)
    check()
    rep.log(f"Translating {proj.language} → {opt.target} with {model}…")
    rep.stage("translate", 0, model)
    t0 = time.time()

    def batch_done() -> None:
        save()
        rep.cues(proj.cues)

    def tr_prog(done: int, total: int) -> None:
        rep.stage("translate", done / max(total, 1), f"{done}/{total} lines")
        rep.log(f"  {done}/{total} lines")

    translate(
        proj.cues,
        client,
        model,
        proj.language,
        opt.target,
        title=video.stem,
        glossary=glossary,
        on_progress=tr_prog,
        on_batch_done=batch_done,
        log=rep.log,
        should_stop=cancel.is_set,
        workers=workers,
        listeners=listeners,
    )
    save()
    check()
    _learn_genders(proj, glossary, video, rep)
    missing = sum(1 for c in proj.cues if not c.translation)
    rep.log(f"  done in {time.time() - t0:.0f}s" + (f" ({missing} lines failed)" if missing else ""))

    for path in write_outputs(video, proj, opt.target, opt.style):
        outputs.append(path)
        rep.log(f"Wrote {path.name}")
    rep.stage("done", 1)
    return proj, outputs


def _learn_genders(proj: Project, glossary: Glossary | None, video: Path, rep: Reporter) -> None:
    """Names said to someone whose voice is known: remember that person's gender in the folder's name list."""
    from .voices import has_voices, speaker_genders

    if glossary is None or not has_voices(proj.cues):
        return
    n = glossary.learn_genders(proj.cues, speaker_genders(proj.cues))
    if n:
        try:
            glossary.save(glossary_path(video))
            rep.log(f"  learnt from voices: {n} name(s) with a gender, kept in {glossary_path(video).name}")
        except OSError as e:
            rep.log(f"  couldn't save {glossary_path(video).name}: {e}")


FIXED = "listeners_fixed"  # project meta: listeners the user chose by hand, {cue id: {"to", "text"}}
LISTENER_CHOICES = ("man", "woman", "several")


def fixed_listeners(proj: Project) -> dict[int, str | None]:
    """The listeners set by hand that still belong to their line (its text unchanged since)."""
    text = {c.id: c.text for c in proj.cues}
    return {int(k): v["to"] for k, v in proj.meta.get(FIXED, {}).items() if text.get(int(k)) == v.get("text")}


def _with_fixed(decided: dict[int, str | None] | None, proj: Project) -> dict[int, str | None] | None:
    out = {**(decided or {}), **fixed_listeners(proj)}
    return out or None


def _listeners(video, opt, proj, save, rep, cancel, client, model, tr_key, workers,
               glossary=None) -> dict[int, str | None] | None:  # fmt: skip
    """Who each line is spoken to, read from whole scenes before translating (subloc.addressee), saved with the
    project so a stopped job doesn't ask again. None (translation then decides it per batch) without voices,
    with the option off, or when nothing came back."""
    from . import addressee
    from .translate import Who

    who = Who.of(proj.cues)
    if not opt.scene_pass or who is None:
        return None
    key = {**tr_key, "voices": proj.meta.get("voices", {}).get("key")}
    saved = proj.meta.get("listeners", {})
    if saved.get("key") == key and not opt.retranslate:
        return {int(k): v for k, v in saved.get("to", {}).items()} or None
    rep.stage("listeners", 0, "Reading scenes…")
    rep.log("Reading each scene to find who is spoken to…")
    t0 = time.time()
    found = addressee.decide(
        proj.cues, client, model, proj.language, who.scene, who.people, who.voice, title=video.stem,
        on_progress=lambda d, n: rep.stage("listeners", d / max(n, 1), f"{d}/{n} lines"),
        log=rep.log, workers=workers, should_stop=cancel.is_set, glossary=glossary,
    )  # fmt: skip
    if cancel.is_set():
        raise Cancelled()
    proj.meta["listeners"] = {"key": key, "to": {str(k): v for k, v in found.items()}}
    save()
    rep.log(f"  listener found for {sum(1 for v in found.values() if v)}/{len(proj.cues)} lines, "
            f"{time.time() - t0:.0f}s")  # fmt: skip
    return found or None


def _client(opt: Options) -> LMStudio:
    """The translator: Subloc's own engine (started on demand) or the configured server."""
    return LMStudio(opt.engine.ensure_running() if opt.engine is not None else opt.llm_url)


def _resolve_model(client: LMStudio, opt: Options) -> str:
    if opt.llm_model:
        return opt.llm_model
    loaded = client.default_model()
    if not loaded:
        raise SublocError("No model is loaded in LM Studio. Load one there, or pick one from the list.")
    return loaded.id


def write_outputs(video: Path, proj: Project, target: str, style: SubStyle | None) -> list[Path]:
    """Translated subtitles next to the video: always .srt, plus a styled .ass when a style is set."""
    out = []
    srt = video.with_name(f"{video.stem}.{target}.srt")
    _write(proj.cues, srt, translated=True, lang=target)
    out.append(srt)
    if style is not None:
        ass = video.with_name(f"{video.stem}.{target}.ass")
        size = probe(video)
        try:
            write_ass(proj.cues, ass, style, True, target, size.width or 1920, size.height or 1080)
        except OSError as e:
            raise friendly_os_error(e, ass.name) from e
        out.append(ass)
    return out


# ---------------------------------------------------------------- review: fix single lines


def update_line(video: Path, cue_id: int, text: str, opt: Options) -> Project:
    """Save a hand-corrected translation and rewrite the subtitle files."""
    video = video.resolve()
    proj = Project.load(project_path(video))
    cue = next(c for c in proj.cues if c.id == cue_id)
    cue.translation = text.strip() or None
    proj.save(project_path(video))
    write_outputs(video, proj, proj.target_language or opt.target, opt.style)
    return proj


def retranslate_lines(video: Path, cue_ids: list[int], opt: Options, listener: str | None = None) -> Project:
    """Translate some lines again (e.g. after fixing a name), with their neighbours as context and the
    name list, then rewrite the files. Lines the translator doesn't return keep their old text.
    `listener` ("man" / "woman" / "several"): who these lines are spoken to, set by the user and kept."""
    video = video.resolve()
    proj = Project.load(project_path(video))
    if listener is not None:
        if listener not in LISTENER_CHOICES:
            raise ValueError(f"listener must be one of {', '.join(LISTENER_CHOICES)}")
        fixed = proj.meta.setdefault(FIXED, {})
        for c in proj.cues:
            if c.id in cue_ids:
                fixed[str(c.id)] = {"to": listener, "text": c.text}
    target = proj.target_language or opt.target
    wanted = set(cue_ids)
    previous = {c.id: c.translation for c in proj.cues if c.id in wanted}
    for c in proj.cues:
        if c.id in wanted:
            c.translation = None
    client = _client(opt)
    model = _resolve_model(client, opt)
    glossary = Glossary.load(glossary_path(video), target) if opt.auto_glossary else None
    saved = proj.meta.get("listeners", {}).get("to") if opt.scene_pass else None
    decided = {int(k): v for k, v in saved.items()} if saved else None  # who each line is to, as decided before
    listeners = _with_fixed(decided, proj)
    try:
        translate(proj.cues, client, model, proj.language, target, title=video.stem, glossary=glossary,
                  log=lambda m: None, workers=max(1, min(opt.parallel, MAX_PARALLEL)),
                  listeners=listeners)  # fmt: skip
    finally:
        for c in proj.cues:
            if c.id in wanted and not c.translation:
                c.translation = previous[c.id]  # keep the old line rather than leaving a hole
    proj.save(project_path(video))
    write_outputs(video, proj, target, opt.style)
    return proj


def retranslate_line(video: Path, cue_id: int, opt: Options) -> Project:
    return retranslate_lines(video, [cue_id], opt)
