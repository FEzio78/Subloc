"""SRT writer with line wrapping and right-to-left fixes."""

from dataclasses import dataclass
from pathlib import Path

from .langs import LINE, NO_SPACES, line_width
from .models import Cue
from .segment import continues_previous

RTL = {"ar", "fa", "ur", "he"}
RLM = "\u200f"  # right-to-left mark


def _ts(t: float) -> str:
    ms = round(max(t, 0) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


CJK_BREAK_AFTER = "，。、！？；：,.!?…）」』"


def wrap(text: str, width: int = LINE, lang: str | None = None) -> list[str]:
    """Two balanced lines when it doesn't fit on one. Chinese and Japanese break between characters (after
    punctuation when there is some near the middle); other languages break at the space nearest the middle."""
    text = " ".join(text.split())
    if len(text) <= width:
        return [text]
    mid = len(text) // 2
    if " " in text and lang not in NO_SPACES:
        spaces = [i for i, ch in enumerate(text) if ch == " "]
        cut = min(spaces, key=lambda i: abs(i - mid))
        return [text[:cut], text[cut + 1 :]]
    if lang in NO_SPACES:
        marks = [i + 1 for i, ch in enumerate(text[:-1]) if ch in CJK_BREAK_AFTER]
        near = min(marks, key=lambda i: abs(i - mid)) if marks else mid
        cut = near if abs(near - mid) <= width // 3 else mid  # punctuation, unless it makes lopsided lines
        return [text[:cut].strip(), text[cut:].strip()]
    return [text]  # no spaces to break at (Thai, a long word): one line rather than a broken word


SHORT = 1.0  # cues shorter than this get paired with a neighbour
PAIR_GAP = 0.5  # max silence between the two paired lines
PAIR_MAX = 6.0  # max duration of a paired cue


@dataclass
class DisplayCue:
    start: float
    end: float
    lines: list[str]
    italic: bool = False  # song lyrics


def build_display(cues: list[Cue], translated: bool, lang: str | None = None) -> list[DisplayCue]:
    """Pair very short lines with a neighbour as a two-line dialogue cue ("- …" / "- …"),
    the way professional subtitles avoid lines that flash by too fast to read."""
    width = line_width(lang)
    kept = [c for c in cues if (c.translation if translated else c.text)]
    items = [(c.start, c.end, ((c.translation if translated else c.text) or "").strip()) for c in kept]
    out: list[DisplayCue] = []
    i = 0
    while i < len(items):
        s, e, t = items[i]
        if i + 1 < len(items):
            s2, e2, t2 = items[i + 1]
            short = (e - s) < SHORT or (e2 - s2) < SHORT
            fits = len(t) <= width and len(t2) <= width
            # Don't pair two lines of one sentence, or a line whose sentence runs on into the next cue.
            joined = continues_previous(kept[i], kept[i + 1]) or (
                i + 2 < len(kept) and continues_previous(kept[i + 1], kept[i + 2])
            )
            same_kind = (kept[i].kind == "song") == (kept[i + 1].kind == "song")
            if short and fits and same_kind and not joined and s2 - e <= PAIR_GAP and e2 - s <= PAIR_MAX:
                out.append(DisplayCue(s, e2, [f"- {t}", f"- {t2}"], kept[i].kind == "song"))
                i += 2
                continue
        out.append(DisplayCue(s, e, wrap(t, width, lang), kept[i].kind == "song"))
        i += 1
    return out


def write_srt(cues: list[Cue], path: Path, translated: bool, lang: str | None = None) -> None:
    rtl = lang in RTL
    blocks = []
    for n, d in enumerate(build_display(cues, translated, lang), 1):
        lines = d.lines
        if rtl:
            # Anchor each line as RTL so leading/trailing punctuation lands on the correct side.
            lines = [f"{RLM}{ln}{RLM}" for ln in lines]
        if d.italic:
            lines = [f"<i>{ln}</i>" for ln in lines]
        blocks.append(f"{n}\n{_ts(d.start)} --> {_ts(d.end)}\n" + "\n".join(lines))
    # UTF-8 with BOM: some TVs / older players need it to detect Arabic correctly.
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8-sig")
