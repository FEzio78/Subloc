# Subloc — notes for development sessions

Local, private subtitle app: Whisper transcribes, a local LLM translates (Arabic first, any language), with
styles, in-app player, burn-in, English/Arabic UI and a first-run setup. Windows, Python 3.12, PySide6.
Public repo: https://github.com/FEzio78/Subloc (GPL-3.0-or-later). Design + history of decisions: `PLAN.md`.

## Commands

```powershell
. .\env.ps1 -Setup                          # env inside the folder (.tools/, .venv/)
.venv\Scripts\python tools\fetch_vendor.py  # llama.cpp + libmpv into vendor/ (git-ignored)
.\Subloc.bat                                # app (first launch opens Setup)
.venv\Scripts\python -m subloc translate VIDEO_OR_FOLDER --to ar   # CLI: docs/cli.md (every command takes --json)
.venv\Scripts\python -m subloc mcp                                # MCP server for agents: docs/agents.md
.venv\Scripts\python -m pytest ; .venv\Scripts\python -m ruff check . ; .venv\Scripts\python -m ruff format . ; .venv\Scripts\python -m mypy subloc
.venv\Scripts\python tools\make_screenshots.py   # README images from a synthetic demo
.venv\Scripts\python toolsuild.py             # dist\Subloc (Subloc.exe + subloc-cli.exe) + installer (Inno Setup 6)
```

All four checks must pass before committing.

## Layout

- Engine: `media` (ffprobe, sync-safe audio decode, fingerprint) · `asr` (Whisper, language vote, mixed mode) ·
  `segment` · `subparse` · `glossary` (name list per folder) · `translate` (batches, enforced JSON with exact
  count + id enum, `src` anchoring, retries, parallel) · `llm` (OpenAI-compatible client) · `engine`
  (built-in llama-server) · `pipeline` (one video, caching) · `batch` · `style`/`burn`/`subtitles` (outputs) ·
  `catalog`/`hardware`/`download`/`config` (setup) · `recent` (Home list) · `library` (folder index, scans) ·
  `proc` (every process starts here, hidden: no console windows; test enforces) · `power` ·
  `service` (no-window layer: app settings, jobs, JSON reports; used by `cli` and `mcp_server`) · `busy`
  (one GPU job at a time across window, CLI and agents: OS file lock) · `cli` · `mcp_server` (MCP over stdio,
  protocol hand-written, no extra packages).
- UI (`subloc/ui`): `app` (main window: wiring, job, player, export) + its parts `home_ctl` (recent list),
  `library_ctl` (scans, watching), `queue_ctl` (queue, busy lock, power, notifications) · `pages` (Home, Job,
  Queue, Settings + About) · `library_page` · `widgets` (incl. Banner, Toast) · `icons` (Lucide SVGs in
  `assets/icons`, recoloured) · `shortcuts` (one list: keys + F1 window) · `intro` · `lines` · `player` (libmpv) ·
  `style_dialog` · `setup` (wizard) · `i18n` (Arabic table) · `theme`.
- UI rules: no emoji as icons (use `icons.icon(name, colour)`); messages that need no answer are toasts
  (`self.toast(...)`), questions and real errors stay dialogs.
- App data while developing (git-ignored): `config.json`, `recent.json`, `library.json`, `queue.json`, `busy.lock`,
  `thumbs/`, `logs/`.

## Rules (hard-won)

- Never commit or upload media, frames or subtitles of real videos; `vids/` is private test media.
- The LLM never sees timestamps; lines are matched back by id and checked.
- UI text: `tr()` for dynamic/drawn text, static widgets are translated by `translate_tree`; add Arabic to `i18n.py`.
- Never name attributes after Qt methods (`style`, `size`, `screen`, `thread`, `done`…) — test enforces.
- Write direction marks as escapes (`"\u200f"`, `"\u2066"`…), never raw — test enforces. The Edit/Write
  tools turn escapes into raw characters: after writing one, check with grep and fix with a script (`chr(92)`).
- Arabic output: MSA, standard Arabic letters only, numbers/model codes as spoken digits (Eight-Six → 86).
- Defaults the user chose: 2 parallel translation requests (1–4 selectable); the user picks models.

## Status (2026-10-22)

**v0.1.0 released** (https://github.com/FEzio78/Subloc/releases/tag/v0.1.0, tag on `5aebb79`): installer
`Subloc-0.1.0-setup.exe`, 154 MB, notes in Arabic and English.

Done: engine quality pass on 11 real videos / 9 languages (0 missing lines), built-in translator, Setup wizard,
UI in English + Arabic, styles with libass preview, player, burn-in. Home = New project + Recent projects;
Library tab (folders scanned once, Refresh by hand, optional watching); queue kept between sessions, Stop,
keep-awake, notification, optional sleep/shut down after it (60 s countdown, never remembered); no console
windows; logo (Plex Serif S) + opening animation (`ui/intro`, can be turned off); Lucide icons, toasts,
keyboard shortcuts (F1), About; CLI with sub-commands + `--json`, MCP server, shared busy lock. Subtitles in
any of the 17 spoken languages; line width and wrapping per script (`langs.LINE_WIDTH`: ja 13, zh/ko 16, else
42; zh/ja break between characters); same language in and out = the transcript is the result.

Installer (`tools/build.py`, `installer/`): PyInstaller onedir (~0.7 GB: Subloc.exe + subloc-cli.exe) +
Inno Setup, per-user, English + Arabic, Explorer "Make subtitles with Subloc". Bundles llama.cpp's Vulkan build
(llama-server only), libmpv, FFmpeg 9.0.2 (GPL essentials). Setup downloads on NVIDIA PCs only: CUDA libs
(`cuda.py`, pins = uv.lock, test enforces) unless NVIDIA's own CUDA 12 + cuDNN 9 are installed
(`cuda.system_dirs`), and llama.cpp's CUDA build when the built-in translator is chosen. Whisper already in
the standard HF cache is used (`asr.local_model`). The installed app keeps only Windows/NVIDIA folders on its
PATH from its first runtime hook (`installer/rth_system_path.py`): other programs' DLLs on PATH crashed it
(R6034).

## Releasing

1. Bump `version` in `pyproject.toml`; all four checks pass; commit and push `main` (only `main`, never
   `private-history`); GitHub Actions must pass.
2. `.venv\Scripts\python tools\build.py` → `dist\Subloc-<version>-setup.exe`; install it silently into a temp
   folder, open the app, uninstall (`/VERYSILENT /CURRENTUSER /DIR=… /TASKS=""`).
3. Notes in Arabic first, then English, with the installer's SHA-256; show them to the user before publishing.
4. Before publishing, check the commits: noreply author, no personal paths/e-mail, no media, logs or data files.
5. `gh release create v<version> dist\Subloc-<version>-setup.exe --target <full commit id> --title
   "Subloc <version>" --notes-file …` (a short commit id is rejected); compare GitHub's asset digest.

## Next

1. Code signing (SmartScreen warns on the unsigned installer); a test on a clean PC (no Python, no Subloc).
2. Later: one running copy at a time (a second launch hands its files to the first), reading burned-in subtitles
   (research notes in PLAN.md §2.2), live captions for system audio, CapCut-style animated captions, more UI
   languages.
