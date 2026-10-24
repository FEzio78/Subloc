"""Name glossary: one target spelling per name, consistent across a video and across a series.

1. extract(): the LLM reads the transcript in chunks and lists people, places, organisations,
   nicknames and recurring terms, grouping spelling variants (Whisper often hears a name two ways)
   under one target spelling.
2. Saved as `subloc.glossary.json` in the video's folder, so the next episode reuses it.
   Entries the user edits there always win.
3. relevant(): only the entries that appear in a batch go into that batch's prompt.
4. People get a gender when it is clear: from the text (titles, well-known names: the name pass) or, more
   reliably, from voices: a name said to someone ("Meryem, come here") votes for that listener's voice
   (learn_genders). So the next lines and episodes know Meryem is a woman even where the audio can't tell.
"""

import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .errors import ModelNotAvailable, TranslatorUnavailable
from .langs import NUMBERS_RULE, TARGET_BRIEF, clean_output, fixed_name
from .llm import LMStudio
from .models import Cue

FILE_NAME = "subloc.glossary.json"
CHUNK = 150  # transcript lines per extraction request
MAX_PROMPT_TERMS = 60  # known terms passed to the extractor (keeps prompts small)

SCHEMA = {
    "type": "object",
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "variants": {"type": "array", "items": {"type": "string"}},
                    "target": {"type": "string"},
                    "type": {"type": "string", "enum": ["person", "place", "organization", "term"]},
                    "gender": {"type": "string", "enum": ["male", "female", "unknown"]},
                },
                "required": ["source", "variants", "target", "type", "gender"],
            },
        }
    },
    "required": ["terms"],
}


@dataclass
class Term:
    source: str
    target: str
    type: str = "person"
    variants: list[str] = field(default_factory=list)
    user: bool = False  # edited by the user: never overwritten
    gender: str | None = None  # people: "male" | "female" | None (not known)
    gender_from: str | None = None  # "name" (the text says it) | "voices" (heard: stronger) | "user"

    def forms(self) -> list[str]:
        return [f for f in [self.source, *self.variants] if f]


@dataclass
class Glossary:
    target_lang: str
    terms: list[Term] = field(default_factory=list)

    # ---------- lookup

    def find(self, form: str) -> Term | None:
        f = form.strip().lower()
        return next((t for t in self.terms if f in (x.lower() for x in t.forms())), None)

    def gender_of(self, form: str) -> str | None:
        t = self.find(form)
        return t.gender if t is not None and t.type == "person" else None

    def learn_genders(self, cues: list[Cue], voice: dict[str, str | None]) -> int:
        """Give people the gender of the voice their name is said to. A line that calls someone by name (at its
        start or end: _calls) counts for its listener (cue.to) when that listener's voice is known; 2 lines that
        agree, or 3+ with 80% agreeing, decide. Never changes what the user set. Returns how many changed.
        Measured on a Turkish episode: three men's names 9/9, 3/3 and 5/6 male (as the names say), one name 2/2
        female (the name pass couldn't tell); one woman's name had 1 vote (the wrong one): too few, left alone."""
        changed = 0
        for t in self.terms:
            if t.type != "person" or t.user or t.gender_from == "user":
                continue
            votes: list[str] = []
            for c in cues:
                g = voice.get(c.to or "")
                if g and any(_calls(c.text, f) for f in t.forms() if len(f) >= 2):
                    votes.append(g)
            if len(votes) < 2:
                continue
            top = max(("male", "female"), key=votes.count)
            agree = votes.count(top) == len(votes) if len(votes) == 2 else votes.count(top) >= 0.8 * len(votes)
            if agree and (t.gender, t.gender_from) != (top, "voices"):
                t.gender, t.gender_from = top, "voices"
                changed += 1
        return changed

    def relevant(self, text: str) -> dict[str, str]:
        """Entries whose source or a variant appears in `text` (substring match, so inflected forms
        like Russian 'Демяткова' still match 'Демятков')."""
        low = text.lower()
        out = {}
        for t in self.terms:
            for f in t.forms():
                if len(f) >= 2 and f.lower() in low:
                    out[f] = t.target
        return out

    # ---------- merge

    def add(self, new: Term) -> None:
        """Add or merge. Existing spellings win (consistency beats the latest guess)."""
        hit = next((t for t in self.terms if {f.lower() for f in t.forms()} & {f.lower() for f in new.forms()}), None)
        if hit is None:
            self.terms.append(new)
            return
        if new.gender and not hit.gender and not hit.user:  # a gender learnt since fills a gap, never overwrites
            hit.gender, hit.gender_from = new.gender, new.gender_from
        for v in new.forms():
            if v.lower() not in (f.lower() for f in hit.forms()):
                hit.variants.append(v)

    # ---------- files

    def save(self, path: Path) -> None:
        data = {"target_lang": self.target_lang, "terms": [asdict(t) for t in self.terms]}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, target_lang: str) -> "Glossary":
        if not path.exists():
            return cls(target_lang)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return cls(target_lang)  # a broken hand-edit must not stop the run
        if data.get("target_lang") != target_lang:
            return cls(target_lang)
        terms = [
            Term(**{k: v for k, v in t.items() if k in Term.__dataclass_fields__})
            for t in data.get("terms", [])
            if t.get("source") and t.get("target")
        ]
        for t in terms:  # heal entries saved before a rule existed (user edits are left alone)
            if not t.user and (fixed := fixed_name(t.source)):
                t.target = fixed
            elif not t.user:
                t.target = clean_output(t.target, target_lang)
        return cls(target_lang, terms)


