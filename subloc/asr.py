"""Speech → timed source-language cues (faster-whisper + Silero VAD)."""

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .errors import SublocError
from .gpu import cuda_available, setup_cuda_dlls
from .media import SAMPLE_RATE
from .models import Cue, Word

# Phrases Whisper invents over music/silence (it learned them from YouTube credits).
JUNK = [
    "thanks for watching",
    "thank you for watching",
    "subtitles by",
    "please subscribe",
    "시청해주셔서 감사합니다",
    "구독과 좋아요",
    "ご視聴ありがとうございました",
    "チャンネル登録",
    "продолжение следует",
    "редактор субтитров",
    "abone olmayı unutmayın",
    "altyazı",
    "字幕由",
    "请不吝点赞",
    "ترجمة نانسي",
    "اشتركوا في القناة",
]


# Whole-line hallucinations (only junk when they are the entire line).
JUNK_EXACT = {"продолжение.", "продолжение", "субтитры", "ご視聴ありがとうございました。", "字幕"}


def _is_junk(text: str) -> bool:
    t = text.lower().strip()
    if t in JUNK_EXACT:
        return True
    if not t or re.fullmatch(r"[\W_]+", t):
        return True
    if "�" in t:  # broken UTF-8 bytes: Whisper decoding garbage
        return True
    return any(j in t for j in JUNK)


def transcribe(
    audio: np.ndarray,
    model_name: str = "large-v3",
    language: str | None = None,
    on_progress: Callable[[float, str, list[Cue]], None] | None = None,
    log: Callable[[str], None] = print,
) -> tuple[list[Cue], str]:
    """Return (cues, language). language=None → vote across the video; "mixed" → per-chunk languages.
    Progress callback gets (fraction, latest_text, cues_so_far)."""
    model = load_model(model_name)
    total = len(audio) / SAMPLE_RATE
    cues: list[Cue] = []

    if language == "mixed":
        _transcribe_mixed(model, audio, cues, on_progress, total)
        return cues, "mixed"

    if not language:
        language, share = detect_language(model, audio)
        log(f"  detected language: {language} ({share:.0%} of samples)")

    # Sequential (not BatchedInferencePipeline): batched mode returns ~30 s chunks with several
    # speakers per segment and was noticeably less accurate on Korean in testing.
    segments, _ = model.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    _collect(segments, cues, 0.0, language, on_progress, total)
    return cues, language


_models: dict[str, object] = {}


def local_model(name: str) -> Path | None:
    """A Whisper model already on this PC: Subloc's own model cache, or the standard Hugging Face cache in the
    user folder (other Whisper tools download there). The folder holding model.bin, or None."""
    import os

    caches = [Path(os.environ["HF_HOME"]) / "hub"] if os.environ.get("HF_HOME") else []
    caches.append(Path.home() / ".cache" / "huggingface" / "hub")
    for cache in caches:
        snaps = cache / f"models--Systran--faster-whisper-{name}" / "snapshots"
        found = sorted(snaps.glob("*/model.bin"), key=lambda p: p.stat().st_mtime) if snaps.is_dir() else []
        if found:
            return found[-1].parent
    return None


def load_model(name: str):
    """Load once per process (the GUI reuses it across videos)."""
    if name not in _models:
        setup_cuda_dlls()
        from faster_whisper import WhisperModel

        gpu = cuda_available()
        _models.clear()  # keep only one in VRAM
        try:
            here = local_model(name)  # already on this PC (also from other Whisper tools): no download
            _models[name] = WhisperModel(
                str(here) if here else name, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8"
            )
        except Exception as e:
            msg = str(e).lower()
            if "out of memory" in msg:
                raise SublocError(
                    "Not enough graphics memory for the speech model. Close other programs that "
                    "use the GPU (games, LM Studio models you don't need) or pick “Faster”.",
                    str(e),
                ) from e
            if any(k in msg for k in ("connection", "resolve", "offline", "timed out", "network", "max retries")):
                raise SublocError(
                    "Couldn't download the speech model. Connect to the internet once so Subloc "
                    "can fetch it (about 3 GB); after that it works offline.",
                    str(e),
                ) from e
            raise SublocError("The speech model couldn't be loaded.", str(e)) from e
    return _models[name]


def unload_model() -> None:
    """Free Whisper's VRAM (~4 GB) before translation so the LLM isn't pushed into shared memory."""
    import gc

    _models.clear()
    gc.collect()


def _speech_chunks(audio: np.ndarray, max_gap: float = 0.3, max_len: float = 20.0) -> list[tuple[int, int]]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    spans = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, speech_pad_ms=200))
    merged: list[list[int]] = []
    for s in spans:
        if (
            merged
            and (s["start"] - merged[-1][1]) < max_gap * SAMPLE_RATE
            and (s["end"] - merged[-1][0]) < max_len * SAMPLE_RATE
        ):
            merged[-1][1] = s["end"]
        else:
            merged.append([s["start"], s["end"]])
    return [(a, b) for a, b in merged]


def detect_language(model, audio: np.ndarray, samples: int = 8) -> tuple[str, float]:
    """Vote over several 30 s windows of speech spread across the video, so an opening song or
    a single noisy spot can't decide the language (Initial D's Eurobeat came out as 'nn')."""
    chunks = _speech_chunks(audio)
    speech = np.concatenate([audio[a:b] for a, b in chunks]) if chunks else audio
    win = 30 * SAMPLE_RATE
    n = max(1, min(samples, len(speech) // win))
    starts = np.linspace(0, max(len(speech) - win, 0), n).astype(int)
    scores: dict[str, float] = {}
    for s in starts:
        _, _, probs = model.detect_language(speech[s : s + win])
        for lang, p in probs:
            scores[lang] = scores.get(lang, 0.0) + p
    best = max(scores, key=scores.__getitem__)
    return best, scores[best] / n


def _transcribe_mixed(model, audio, cues, on_progress, total) -> None:
    """Language can change every line: detect + transcribe each speech chunk separately."""
    prev_lang = None
    for a, b in _speech_chunks(audio, max_gap=0.3, max_len=15.0):
        chunk = audio[a:b]
        lang, prob, _ = model.detect_language(chunk)
        if prob < 0.5 and prev_lang and (b - a) < 2 * SAMPLE_RATE:
            lang = prev_lang  # too short to tell: assume same speaker continues
        prev_lang = lang
        segments, _ = model.transcribe(
            chunk, language=lang, word_timestamps=True, vad_filter=False, condition_on_previous_text=False
        )
        _collect(segments, cues, a / SAMPLE_RATE, lang, on_progress, total)


def _collect(segments, cues: list[Cue], offset: float, lang: str | None, on_progress, total: float) -> None:
    for seg in segments:
        text = seg.text.strip()
        if on_progress:
            on_progress(min((seg.end + offset) / total, 1.0), text, cues)
        if _is_junk(text):
            continue
        if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
            continue
        if cues and text == cues[-1].text and seg.start + offset - cues[-1].end < 1.0:
            cues[-1].end = seg.end + offset  # collapse stutter-repeats
            continue
        words = [Word(w.start + offset, w.end + offset, w.word, w.probability) for w in (seg.words or [])]
        cues.append(
            Cue(
                id=0,
                start=seg.start + offset,
                end=seg.end + offset,
                text=text,
                source="asr",
                words=words,
                confidence=float(np.exp(seg.avg_logprob)),
                lang=lang,
            )
        )
