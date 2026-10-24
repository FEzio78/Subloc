"""Who each line is spoken to, decided over whole scenes before translating (PLAN.md 2.7, step e).

Translating while also choosing the listener, the model sees 25 lines plus a few around them; on a film it left
30% of lines without a listener and picked the wrong one on many others. Here it reads whole scenes (up to
LISTEN_BATCH lines, who speaks and how each voice sounds) and only answers who each line is for, so the
translation can then take the listener as given (translate(..., listeners=...)).
"""

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .glossary import Glossary
from .langs import lang_name
from .llm import LMStudio
from .models import Cue
from .voices import likely_speaker, listener_choices

LISTEN_BATCH = 60  # lines per request: whole scenes where they fit
CONTEXT = 10  # lines shown before / after a long scene's piece
TO_OTHER = ["several", "unknown"]
VOICE = {"male": "man", "female": "woman"}


def _system(src: str, title: str | None) -> str:
    s = (
        f"You read the subtitles of a video in {src}, scene by scene, and work out who each line is spoken to. "
        'Each line says who speaks ("speaker", e.g. "S1") and how the voice sounds ("voice": "man" or "woman", '
        'measured from the audio; missing = not known); "people" lists who speaks in each scene. Speaker ids can '
        "be wrong now and then (two people under one id): when a line's voice differs from how its speaker sounds in "
        "\"people\", the line is probably someone else's (in a two-person scene, the other person's). People who "
        "listen without speaking are not listed. "
        'For every line answer "to": the speaker id of the person it is spoken to, "several" when it speaks to '
        'more than one person (a group, a team, a crowd, "all of you", "guys", a speech; and the lines after it '
        'until someone else is clearly addressed), or "unknown" when it speaks to nobody in particular or you '
        'cannot tell. "to" is never the line\'s own speaker. Use the whole scene: the next person to speak is '
        "usually the one who was addressed; a question is usually answered by its listener; a name said to "
        "someone names the listener, and the same name later points to the same person; in a scene with two "
        "speakers each talks to the other; a line to someone who does not speak in the scene (a customer, a "
        'child, someone on the phone) is "unknown" unless their voice is listed. Do not translate anything.'
    )
    if title:
        s += f"\n\nThe video is titled: {title}"
    return s


def chunks(cues: list[Cue], scene: dict[int, int]) -> list[tuple[list[Cue], list[Cue], list[Cue]]]:
    """(before, lines, after) per request: whole scenes packed up to LISTEN_BATCH lines; a longer scene in
    pieces, each with CONTEXT lines around it."""
    by_scene: dict[int, list[Cue]] = {}
    for c in cues:
        by_scene.setdefault(scene[c.id], []).append(c)
    pos = {c.id: i for i, c in enumerate(cues)}
    out: list[tuple[list[Cue], list[Cue], list[Cue]]] = []
    cur: list[Cue] = []
    for lines in by_scene.values():
        if len(lines) > LISTEN_BATCH:
            if cur:
                out.append(([], cur, []))
                cur = []
            for k in range(0, len(lines), LISTEN_BATCH):
                piece = lines[k : k + LISTEN_BATCH]
                i0, i1 = pos[piece[0].id], pos[piece[-1].id]
                out.append((cues[max(0, i0 - CONTEXT) : i0], piece, cues[i1 + 1 : i1 + 1 + CONTEXT]))
            continue
        if cur and len(cur) + len(lines) > LISTEN_BATCH:
            out.append(([], cur, []))
            cur = []
        cur += lines
    if cur:
        out.append(([], cur, []))
    return out


def _line(c: Cue, scene: int, people: dict[int, list[str]], voice: dict[str, str | None]) -> str:
    item: dict = {"id": c.id, "scene": scene}
    if speaker := likely_speaker(c, people.get(scene, []), voice):
        item["speaker"] = speaker
    if c.gender in VOICE:
        item["voice"] = VOICE[c.gender]
    item["text"] = c.text
    return json.dumps(item, ensure_ascii=False)