def _calls(text: str, name: str) -> bool:
    """Is `name` likely used to call someone in this line: its first or last word ("Meryem, come here", "Where are
    you Meryem")? Speech recognition leaves out most commas (Turkish: 13 of 469 lines had one), so position is the
    clue. A name only talked about lands there too, but its listeners differ: learn_genders needs them to agree."""
    words = re.findall(r"\w+", text.lower())
    return bool(words) and name.lower() in (words[0], words[-1])


def folder_path(video: Path) -> Path:
    return video.parent / FILE_NAME


def _prompt(lines: list[str], src: str, tgt: str, known: Glossary, style: str = "") -> list[dict]:
    system = (
        f"You prepare a glossary for translating video subtitles from {src} into {tgt}. "
        f"List proper names (people, nicknames, places, organisations, brands, car models, ranks used as names) "
        f"and recurring special terms that must be translated the same way every time. "
        f"The text is a speech-recognition transcript, so one name may be misspelled in several ways: "
        f"put all spellings of the same name in 'variants' under one entry. "
        f"'source' is the bare name as written in the transcript, without titles such as Mr., Mrs., Dr. or -san. "
        f"'target' renders exactly that bare name in {tgt} (no added titles or words): transliterate personal "
        f"names, translate the meaning of place-like names only when {tgt} has an established form. "
        f"Skip ordinary words. Speech recognition often turns an ordinary word into a rare word or "
        f"name that sounds alike (e.g. 平氏 'the Taira clan' heard instead of 兵士 'soldiers', エース "
        f"instead of 兵士): if a 'name' only makes sense as a misheard ordinary word in its context, leave it "
        f"out. Only list terms you are confident are real names or terms. "
        f"For people, 'gender' is male or female only when the text makes it clear (a title such as Mr./Mrs., "
        f"Bey/Hanım, oppa/unni, or a name that is clearly a man's or a woman's name); otherwise unknown. "
        f"Return an empty list if there are none."
    )
    if style:
        system += f"\n\nRules for {tgt}: {style}"
    if known.terms:
        keep = "\n".join(f"- {t.source} → {t.target}" for t in known.terms[:MAX_PROMPT_TERMS])
        system += f"\n\nAlready decided — reuse these exact spellings, don't list them again:\n{keep}"
    return [{"role": "system", "content": system}, {"role": "user", "content": "Transcript:\n" + "\n".join(lines)}]


def extract(
    cues: list[Cue],
    client: LMStudio,
    model: str,
    src: str,
    tgt: str,
    known: Glossary,
    workers: int = 2,
    log: Callable[[str], None] = print,
    tgt_code: str = "",
) -> Glossary:
    """Return `known` extended with names found in `cues` (known entries are never changed)."""
    texts = [c.text for c in cues]
    full = "\n".join(texts).lower()
    chunks = [texts[i : i + CHUNK] for i in range(0, len(texts), CHUNK)]
    # Only show the extractor known names that occur in this video (the folder may hold other shows).
    known = (
        Glossary(known.target_lang, [t for t in known.terms if any(f.lower() in full for f in t.forms())])
        if known.terms
        else known
    )

    def run(chunk: list[str]) -> list[Term]:
        try:
            style = " ".join(filter(None, [TARGET_BRIEF.get(tgt_code, ""), NUMBERS_RULE]))
            prompt = _prompt(chunk, src, tgt, known, style)
            raw = client.chat(model, prompt, json_schema=SCHEMA, temperature=0.1)
            return [
                Term(
                    t["source"].strip(),
                    fixed_name(t["source"]) or clean_output(t["target"].strip(), tgt_code),
                    t.get("type", "term"),
                    [v.strip() for v in t.get("variants", []) if v.strip()],
                    gender=t.get("gender")
                    if t.get("gender") in ("male", "female") and t.get("type") == "person"
                    else None,
                    gender_from="name" if t.get("gender") in ("male", "female") else None,
                )
                for t in json.loads(raw)["terms"]
                if t.get("source", "").strip() and t.get("target", "").strip()
            ]
        except (TranslatorUnavailable, ModelNotAvailable):
            raise
        except Exception as e:
            log(f"  glossary chunk failed ({type(e).__name__}); continuing without it")
            return []

    found = Glossary(known.target_lang)
    with ThreadPoolExecutor(max(1, workers)) as ex:
        for terms in ex.map(run, chunks):  # map keeps chunk order: earlier spellings win
            for t in terms:
                # Drop "names" that never actually occur (model invention).
                t.variants = [v for v in t.variants if v.lower() in full]
                if t.source.lower() in full or t.variants:
                    found.add(t)
    return found


def merge_into(base: Glossary, found: Glossary) -> Glossary:
    """Add newly found names to the folder glossary without touching existing (or user) entries."""
    for t in found.terms:
        base.add(t)
    return base
