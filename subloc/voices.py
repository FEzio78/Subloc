"""Voices: who speaks each line, and whether it is a man's or a woman's voice (PLAN.md 2.7).

Two local models, downloaded once (Setup, or Settings → Speakers):
- NVIDIA Nemotron 3 Diarization (OpenMDW-1.1), run by NVIDIA's NeMo-Speech.cpp (`nemo-speech.exe`, Apache-2.0,
  bundled from vendor/nemo-speech, Vulkan build: any graphics card, else the processor). It answers "speaker 1
  talks from 3.2 s to 5.0 s"; up to 8 speakers. Reliable in conversations, unreliable when many talk at once.
- A voice gender classifier (ECAPA-TDNN, MIT; JaesungHuh/voice-gender-classifier as ONNX q8, 16 MB) on each
  line's own audio, on the processor (~70 ms a line).

Measured on real clips (PLAN.md 2.7): a speaker's overall gender matches listening, but one diarized "speaker"
sometimes holds two people. So a line the classifier is sure about decides for itself; otherwise it takes its
speaker's overall gender; otherwise it stays unknown. Unknown is fine: translation then uses the generic form.
"""

import json
import subprocess
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import VENDOR, proc
from .config import models_dir
from .download import download
from .media import SAMPLE_RATE
from .models import Cue

# Bump when the method changes in a way that makes saved results wrong: projects then label their lines again.
VERSION = 1


@dataclass(frozen=True)
class ModelFile:
    url: str
    file: str
    sha256: str
    size: int  # bytes


# Revisions pinned (Hugging Face commit ids); sha256 from the repositories' LFS records, checked on download.
DIARIZER = ModelFile(
    "https://huggingface.co/nvidia/Nemotron-3-Diarization/resolve/f667ed73aee57d40cc39428eb768b4fd87a0a29e/"
    "Nemotron-3-Diarization.q8_0.gguf",
    "Nemotron-3-Diarization.q8_0.gguf",
    "08456d9e22cd9a323c0364d98375f3746d6e68507ebb705cd46438c534c7a3a1",
    107012128,
)
GENDER = ModelFile(
    "https://huggingface.co/Alice-Sabrina-Ivy/voice-gender-classifier-onnx-q8-v2/resolve/"
    "8aedeb1a399945e52e6f3f61714abe07c1c48742/onnx/model_quantized.onnx",
    "voice-gender-q8-v2.onnx",
    "fdc2dbdcf99b9217977f7472f7d677dd48219c4759ca3f38d0626b600d86c252",
    16057697,
)
MODELS = (DIARIZER, GENDER)
DOWNLOAD_GB = sum(m.size for m in MODELS) / 1e9

# Diarization settings that scored best on the test scene (22/24 lines right, none missed).
DIARIZE_ARGS = ["--preset", "v3-streaming", "--onset", "0.4", "--offset", "0.35"]

SURE = 0.9  # a line this sure (P(female) ≥ 0.9 or ≤ 0.1) keeps its own answer
LEANS = 0.75  # a speaker (or, failing that, a line) needs this much to count
MIN_LINE = 0.5  # seconds: shorter lines aren't classified on their own
MAX_LINE = 6.0  # seconds of a line's audio given to the classifier (its middle)
MIN_SPEAKER = 4.0  # seconds of classified audio before a speaker's overall answer is used
MIN_OVERLAP = 0.25  # share of a line a speaker must cover to be its speaker


def folder() -> Path:
    return models_dir() / "voices"


def exe() -> Path | None:
    path = VENDOR / "nemo-speech" / "nemo-speech.exe"
    return path if path.exists() else None


def installed() -> bool:
    """Both models are downloaded (each was checked against its sha256 when it arrived)."""
    return all((folder() / m.file).exists() and (folder() / m.file).stat().st_size == m.size for m in MODELS)


def ready() -> bool:
    return exe() is not None and installed()


def install(on_progress: Callable[[int, int], None], cancel: threading.Event | None = None) -> None:
    """Download both models into the data folder. on_progress(bytes_done, bytes_total) over both."""
    total, before = sum(m.size for m in MODELS), 0

    def progress(done: int, _total: int) -> None:
        on_progress(before + done, total)

    for m in MODELS:
        download(m.url, folder() / m.file, m.sha256, progress, cancel)
        before += m.size


# ---------------------------------------------------------------- who speaks when


@dataclass
class Turn:
    start: float
    end: float
    speaker: int


class Cancelled(Exception):
    pass


