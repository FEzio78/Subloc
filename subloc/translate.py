"""Batch translation of numbered cues through a local LLM. Timestamps never leave the app."""

import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .errors import ContextTooLong, ModelNotAvailable, TranslatorUnavailable
from .glossary import Glossary
from .langs import LANGS, NUMBERS_RULE, TARGET_BRIEF, clean_output, lang_name
from .llm import LMStudio
from .models import Cue
from .segment import continuation_flags, max_chars

BATCH = 25
CONTEXT_BEFORE = 8
CONTEXT_AFTER = 3
RETRIES = 2
PARALLEL = 2  # concurrent requests by default: gentle on VRAM next to a ~16 GB model
MAX_PARALLEL = 4  # user can raise it; 4 was ~2.3x throughput when VRAM had room


def schema_for(batch: list[Cue]) -> dict:
    """Response format for one request. The server enforces it while generating, so the model can't
    stop after the first line (it did, reproducibly, on some batches: 0/3 complete answers without
    the item count, 3/3 with it) and can't invent ids. "src" (the line's first words, copied) anchors
    each translation to its own line and lets _parse detect lines that slid onto a neighbour."""
    ids = [c.id for c in batch]
    return {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "enum": ids},
                        "src": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["id", "src", "text"],
                },
            }
        },
        "required": ["lines"],
    }


def _system(src: str, tgt: str, tgt_code: str, title: str | None) -> str:
    s = (
        f"You translate video subtitles from {src} into {tgt}. "
        f"Each input line is one subtitle shown on screen. Keep the speaker's tone (casual, rude, polite, joking). "
        f"Subtitles must be short and easy to read: stay within each line's max_chars when you can, "
        f"dropping filler words rather than meaning. Never add notes or explanations. " + NUMBERS_RULE
    )
    if tgt_code in TARGET_BRIEF:
        s += " " + TARGET_BRIEF[tgt_code]
    if src == LANGS["mixed"]:
        s += ' The speech switches language; each line says its language in "lang".'
    s += (
        ' Lines with "kind": "song" are song lyrics: translate them as lyrics.'
        ' Lines with "kind": "caption" are on-screen signs or notes.'
    )
    s += (
        ' Resolve pronouns, grammatical number and gender from context: if "you" addresses several people '
        "use the plural form; if it addresses one person, match that person's gender when the context shows it."
    )
    if title:
        s += f"\n\nThe video is titled: {title}"
    return s


def _batches(cues: list[Cue]) -> list[list[Cue]]:
    """Batches of ~BATCH cues that never cut a sentence group in half."""
    out: list[list[Cue]] = []
    cur: list[Cue] = []
    for c, cont in zip(cues, continuation_flags(cues), strict=True):
        if len(cur) >= BATCH and not cont:
            out.append(cur)
            cur = []
        cur.append(c)
    if cur:
        out.append(cur)
    return out


def _user(batch: list[Cue], before: list[Cue], after: list[Cue], continues: dict[int, bool], src: str, tgt: str) -> str:
    """`continues`: cue id → is the rest of the previous cue's sentence (see continuation_flags)."""
    lines = []
    for c in batch:
        item = {"id": c.id, "max_chars": max_chars(c), "text": c.text}
        if c.speaker:
            item["speaker"] = c.speaker
        if c.lang and src == LANGS["mixed"]:
            item["lang"] = lang_name(c.lang)
        if c.kind in ("song", "caption"):
            item["kind"] = c.kind
        if continues.get(c.id):
            item["continues"] = True
        lines.append(json.dumps(item, ensure_ascii=False))

    parts = []
    if before:
        # Pairs when the previous batch is already done; source only when it is being translated in parallel.
        prev = "\n".join(
            f"{src}: {c.text}\n{tgt}: {c.translation}" if c.translation else f"{src}: {c.text}" for c in before
        )
        parts.append(f"CONTEXT ONLY — previous lines, do not translate or repeat:\n{prev}")
    if after:
        parts.append("CONTEXT ONLY — upcoming lines, do not translate:\n" + "\n".join(c.text for c in after))
    parts.append(
        f"Translate every line below into {tgt}. Return exactly one output item per id, same ids, "
        f"in the same order. Never merge several ids into one item and never skip an id.\n"
        f"For each item, first copy the first few words (up to 12 characters) of THAT line's original text into "
        f'"src", then write its translation in "text". Each translation must say what its own line says.\n'
        f'Lines marked "continues": true finish the previous line\'s sentence (common in {src}, where the verb '
        f"comes last): translate the sentence as a whole, but keep each part's meaning in its own id; move words "
        f"between those lines only where {tgt} grammar requires it.\n\n" + "\n".join(lines)
    )
    return "\n\n".join(parts)


_OBJ = re.compile(r"\{[^{}]*\}")


def _items(content: str) -> list[tuple[int, str, str]]:
    """(id, src, text) in the order the model wrote them. Falls back to salvaging every complete item
    when the JSON is broken or cut off."""
    content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
    try:
        raw = json.loads(content)["lines"]
    except (ValueError, KeyError, TypeError):
        raw = []
        for obj in _OBJ.findall(content):
            try:
                raw.append(json.loads(obj))
            except ValueError:
                continue
    out = []
    for x in raw:
        try:
            out.append((int(x["id"]), str(x.get("src", "")).strip(), str(x["text"]).strip()))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", s.lower())


def anchored(src_echo: str, line: str) -> bool:
    """Does the model's copy of a line's start really come from that line? False means the translation
    slid onto the wrong line. No copy at all (servers without enforced formats) can't be checked: accept."""
    echo = _norm(src_echo)[:6]
    return not echo or echo in _norm(line)