def _user(before: list[Cue], lines: list[Cue], after: list[Cue], scene: dict[int, int],
          people: dict[int, list[str]], voice: dict[str, str | None],
          names: dict[str, str] | None = None) -> str:  # fmt: skip
    parts = []
    if names:  # known from the folder's name list (earlier lines and episodes)
        parts.append("People's names and genders known so far: "
                     + ", ".join(f"{n} ({VOICE[g]})" for n, g in names.items()))  # fmt: skip
    if before:
        parts.append("CONTEXT ONLY — lines just before, no answer needed:\n"
                     + "\n".join(_line(c, scene[c.id], people, voice) for c in before))  # fmt: skip
    if after:
        parts.append("CONTEXT ONLY — lines just after, no answer needed:\n"
                     + "\n".join(_line(c, scene[c.id], people, voice) for c in after))  # fmt: skip
    rows = []
    for n in dict.fromkeys(scene[c.id] for c in lines):
        cast = [f"{s} ({VOICE[g]})" if (g := voice.get(s)) else s for s in people.get(n, [])]
        rows.append(f"scene {n}: " + (", ".join(cast) or "nobody known"))
    parts.append("People speaking (voice from the audio):\n" + "\n".join(rows))
    parts.append('For every line below, one item with its "id" and "to", same order:\n\n'
                 + "\n".join(_line(c, scene[c.id], people, voice) for c in lines))  # fmt: skip
    return "\n\n".join(parts)


def schema_for(lines: list[Cue], choices: dict[int, list[str]]) -> dict:
    """One schema per position (see translate.schema_for): its own id, and a "to" from the people of its own scene
    other than its speaker (`choices`: cue id → those ids)."""
    items = [{"type": "object",
              "properties": {"id": {"type": "integer", "enum": [c.id]},
                             "to": {"type": "string", "enum": choices[c.id] + TO_OTHER}},
              "required": ["id", "to"]} for c in lines]  # fmt: skip
    return {"type": "object", "properties": {"lines": {"type": "array", "minItems": len(lines),
            "maxItems": len(lines), "prefixItems": items}}, "required": ["lines"]}  # fmt: skip


def _parse(content: str, lines: list[Cue], choices: dict[int, list[str]]) -> dict[int, str | None]:
    want = {c.id for c in lines}
    try:
        raw = json.loads(content)["lines"]
    except (ValueError, KeyError, TypeError):
        return {}
    out: dict[int, str | None] = {}
    for x in raw if isinstance(raw, list) else []:
        try:
            i, to = int(x["id"]), str(x["to"])
        except (KeyError, TypeError, ValueError):
            continue
        if i in want and (to in choices[i] or to in TO_OTHER):
            out[i] = None if to == "unknown" else to
    return out


def decide(
    cues: list[Cue],
    client: LMStudio,
    model: str,
    src_code: str | None,
    scene: dict[int, int],
    people: dict[int, list[str]],
    voice: dict[str, str | None],
    title: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    log: Callable[[str], None] = print,
    workers: int = 2,
    should_stop: Callable[[], bool] = lambda: False,
    glossary: Glossary | None = None,
) -> dict[int, str | None]:
    """cue id → who it is spoken to ("S2", "several", None = nobody in particular / not known). Lines whose request
    fails are left out: translation then decides their listener itself, as without this pass."""
    system = _system(lang_name(src_code), title)
    work = chunks(cues, scene)
    found: dict[int, str | None] = {}
    lock = threading.Lock()
    done = [0]

    def run(part: tuple[list[Cue], list[Cue], list[Cue]]) -> None:
        before, lines, after = part
        if should_stop():
            return
        choices = {c.id: listener_choices(c, people.get(scene[c.id], []), voice) for c in lines}
        names = {}
        if glossary is not None:
            for form in glossary.relevant(" ".join(c.text for c in [*before, *lines, *after])):
                if (g := glossary.gender_of(form)) in VOICE:
                    names[form] = g
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": _user(before, lines, after, scene, people, voice, names)}]  # fmt: skip
        got: dict[int, str | None] = {}
        for _attempt in range(2):
            try:
                got = _parse(client.chat(model, msgs, json_schema=schema_for(lines, choices), temperature=0.2,
                                         reasoning="none"), lines, choices)  # fmt: skip
            except Exception as e:  # the translation pass still decides these itself (also: format refused)
                log(f"  listeners for lines {lines[0].id}-{lines[-1].id}: {type(e).__name__}: {e}")
                continue
            if len(got) == len(lines):
                break
        with lock:
            found.update(got)
            done[0] += len(lines)
            if on_progress:
                on_progress(done[0], len(cues))

    with ThreadPoolExecutor(max(1, workers)) as ex:
        list(ex.map(run, work))
    return found