def _write_wav(audio: np.ndarray, path: Path) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def diarize(audio: np.ndarray, should_stop: Callable[[], bool] = lambda: False,
            log: Callable[[str], None] = lambda m: None) -> list[Turn]:  # fmt: skip
    """Speaker turns for 16 kHz mono audio. Tries the graphics card (Vulkan), then the processor."""
    program = exe()
    if program is None:
        raise FileNotFoundError("nemo-speech.exe is missing (vendor/nemo-speech).")
    with tempfile.TemporaryDirectory(prefix="subloc-voices-") as tmp:
        wav, out, errfile = Path(tmp) / "audio.wav", Path(tmp) / "turns.json", Path(tmp) / "err.txt"
        _write_wav(audio, wav)
        err = ""
        for device in ("vulkan", "cpu"):
            cmd = [str(program), "diarize", str(wav), "--model", str(folder() / DIARIZER.file), "--device", device,
                   "--format", "json", "-o", str(out), "--force", *DIARIZE_ARGS]  # fmt: skip
            with errfile.open("wb") as ef:  # a file, not a pipe: a full pipe would stall the program
                p = proc.popen(cmd, stdout=subprocess.DEVNULL, stderr=ef)
                while p.poll() is None:
                    if should_stop():
                        p.kill()
                        p.wait()
                        raise Cancelled()
                    time.sleep(0.2)
            err = errfile.read_text(encoding="utf-8", errors="replace").strip()
            if p.returncode == 0 and out.exists():
                segs = json.loads(out.read_text(encoding="utf-8")).get("segments", [])
                return [Turn(float(s["start"]), float(s["end"]), int(s["speaker"])) for s in segs]
            log(f"  speakers on {device} failed ({p.returncode}): {err[-200:]}")
        raise RuntimeError(f"Finding speakers failed: {err[-300:]}")


def speaker_of(cue: Cue, turns: list[Turn]) -> int | None:
    """The speaker heard longest during the line (None if nobody covers at least MIN_OVERLAP of it)."""
    cover: dict[int, float] = {}
    for t in turns:
        o = min(cue.end, t.end) - max(cue.start, t.start)
        if o > 0:
            cover[t.speaker] = cover.get(t.speaker, 0.0) + o
    if not cover:
        return None
    best = max(cover, key=lambda s: cover[s])
    return best if cover[best] >= MIN_OVERLAP * max(cue.duration, 0.01) else None


# ---------------------------------------------------------------- man or woman


class GenderModel:
    def __init__(self, path: Path | None = None):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(path or folder() / GENDER.file), opts,
                                            providers=["CPUExecutionProvider"])  # fmt: skip

    def p_female(self, x: np.ndarray) -> float:
        """Raw 16 kHz audio in (the model does its own feature extraction); P(female) out."""
        logits = self.session.run(None, {"input_values": x.astype(np.float32)[None, :]})[0][0]
        e = np.exp(logits - logits.max())
        return float(e[1] / e.sum())  # labels: 0 male, 1 female


def _middle(audio: np.ndarray, cue: Cue) -> np.ndarray:
    mid, half = (cue.start + cue.end) / 2, min(cue.duration, MAX_LINE) / 2
    return audio[max(0, int((mid - half) * SAMPLE_RATE)) : int((mid + half) * SAMPLE_RATE)]


def _side(p: float | None, need: float) -> str | None:
    if p is None:
        return None
    return "female" if p >= need else "male" if p <= 1 - need else None


def decide(line_p: float | None, speaker_p: float | None) -> str | None:
    """A sure line decides; else the speaker's overall voice; else a line that leans clearly; else unknown."""
    return _side(line_p, SURE) or _side(speaker_p, LEANS) or _side(line_p, LEANS)


def label(cues: list[Cue], audio: np.ndarray, turns: list[Turn], model: GenderModel,
          should_stop: Callable[[], bool] = lambda: False,
          on_progress: Callable[[float], None] = lambda f: None) -> dict[str, dict]:  # fmt: skip
    """Set cue.speaker ("S1", "S2"… in order of first appearance) and cue.gender ("male" / "female" / None).
    Returns the speakers found: {"S1": {"gender", "p_female", "seconds", "lines"}}."""
    raw = [speaker_of(c, turns) for c in cues]
    names: dict[int, str] = {}
    for s in raw:
        if s is not None and s not in names:
            names[s] = f"S{len(names) + 1}"
    line_p: list[float | None] = []
    for i, c in enumerate(cues):
        if should_stop():
            raise Cancelled()
        x = _middle(audio, c)
        line_p.append(model.p_female(x) if c.duration >= MIN_LINE and len(x) >= MIN_LINE * SAMPLE_RATE else None)
        on_progress((i + 1) / max(len(cues), 1))
    speakers: dict[str, dict] = {}
    for s, name in names.items():
        mine = [(p, c.duration) for c, r, p in zip(cues, raw, line_p, strict=True) if r == s and p is not None]
        secs = sum(min(d, MAX_LINE) for _, d in mine)
        p = sum(p * min(d, MAX_LINE) for p, d in mine) / secs if secs else None
        speakers[name] = {"p_female": None if p is None else round(p, 3), "seconds": round(secs, 1),
                          "lines": sum(1 for r in raw if r == s),
                          "gender": _side(p, LEANS) if secs >= MIN_SPEAKER else None}  # fmt: skip
    for c, r, p in zip(cues, raw, line_p, strict=True):
        c.speaker = names.get(r) if r is not None else None
        info = speakers.get(c.speaker or "")
        sp = info["p_female"] if info and info["seconds"] >= MIN_SPEAKER else None
        c.gender = decide(p, sp)
    return speakers
