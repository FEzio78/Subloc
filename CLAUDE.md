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
.venv\Scripts\python tools\build.py             # dist\Subloc (Subloc.exe + subloc-cli.exe) + installer (Inno Setup 6)
```

All four checks must pass before committing.

## Branches

- `main` = the working, released app. Don't develop on it.
- `dev` = testing phase: new work is committed here, tested in the real app, then merged into `main` when the
  user says so (`git switch main; git merge --ff-only dev`). Pushed to GitHub (`origin/dev`, 2026-10-24, the
  user asked); CI runs only on `main` and pull requests. Before pushing: noreply author, no personal paths, and
  nothing from `vids/` (no media, subtitles, dialogue or character names) in files or commit messages.
- `dev-backup` (local only, never push): `dev` before its history was rewritten to drop character names.
- `private-history` is never pushed.

## Layout

- Engine: `media` (ffprobe, sync-safe audio decode, fingerprint) · `asr` (Whisper, language vote, mixed mode) ·
  `segment` · `subparse` · `glossary` (name list per folder, people's genders) · `voices` (speaker + man/woman
  voice per line, fingerprints, scenes) · `addressee` (optional scene-first listener pass) · `translate` (batches, enforced JSON with exact
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
- Arabic output: MSA, standard Arabic letters only, numbers/model codes as spoken digits (Eight-Six → 86);
  feminine "you" with a visible ي, not a kasra (أنتي، لكي، يمكنكي، كنتي: the user's choice, `langs.visible_feminine`).
- Defaults the user chose: 2 parallel translation requests (1–4 selectable); the user picks models.

## Status (2026-10-24)

**v0.2.0 built on `dev`, not released** (`dist\Subloc-0.2.0-setup.exe`, 159 MB): installed silently into a temp
folder, the installed CLI ran a clip end to end (Whisper GPU, quiet-speech pass, nemo-speech speakers, names,
Arabic), the window opened, uninstalled clean. Release notes not written yet; `main` still = v0.1.0.

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

1. **Speakers and who is spoken to** (on `dev`): design + results in PLAN.md 2.7. Built: (a) `voices.py`
   (Nemotron via bundled nemo-speech Vulkan + one ONNX gender classifier; per-line speaker/gender, shown in
   Lines) and (b) translation with scenes, speakers, voices and a `to` field (synthetic test en→ar: Gemma 26B
   12–13 → 21–22 of 22 lines right, E4B 10 → 19–21; Turkish series and an English film with official Arabic:
   fewer wrong feminine forms, the film's listener choice is the weak part). Long audio is diarized in
   10-min windows, ids joined by voice fingerprints (CAM++); names learn their gender; Lines editor "Spoken
   to" fix; scene-first listener pass is an option, not the default (worse on the film). Next: the user tests
   it all in the app; then merge `dev` into `main` when they say so. Also on `dev`: quiet/whispered speech the
   VAD skipped is listened to again (PLAN.md 2.8; film: 621 -> 680 of 713 official lines covered). Ideas: shot changes as scene cuts, the
   listener choice in crowded scenes (the film's weak part).
2. Code signing (SmartScreen warns on the unsigned installer); a test on a clean PC (no Python, no Subloc).
3. Later: one running copy at a time (a second launch hands its files to the first), reading burned-in subtitles
   (research notes in PLAN.md §2.2), live captions for system audio, CapCut-style animated captions, more UI
   languages.
