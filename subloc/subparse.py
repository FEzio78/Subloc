"""Parse existing subtitles (ASS/SSA or SRT text) into cues."""

import re

from .models import Cue, renumber

_TAG = re.compile(r"\{[^}]*\}")
_DRAWING = re.compile(r"\\p[1-9]")
_POS_Y = re.compile(r"\\pos\(\s*[-\d.]+\s*,\s*([-\d.]+)\s*\)")
_HTML = re.compile(r"</?[a-zA-Z][^>]*>")
_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
_LATIN = re.compile(r"[A-Za-z]")
_NON_LATIN = re.compile(r"[\u0400-\u04FF\u0600-\u06FF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF\u0E00-\u0E7F]")
NON_LATIN_LANGS = {"ja", "zh", "ko", "ru", "uk", "ar", "fa", "th", "hi"}


def _ass_time(t: str) -> float:
    h, m, s = t.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_ass(text: str) -> list[Cue]:
    fields: list[str] | None = None
    raw: list[tuple[float, float, str, bool, bool, float]] = []
    in_events = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            in_events = line.lower() == "[events]"
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            fields = [f.strip().lower() for f in line[7:].split(",")]
            continue
        if not line.lower().startswith("dialogue:") or not fields:
            continue
        parts = line[9:].split(",", len(fields) - 1)
        row = dict(zip(fields, (p.strip() for p in parts), strict=False))  # malformed lines may be short
        body = row.get("text", "")
        if _DRAWING.search(body):
            continue  # vector drawings, not text
        pos = _POS_Y.search(body)
        italic = "\\i1" in body
        clean = _TAG.sub("", body).replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
        clean = " ".join(clean.split())
        if clean:
            raw.append(
                (
                    _ass_time(row["start"]),
                    _ass_time(row["end"]),
                    clean,
                    bool(pos),
                    italic,
                    float(pos.group(1)) if pos else 0.0,
                )
            )

    # Signs are often split into one event per line at the same time: join them top-to-bottom.
    # Identical events (outline/shadow layers) collapse into one.
    groups: dict[tuple[float, float, bool], list] = {}
    for start, end, t, positioned, italic, y in raw:
        groups.setdefault((start, end, positioned), []).append((y, t, italic))
    cues = []
    for (start, end, positioned), items in groups.items():
        items.sort(key=lambda x: x[0])
        seen, texts = set(), []
        for _, t, _ in items:
            if t not in seen:
                seen.add(t)
                texts.append(t)
        kind = "caption" if positioned else ("song" if all(i[2] for i in items) else "dialogue")
        cues.append(Cue(id=0, start=start, end=end, text=" ".join(texts), source="subs", kind=kind))
    return renumber(cues)


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = _SRT_TIME.search(ln)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            body = " ".join(lines[i + 1 :])
            italic = "<i>" in body.lower()
            body = " ".join(_TAG.sub("", _HTML.sub("", body)).split())
            if body:
                cues.append(
                    Cue(
                        id=0,
                        start=start,
                        end=end,
                        text=body,
                        source="subs",
                        kind="song" if italic and body.startswith(("♪", "#")) else "dialogue",
                    )
                )
            break
    return renumber(cues)


def parse(text: str) -> list[Cue]:
    return parse_ass(text) if "[Events]" in text or "Dialogue:" in text else parse_srt(text)


def guess_language(cues: list[Cue], tagged: str | None) -> str | None:
    """Container tags are often wrong (e.g. an English track tagged 'jpn'). Keep the tag only if
    the script agrees; None means 'let the translator detect it'."""
    sample = " ".join(c.text for c in cues[:200])
    latin, other = len(_LATIN.findall(sample)), len(_NON_LATIN.findall(sample))
    mostly_latin = latin > 3 * other
    if tagged in NON_LATIN_LANGS and mostly_latin:
        return None
    if tagged and tagged not in NON_LATIN_LANGS and not mostly_latin:
        return None
    return tagged
