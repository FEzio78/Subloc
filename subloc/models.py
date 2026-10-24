"""Core data types shared by every stage."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Word:
    start: float
    end: float
    text: str
    prob: float = 1.0


@dataclass
class Cue:
    id: int
    start: float
    end: float
    text: str  # source language
    source: str = "asr"  # asr | ocr | subs | merged
    kind: str = "dialogue"  # dialogue | caption | sfx | narration | song
    speaker: str | None = None  # "S1", "S2"… (subloc.voices), None = not known
    gender: str | None = None  # the voice: "male" | "female" | None (not known; subloc.voices)
    to: str | None = None  # who the line is spoken to, as the translator decided: "S2" | "several" | None
    translation: str | None = None
    words: list[Word] = field(default_factory=list)
    confidence: float = 1.0
    position: str = "bottom"  # bottom | middle | top (where it was on screen)
    lang: str | None = None  # per-line language (mixed-language videos)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Project:
    video: str
    language: str | None = None
    asr_cues: list[Cue] = field(default_factory=list)
    ocr_cues: list[Cue] = field(default_factory=list)
    cues: list[Cue] = field(default_factory=list)  # final, fused + segmented
    target_language: str | None = None
    meta: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "Project":
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("asr_cues", "ocr_cues", "cues"):
            data[key] = [_cue(c) for c in data.get(key, [])]
        # Fields a newer (or older) Subloc wrote that this one doesn't know are left out, not an error.
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _cue(d: dict) -> Cue:
    d = {k: v for k, v in d.items() if k in Cue.__dataclass_fields__}
    d["words"] = [Word(**{k: v for k, v in w.items() if k in Word.__dataclass_fields__}) for w in d.get("words", [])]
    return Cue(**d)


def renumber(cues: list[Cue]) -> list[Cue]:
    cues.sort(key=lambda c: (c.start, c.end))
    for i, c in enumerate(cues, 1):
        c.id = i
    return cues
