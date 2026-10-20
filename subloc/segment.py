"""Turn raw ASR segments into readable subtitle cues and sentence groups."""

from .models import Cue, Word, renumber

# Bump when the rules below change: saved projects are re-split from their raw transcript.
SEGMENT_VERSION = 2

MAX_DUR = 7.0  # seconds on screen, hard limit
SPLIT_PAUSE = 0.6  # a pause this long starts a new cue
SOFT_DUR = 3.5  # past this, split at the next punctuation
MIN_DUR = 1.0
MIN_GAP = 0.08
READ_CPS = 17  # target-language reading speed (chars / second)
SENTENCE_END = tuple(".?!。？！…♪\"'」』)")
CLAUSE_END = tuple(",，、;；:：")


def _text(words: list[Word]) -> str:
    # Whisper word tokens carry their own leading spaces (none for CJK).
    return "".join(w.text for w in words).strip()


MIN_PART_DENSE = 4  # min characters for a split-off part in CJK text (one char ≈ one syllable/word)
MIN_PART = 10  # min characters elsewhere


def _is_dense(text: str) -> bool:
    """Chinese / Japanese / Korean: many meaning-carrying characters, no spaces."""
    cjk = sum(1 for ch in text if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" or "가" <= ch <= "힯")
    return cjk > len(text) / 2


def _merge_small(parts: list[list[Word]]) -> list[list[Word]]:
    """Fold parts that are too short to stand alone (e.g. 'ここ' | 'で殺すか' split at a dramatic pause)
    back into a neighbour, so no subtitle is a lone particle or half a word."""
    out: list[list[Word]] = []
    for p in parts:
        text = _text(p)
        small = len(text) < (MIN_PART_DENSE if _is_dense(text) else MIN_PART)
        if out and (small or len(_text(out[-1])) < (MIN_PART_DENSE if _is_dense(_text(out[-1])) else MIN_PART)):
            out[-1] = out[-1] + p
        else:
            out.append(p)
    return out


def split_cue(cue: Cue) -> list[Cue]:
    if not cue.words or cue.duration <= SOFT_DUR:
        return [cue]
    parts: list[list[Word]] = [[]]
    for w in cue.words:
        cur = parts[-1]
        if cur:
            dur = w.end - cur[0].start
            prev = cur[-1]
            pause = w.start - prev.end
            end_tok = prev.text.strip()
            soft = dur > SOFT_DUR and end_tok.endswith(SENTENCE_END + CLAUSE_END)
            if pause >= SPLIT_PAUSE or dur > MAX_DUR or soft:
                parts.append([])
        parts[-1].append(w)
    parts = _merge_small(parts)
    return [
        Cue(
            id=0,
            start=p[0].start,
            end=p[-1].end,
            text=_text(p),
            source=cue.source,
            kind=cue.kind,
            speaker=cue.speaker,
            words=p,
            confidence=cue.confidence,
            lang=cue.lang,
        )
        for p in parts
        if p and _text(p)
    ]


def segment(cues: list[Cue]) -> list[Cue]:
    out = [c for cue in cues for c in split_cue(cue)]
    if not out:  # no speech at all (music, silence): the caller reports it
        return []
    out.sort(key=lambda c: c.start)
    # Minimum display time without overlapping the next cue.
    for a, b in zip(out, [*out[1:], None], strict=True):
        if a.duration < MIN_DUR:
            limit = b.start - MIN_GAP if b else a.start + MIN_DUR
            a.end = max(a.end, min(a.start + MIN_DUR, limit))
        if b and a.end > b.start - MIN_GAP:
            a.end = max(a.start + 0.3, b.start - MIN_GAP)
    return renumber(out)


def max_chars(cue: Cue) -> int:
    """How many target characters fit in this cue's time on screen (2 lines max)."""
    return int(min(84, max(16, cue.duration * READ_CPS)))


MAX_CHAIN = 3  # a sentence group is at most 4 cues, even when punctuation is missing


def continues_previous(prev: Cue | None, cue: Cue) -> bool:
    """True if `cue` looks like the rest of the sentence started in `prev`.
    Whisper often leaves out final punctuation (Turkish especially), so a capital letter at the
    start of `cue` also counts as a new sentence in languages that have capitals."""
    if prev is None or cue.start - prev.end >= 1.0:
        return False
    if prev.text.rstrip().endswith(SENTENCE_END):
        return False
    first = next((ch for ch in cue.text.lstrip("-–—\"'«„“ ") if ch.isalpha()), "")
    return not (first and first.isupper())


def continuation_flags(cues: list[Cue]) -> list[bool]:
    """continues_previous for every cue, with chains capped at MAX_CHAIN so a transcript without
    punctuation can't become one endless 'sentence'."""
    flags, chain = [], 0
    for i, c in enumerate(cues):
        f = continues_previous(cues[i - 1] if i else None, c) and chain < MAX_CHAIN
        chain = chain + 1 if f else 0
        flags.append(f)
    return flags
