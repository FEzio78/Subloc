# Subloc — notes for development sessions

Local, private subtitle app: Whisper transcribes, a local LLM translates (Arabic first, any language), with
styles, in-app player, burn-in, English/Arabic UI and a first-run setup. Windows, Python 3.12, PySide6.
Public repo: https://github.com/FEzio78/Subloc (GPL-3.0-or-later). Design + history of decisions: `PLAN.md`.

## Commands

```powershell
. .\env.ps1 -Setup                          # env inside the folder (.tools/, .venv/)
.venv\Scripts\python tools\fetch_vendor.py  # llama.cpp + libmpv into vendor/ (git-ignored)
.\Subloc.bat                                # app (first launch opens Setup)
.venv\Scripts\python -m subloc.cli VIDEO --to ar
.venv\Scripts\python -m pytest ; .venv\Scripts\python -m ruff check . ; .venv\Scripts\python -m ruff format . ; .venv\Scripts\python -m mypy subloc
.venv\Scripts\python tools\make_screenshots.py   # README images from a synthetic demo
```

All four checks must pass before committing.

## Layout

- Engine: `media` (ffprobe, sync-safe audio decode, fingerprint) · `asr` (Whisper, language vote, mixed mode) ·
  `segment` · `subparse` · `glossary` (name list per folder) · `translate` (batches, enforced JSON with exact
  count + id enum, `src` anchoring, retries, parallel) · `llm` (OpenAI-compatible client) · `engine`
  (built-in llama-server) · `pipeline` (one video, caching) · `batch` · `style`/`burn`/`subtitles` (outputs) ·
  `catalog`/`hardware`/`download`/`config` (setup) · `cli`.
- UI (`subloc/ui`): `app` (main window/controller) · `pages` · `widgets` · `lines` · `player` (libmpv) ·
  `style_dialog` · `setup` (wizard) · `i18n` (Arabic table) · `theme`.
- `subloc/gui.py` is the old pre-redesign window — unused, safe to delete.

## Rules (hard-won)

- Never commit or upload media, frames or subtitles of real videos; `vids/` is private test media.
- The LLM never sees timestamps; lines are matched back by id and checked.
- UI text: `tr()` for dynamic/drawn text, static widgets are translated by `translate_tree`; add Arabic to `i18n.py`.
- Never name attributes after Qt methods (`style`, `size`, `screen`, `thread`, `done`…) — test enforces.
- Write direction marks as escapes (`"‏"`), never raw — test enforces. File-writing tools have turned
  `‏` into a raw character before: check after writing.
- Arabic output: MSA, standard Arabic letters only, numbers/model codes as spoken digits (Eight-Six → 86).
- Defaults the user chose: 2 parallel translation requests (1–4 selectable); the user picks models.

## Status (2026-10-20)

Done: engine quality pass on 11 real videos / 9 languages (0 missing lines), built-in translator,
Setup wizard, new UI + Arabic UI, styles with libass preview, player, burn-in, queue, open-source release.

## Next

1. **Windows installer** (PyInstaller or Nuitka): bundle Python app + `vendor/` (llama.cpp CUDA+Vulkan,
   libmpv) + an ffmpeg build; data in `%LOCALAPPDATA%\Subloc` (see `config.data_dir`); first launch → Setup.
   NVIDIA CUDA DLLs: bundle or fetch at setup (licence permission is in THIRD_PARTY_NOTICES.md).
2. Publish v0.1.0 on GitHub Releases. Check the GitHub Actions run (first one was never confirmed).
3. Later: reading burned-in subtitles (research notes in PLAN.md §2.2), live captions for system audio,
   CapCut-style animated captions, more UI languages.
