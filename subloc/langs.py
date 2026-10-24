"""Language names and per-target style rules, shared by translation and the name glossary."""

import re

LANGS = {
    "ar": "Arabic",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "ru": "Russian",
    "tr": "Turkish",
    "zh": "Chinese",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "hi": "Hindi",
    "id": "Indonesian",
    "th": "Thai",
    "vi": "Vietnamese",
    "fa": "Persian",
    "ur": "Urdu",
    "uk": "Ukrainian",
    "pl": "Polish",
    "tl": "Tagalog (Filipino)",
    "ms": "Malay",
    "cs": "Czech",
    "nl": "Dutch",
    "sv": "Swedish",
    "hu": "Hungarian",
    "ro": "Romanian",
    "el": "Greek",
    "he": "Hebrew",
    "bn": "Bengali",
    "mixed": "several languages",
}

LINE = 42  # characters per subtitle line (Latin, Cyrillic, Arabic, Thai…)
# Wide scripts fit fewer characters on a line (as in professional subtitle style guides).
LINE_WIDTH = {"ja": 13, "zh": 16, "ko": 16}
# Chinese and Japanese don't put spaces between words: lines may break between characters.
NO_SPACES = {"ja", "zh"}


def line_width(code: str | None) -> int:
    return LINE_WIDTH.get(code or "", LINE)


TARGET_BRIEF = {
    "ar": (
        "Write Modern Standard Arabic (فصحى), natural and easy to read, as used in professional "
        "Arabic subtitles. Translate titles and roles instead of transliterating them "
        "(e.g. PD → المخرج, CEO → المدير التنفيذي); transliterate personal names. "
        "Use only standard Arabic letters — never Persian/Urdu letters such as پ چ ژ گ ڤ: "
        "write zh/j/ж as ج, p as ب, v as ف, ch as تش, hard g as غ (e.g. Серёжа → سيريوجا, Pavel → بافل). "
        "The listener's gender decides the form, not the speaker's: to a man أنت، لك، كنت، تريد، انظر; to a "
        "woman أنتي، لكي، كنتي، يمكنكي، تريدين، انظري (feminine written with a visible ي, never a kasra alone); to "
        "several أنتم، لكم، تريدون، انظروا."
    ),
}

# Persian/Urdu letters that models sometimes use when transliterating foreign names into Arabic
# (Серёжа came out with ژ). Standard Arabic equivalents, applied to every Arabic output.
_ARABIC_LETTERS = str.maketrans({"ژ": "ج", "پ": "ب", "ڤ": "ف", "گ": "غ", "ک": "ك", "ی": "ي"})


NUMBERS_RULE = (
    "Write numbers with digits (0-9). Keep model names and codes of cars, devices and products in "
    "digits/Latin letters exactly as the speakers say them, even when the source spells them out in "
    'words, and don\'t expand them: "Eight-Six" → 86 (not AE86), "S thirteen" → S13, iPhone 15 → iPhone 15.'
)

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip


def fixed_name(source: str) -> str | None:
    """Names whose rendering must not be left to the model: codes with digits keep their exact form
    (S13, AE86 — the model wrote إس 13), and names spelled as digit words become digits ("Eight-Six" →
    86; it wrote إيت-سيكس). None = no rule, use the model's spelling."""
    s = source.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]*", s) and re.search(r"\d", s):  # one code, not a phrase
        return s
    words = re.split(r"[\s\-]+", s.lower())
    if len(words) >= 2 and all(w in _DIGIT_WORDS for w in words):
        return "".join(_DIGIT_WORDS[w] for w in words)
    return None


# Feminine "you" written with a visible ي (the user's choice: on a moving subtitle a kasra under a letter is easy
# to miss): لكِ → لكي, أنتِ → أنتي, يمكنكِ → يمكنكي, كنتِ → كنتي. Only where the model wrote that kasra at the end
# of a word (it marks the feminine there); words with the article (case endings such as البيتِ) stay as they are.
_FEM_YOU = re.compile(r"(?<![\u0621-\u0652])([\u0621-\u0652]*?[كت])\u0650(?![\u0621-\u0652])")
_ARTICLE = ("ال", "وال", "بال", "فال", "كال", "لل")


def visible_feminine(text: str) -> str:
    def fix(m: re.Match) -> str:
        word = m.group(1)
        return m.group(0) if word.startswith(_ARTICLE) else word + "ي"

    return _FEM_YOU.sub(fix, text)


def clean_output(text: str, tgt_code: str) -> str:
    if tgt_code == "ar":
        return visible_feminine(text.replace("چ", "تش").translate(_ARABIC_LETTERS))
    return text


def lang_name(code: str | None) -> str:
    """Unknown source (e.g. a mislabeled subtitle track) → the model works it out from the text."""
    return LANGS.get(code or "", code or "the original language")
