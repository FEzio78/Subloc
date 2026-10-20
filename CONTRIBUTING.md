# Contributing to Subloc

Thanks for helping. Subloc aims to be something an ordinary person trusts with their evening's movie, so
changes are judged by one question: *does it make the subtitles better or the app easier, without
breaking anything?*

## Getting started

See "Run from source" in the README. Then:

```powershell
.venv\Scripts\python -m pytest          # tests (no GPU or translator needed)
.venv\Scripts\python -m ruff check .    # lint
.venv\Scripts\python -m ruff format .   # format
.venv\Scripts\python -m mypy subloc     # types
```

All four must pass before a pull request is merged.

## Ground rules

- **Never commit media.** No videos, audio, frames or subtitles from real films or shows — not in code,
  tests, issues or screenshots. Tests use synthetic data; screenshots come from
  `tools/make_screenshots.py` (generated video, invented dialogue).
- **Fix the cause, add a test.** Most bugs found so far came from real content (missing punctuation in
  Turkish, damaged files, the model shifting lines). Every fix ships with a test that reproduces it.
- **Every user-facing text goes through translation** — `tr()` for dynamic or drawn text; static widget
  text is translated automatically. Add the Arabic in `subloc/ui/i18n.py`.
- **Keep the timing sacred.** The language model never sees timestamps; translations are matched back by
  id and checked.
- **No invisible characters in code.** Write direction marks as escapes (`"‏"`); a test enforces it.
- **Don't shadow Qt methods** with attributes (`self.style`, `self.size`, `self.screen`…); a test enforces it.

## Reporting a translation problem

Please include the source language, the target language, the model, and a *short* quote of the
original line and the translation (a quote, not the media file).

## License

By contributing you agree your contribution is licensed under GPL-3.0-or-later, like the rest of Subloc.