def _parse(content: str, batch: list[Cue] | None = None) -> dict[int, str]:
    """Map id → translation, dropping lines whose "src" copy doesn't match (they are asked again).
    With `batch`, also repair miswritten ids by position (e.g. 503 for 533) when the count is right."""
    items = _items(content)
    if batch is None:
        return {i: t for i, _, t in items}
    text_of = {c.id: c.text for c in batch}
    want = [c.id for c in batch]
    if len(items) == len(want):
        returned = [i for i, _, _ in items]
        fixed = [w if (r not in want or returned.count(r) > 1) else r for r, w in zip(returned, want, strict=True)]
        if sorted(fixed) == sorted(want):
            items = [(i, src, t) for i, (_, src, t) in zip(fixed, items, strict=True)]
    # A one-line request can't slide onto a neighbour, so its copy isn't checked (models sometimes copy a
    # context line there instead, which would wrongly drop a correct translation).
    check = len(want) > 1
    return {i: t for i, src, t in items if i in text_of and t and (not check or anchored(src, text_of[i]))}


def translate(
    cues: list[Cue],
    client: LMStudio,
    model: str,
    src_code: str | None,
    tgt_code: str,
    title: str | None = None,
    glossary: Glossary | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_batch_done: Callable[[], None] | None = None,
    log: Callable[[str], None] = print,
    workers: int = PARALLEL,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """Fill cue.translation in place. Skips cues already translated (resume)."""
    src, tgt = lang_name(src_code), lang_name(tgt_code)
    system = _system(src, tgt, tgt_code, title)
    pos = {c.id: i for i, c in enumerate(cues)}
    flags = {c.id: f for c, f in zip(cues, continuation_flags(cues), strict=True)}

    def call(batch: list[Cue]) -> dict[int, str]:
        i0, i1 = pos[batch[0].id], pos[batch[-1].id]
        before = cues[max(0, i0 - CONTEXT_BEFORE) : i0]
        after = cues[i1 + 1 : i1 + 1 + CONTEXT_AFTER]
        ids = {c.id for c in batch}
        # Only mark a continuation when the cue it continues is in this same request.
        cont = {c.id: flags[c.id] and pos[c.id] > 0 and cues[pos[c.id] - 1].id in ids for c in batch}
        user = _user(batch, before, after, cont, src, tgt)
        if glossary:
            # Only the names that occur here (glossary may be large; keeps prompts small and focused).
            names = glossary.relevant(" ".join(c.text for c in [*before, *batch, *after]))
            if names:
                rules = "\n".join(f'- "{k}" → "{v}"' for k, v in names.items())
                user = (
                    f"Names and terms — use these spellings whenever the word is that name or term:\n{rules}\n"
                    f"The text comes from speech recognition: if a listed term clearly makes no sense as a "
                    f"name in a line, it was probably a misheard ordinary word, so translate the meaning.\n\n{user}"
                )
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        raw = client.chat(model, msgs, json_schema=schema_for(batch), temperature=0.3, reasoning="none")
        return {i: clean_output(t, tgt_code) for i, t in _parse(raw, batch).items()}

    def call_fitting(batch: list[Cue]) -> dict[int, str]:
        """call(), halving the batch whenever it doesn't fit the model's context window."""
        try:
            return call(batch)
        except ContextTooLong:
            if len(batch) == 1:
                raise
            mid = len(batch) // 2
            return {**call_fitting(batch[:mid]), **call_fitting(batch[mid:])}

    fatal: list[Exception] = []  # translator gone / model missing: stop everything, keep progress
    stopped = lambda: should_stop() or bool(fatal)  # noqa: E731

    lock = threading.Lock()
    done = sum(1 for c in cues if c.translation)

    def run_batch(todo: list[Cue]) -> None:
        nonlocal done
        if stopped():
            return
        # Keep every good line from each answer; only ask again for what's still missing
        # (re-asked lines now see their translated neighbours as context).
        remaining = todo
        for attempt in range(RETRIES + 1):
            if not remaining or stopped():
                break
            try:
                got = call_fitting(remaining)
            except (TranslatorUnavailable, ModelNotAvailable) as e:
                fatal.append(e)
                return
            except Exception as e:  # unusable output, a one-off server error
                log(f"  lines {remaining[0].id}-{remaining[-1].id}: {type(e).__name__}: {e}, retrying")
                time.sleep(1.5 * (attempt + 1))
                continue
            for c in remaining:
                if got.get(c.id):
                    c.translation = got[c.id]
            missing = [c for c in remaining if not c.translation]
            if missing:
                log(
                    f"  lines {remaining[0].id}-{remaining[-1].id}: {len(missing)} of {len(remaining)} "
                    f"missing, asking again for those"
                )
            remaining = missing
        # Fallback: one line at a time for anything still missing.
        for c in todo:
            if c.translation or stopped():
                continue
            try:
                c.translation = call([c]).get(c.id) or None
            except (TranslatorUnavailable, ModelNotAvailable) as e:
                fatal.append(e)
                return
            except Exception as e:
                log(f"  line {c.id} failed: {e}")
        with lock:
            done += len(todo)
            if on_progress:
                on_progress(done, len(cues))
            if on_batch_done:
                on_batch_done()

    batches = [todo for b in _batches(cues) if (todo := [c for c in b if not c.translation])]
    if not batches:
        return
    # First batch alone so the next ones start with real translated context (names, tone).
    run_batch(batches[0])
    with ThreadPoolExecutor(max(1, workers)) as ex:
        for f in [ex.submit(run_batch, b) for b in batches[1:]]:
            f.result()
    if fatal:
        raise fatal[0]
