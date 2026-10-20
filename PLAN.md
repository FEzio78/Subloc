# Subloc — Plan

Local, private, one-click subtitles for everyday people.
Drop a video → get subtitles in your language. No cloud, no accounts, no settings to learn.

Main focus: **non-English sources** (Japanese, Korean, Russian, Turkish, Chinese, …) and **English → Arabic** (plus other targets).

---

## 1. Principles

1. **One screen, one button.** Everything technical is hidden under "Advanced".
2. **Timestamps are sacred.** The translator (LLM) only ever sees numbered text, never times. Times are re-attached by ID.
3. **Use every source of truth.** Audio (Whisper) *and* on-screen text (OCR of burned-in subs). Pick the best automatically.
4. **Output that just works.** `Movie.ar.srt` saved next to `Movie.mp4` so VLC / MPV / Plex / TVs load it automatically.
5. **Never redo work.** Transcript is cached; changing target language only re-runs translation.
6. **Runs on normal PCs.** Quality presets map to model sizes based on detected GPU/VRAM; CPU fallback exists.

---

## 2. Pipeline

```
                ┌──────────────── Audio path ────────────────┐
Video ─ffmpeg─► │ 16 kHz mono → VAD (skip music/silence)     │
                │ → faster-whisper (word timestamps)         │
                └────────────────────────────────────────────┘
                ┌──────────── On-screen text path ───────────┐
       ─ffmpeg─►│ quick scan (≈30 frames) → subs present?    │
                │ → sample 3–5 fps → change detection        │
                │ → OCR only changed frames → cues w/ timing │
                │ → drop watermark / scene text              │
                └────────────────────────────────────────────┘
                                   │
                         Fusion (Smart mode)
                                   │
                Segmenter (readable lines, ≤42 chars, 1–7 s)
                                   │
                  Source subtitles  →  Video.ko.srt
                                   │
              LLM translation (batched, numbered, with context)
                                   │
                 Video.ar.srt  +  Video.ar.ass (positioned)
```

### 2.1 Audio path (ASR)
- `ffmpeg` → 16 kHz mono WAV.
- Silero VAD to cut out music/silence (main fix for Whisper hallucinations like "Thanks for watching!").
- `faster-whisper` `large-v3` (Best) / `large-v3-turbo` (Fast), `word_timestamps=True`, `condition_on_previous_text=False`.
- Language auto-detect, with manual override.
- Hallucination filter: repeated lines, known junk phrases, segments with very low avg log-prob.
- Optional language-specialized models later (e.g. Japanese/anime-tuned Whisper).

### 2.2 On-screen text path (burned-in subtitles) — OPTIONAL, later phase
> Most target videos have no burned-in subs, so the audio path is the product. This is an add-on.
> Research done so far (Korean test clip):
> - Outline-text mask (bright pixels next to dark ones, stable across 2 samples at 4 fps) scans 6.5 min in ~4 s and finds subtitle rows clearly; watermark must be removed by "bright in ~all frames", not by mask frequency.
> - Gemma 4 26B reads Korean subs + speaker names accurately. Must send `reasoning_effort: "none"` (thinking adds ~150 tokens/frame): ~2.8 s/frame.
> - Idea to test: stack ~8 cropped subtitle strips per image → one call per 8 subtitles.

- **Quick scan:** ~30 frames across the video → text detection → decide "has burned-in subs?" and where (usually bottom band).
- **Region classification:**
  - *Watermark*: same text, same position in >70% of frames → ignore (e.g. `We're 스푸닝19`).
  - *Scene text*: monitors, posters, phones — no outline, irregular, moves with camera → ignore.
  - *Dialogue*: bottom-center, consistent style, often `Speaker : text` → keep, extract speaker name.
  - *Captions / SFX / narration*: larger or mid-screen text, `( … )`, text on black screens → keep, tag as caption.
- **Timing:** sample at 3–5 fps; perceptual-hash the subtitle band; OCR only when it changes. Start = first frame text appears, end = first frame it's gone. Merge duplicates.
- **OCR engine:** local vision LLM via LM Studio (Gemma 4 / Qwen 3.8 with mmproj). Tested on the Korean clip: read `PD : 얘기를 들어 좀..` exactly, split speaker, tagged watermark, ignored on-screen monitor text — all in one call. Only *changed* frames are sent, so cost scales with number of subtitles, not video length.
- PaddleOCR kept as an optional fast path for very long videos / weak PCs (detection + reading without an LLM).

### 2.3 Fusion (Smart mode)
- OCR dialogue cue overlapping Whisper speech → **use OCR text** (author-written, correct names), timing from OCR, refined by Whisper word times.
- Whisper speech with no OCR cue → keep (uncaptioned speech).
- OCR captions/SFX/narration with no speech → keep as separate cues, styled differently.
- Modes exposed to user: **Auto** (default) · Audio · On-screen text · Both.

### 2.4 Segmentation
- Split long segments using word timestamps at punctuation/pauses.
- Rules: max 2 lines, ~42 chars/line, 1–7 s duration, reading speed ~17 chars/s, min gap 80 ms.

### 2.5 Translation
- Backend: **LM Studio** local server (`http://localhost:1234/v1`, OpenAI-compatible, JSON-schema output). Pluggable: any OpenAI-compatible endpoint (Ollama, llama.cpp, cloud key) works too.
- **Model choice is the user's.** The app lists chat models from LM Studio (`/api/v0/models`), loaded ones first, each with a suggestion label. **Default = whatever is currently loaded.** Reading on-screen text needs a vision (`vlm`) model; text-only models are greyed out for that step.
- Suggestion labels (for models commonly installed in LM Studio):
  - **Default:** `google/gemma-4-26b-a4b` (MoE, fast, strong Arabic) — tested ko→ar, good result.
  - **Best quality:** `google/gemma-4-31b`; `qwen/qwen3.8-27b` for ja/ko/zh sources (compare in Phase 0).
  - **Weak PC preset:** `google/gemma-4-e4b` / `e2b`.
  - **Fallback if a model refuses/softens mature dialogue:** uncensored variants (supergemma4 / Qwen3.8 uncensored).
  - Not used: Bonsai Q1_0 (1-bit, too lossy), Writing Partner Mistral 7B (old, English-focused).
- Flow: **ASR/OCR → numbered lines → LLM translates → app re-attaches timestamps by ID** (LLM never sees times).
- Input to LLM: JSON list of `{id, speaker?, max_chars, text}` in batches of ~20–30 lines.
- **Sentence groups:** Japanese, Korean and Turkish put the verb at the end, so one sentence is often split across 2–3 subtitles. Lines that belong to one sentence are sent together and the LLM returns one text per ID, free to move words between them so each line reads naturally. Never translate half-sentences in isolation.
- **Reading budget:** `max_chars` per line from its duration (~17 chars/s) so Arabic lines fit on screen in time.
- Reused from [ProseArc](https://github.com/FEzio78/ProseArc) (`src/prompt.js`, `src/engine.js`):
  - Context = previous lines as *source ⇢ translation pairs* + 2 upcoming source lines, marked "context only".
  - Arabic agreement reminder next to the task: number/gender of "you" from context (+ speaker names from OCR).
  - Glossary: only terms present in the batch; series glossary overrides global.
  - Timeout + retry, save progress so a stopped job resumes; identical lines translated once.
  - Re-translate a single line from the review screen.
- Fallback: if a batch comes back with missing/merged IDs after retry, translate those lines one by one (ProseArc style).
- Prompt context: video title, source/target language, glossary (names), "keep it short, subtitle-style".
- **Arabic = Modern Standard Arabic (فصحى)** — the only target for now. Common titles translated, not transliterated (e.g. `PD` → `المخرج`).
- Output forced to JSON schema `{id, text}`; validate every ID present; retry batch on mismatch.
- Per-series glossary file so names stay consistent across episodes.

### 2.6 Output
- `Video.<src>.srt` — original-language subtitles (useful itself + cache).
- `Video.<tgt>.srt` — translated, universal.
- `Video.<tgt>.ass` — positioned/styled (above burned-in subs, captions styled separately).
- `Video.subloc.json` — project cache (segments, words, OCR cues, translations).
- RTL fix for Arabic/Hebrew/Persian: wrap lines with U+202B/U+202C or add U+200F so punctuation lands correctly.
- Optional: burn subtitles into a new video (ffmpeg), with "cover original subs" box.

---

## 3. Data model

```python
Cue:
  id: int
  start: float          # seconds
  end: float
  source: "asr" | "ocr" | "merged"
  kind: "dialogue" | "caption" | "sfx" | "narration"
  speaker: str | None
  text: str             # source language
  translation: str | None
  words: list[Word]     # from ASR, optional
  confidence: float
```

---

## 4. Tech stack

| Part | Choice |
|---|---|
| Language / env | Python 3.12 via `uv` venv (best wheel support for CUDA libs) |
| Media | ffmpeg / ffprobe |
| ASR | faster-whisper (CTranslate2, CUDA) + Silero VAD |
| OCR | Vision LLM via LM Studio (Gemma 4 / Qwen 3.8); PaddleOCR optional fast path |
| Translation | LM Studio — Gemma 4 / Qwen 3.8 (OpenAI-compatible API) |
| GUI | PySide6 (Qt) |
| Player | libmpv (python-mpv) embedded |
| Packaging | PyInstaller / installer, models downloaded on first run |

---

## 5. Project layout

```
Subloc/
  PLAN.md  README.md  pyproject.toml  env.ps1  Subloc.bat
  subloc/
    models.py        # Cue, Word, Project (saved as Video.subloc.json)
    media.py         # ffprobe tracks, audio decode (sync-safe on damaged files), fingerprint, built-in subs
    asr.py           # faster-whisper, language vote, mixed-language mode, junk filter
    segment.py       # readable cues, sentence groups (capped), SEGMENT_VERSION
    subparse.py      # ASS/SRT parsing of built-in subtitles
    langs.py         # language names, per-target style rules, Arabic letter cleanup
    glossary.py      # name pass + folder glossary (subloc.glossary.json)
    translate.py     # batched translation: enforced format, src anchoring, retries, parallel
    llm.py           # LM Studio / OpenAI-compatible client with readable errors
    errors.py        # user-facing error types
    subtitles.py     # SRT writer: RTL marks, dialogue pairing, song italics
    pipeline.py      # one video: caching/resume, stages, warnings
    batch.py         # many videos: listen all, then translate all
    cli.py  gui.py   # command line, current (pre-redesign) window
  tests/             # pytest, no GPU/LM Studio needed
  tools/compare_subs.py   # accuracy vs reference subtitles
  design/mockup.html      # UI direction for part B
  vids/              # private test media — git-ignored, never uploaded
```

---

## 6. Phases

### Status (2026-10-20)
- ✅ Phase 0 CLI works end to end on the Korean clip (6.5 min → ko.srt + ar.srt in ~80 s).
- ✅ Phase 1 MVP GUI (`Subloc.bat`): drop zone, language/speech/translator pickers (default = loaded LM Studio model), live lines while listening/translating, Stop + resume, Play / Show files.
- Findings: Whisper sequential mode > batched mode (accuracy, per-utterance segments); turbo is worse on Korean (garbage lines) → "Best" is default; 4 parallel LLM requests ≈ 2.3× throughput; very short lines are paired as "- … / - …" dialogue cues at output.
- ✅ Audio track picker (default = original-language track; container language tags are often wrong).
- ✅ Built-in subtitles: "Translate built-in subtitles" (ASS/SRT/mov_text/WebVTT) — keeps professional timing, joins multi-part signs, songs → italics. Image subs (PGS/VobSub) not supported yet.
- ✅ Mixed-language mode: VAD chunks → per-chunk language detection + transcription; each line carries its language. Tested: Attack on Titan (ja/en/es/ru), STALKER (8 languages incl. uk vs ru).
- ✅ Language auto-detect votes across 8 speech windows (single-window detection called Initial D's Eurobeat "nn").
### Part A — engine quality (2026-10-20)
Found on real content and fixed (each with a regression test):

| Problem | Seen on | Fix |
|---|---|---|
| VRAM full during translation (Whisper still loaded) → ~10× slower | 87-min film | unload Whisper before translating; default 2 parallel requests (1–4) |
| Model answered only the first line of a batch | Tagalog | response format enforces exact item count + allowed ids |
| Sentence groups ran 15 lines when Whisper omits punctuation | Turkish | capital letter starts a sentence; groups capped at 4 cues |
| Translations slid onto the next line (~15 in a row) | Initial D | each item copies its source start (`src`); mismatch → re-ask that line (not for 1-line requests) |
| Subtitles minutes early on a damaged file (12 of 25 min decodable) | Initial D (corrupt) | decode with silence-fill (aresample async) + "damaged" warning |
| 1–2 character fragment subtitles at dramatic pauses | Japanese anime | splitter keeps parts ≥4 CJK / ≥10 other chars |
| Same-name replaced video reused old transcript | Initial D (fixed file) | content fingerprint in saved work |
| Names spelled inconsistently | Russian film, Korean | name pass + folder glossary |
| "Eight-Six" transliterated (إيت-سيكس) | Initial D | numbers/model codes as digits, as spoken → الـ 86 |
| Persian letters in Arabic names (سيريوژا) | Russian series | prompt rule + deterministic cleanup |

Measured: 87-min film end to end in 8 min 56 s (listen 2:47, translate 6:00). Initial D (Japanese) vs official English subtitles: 98% of official dialogue lines covered, translations match in meaning.

- Test set (vids/, never uploaded): ko variety, ja anime ×2, en speech, ru film 87 min, ru series, tr series, tl series, 2 mixed-language clips.

### Phase 0 — Prototype (CLI)
- Env + deps, CLI: `subloc <video> --to ar [--mode auto|audio|ocr|both]`.
- Test set: Korean variety clip (burned-in subs) + Japanese anime + Russian/Turkish + English movie clip.
- Compare: large-v3 vs turbo; 2–3 LLMs for → Arabic.
- **Done when:** Korean test clip produces `.ko.srt` and `.ar.srt` you rate as watchable; 2-hour movie processes in < 15 min on the 4090.

### Phase 1 — MVP GUI
- Drop zone, From/To/Quality, Start, live progress with lines appearing, Play / Open folder.
- First-run model download with progress; GPU detection → presets.

### Phase 2 — Watch Now
- Embedded mpv player; playback starts after ~30 s buffer while subtitles keep generating ahead.

### Phase 3 — Extras
- Subtitle editor (fix a line → optionally re-translate neighbors).
- Batch queue (whole season folder), per-series glossary.
- Burn-in export with "cover original" option.
- **Caption styles (CapCut/Submagic-style):** style presets → generated `.ass` (fonts, outline, colors, position, `\k`/`\t` word-highlight + pop animations) → live preview in mpv (libass, no re-encode) → export with ffmpeg + NVENC. Word highlight uses Whisper word times for the source language; for translations, word times are estimated by character length (or line-level highlight). Color emoji needs an image overlay (libass can't draw color emoji).
- Live captions for system audio (WASAPI loopback) as an overlay.

---

## 7. Production: self-contained app for non-technical users

Goal: one installer → drop a video → subtitles. The user never sees Python, CUDA or LM Studio.

| Part | Shipped how |
|---|---|
| Python + libraries | Frozen app (PyInstaller or Nuitka), per-user install, no admin |
| ffmpeg | Bundled **LGPL** build (current dev machine uses a GPL "full" build — not for redistribution) |
| Whisper | Downloaded on first run, size chosen by hardware |
| Translator | Bundled `llama-server` (llama.cpp, OpenAI-compatible like LM Studio) started by the app; GGUF model downloaded on first run. LM Studio / Ollama / cloud key = "Advanced" |
| CUDA libs (~1.2 GB) | Downloaded only when an NVIDIA GPU is present; Vulkan build of llama.cpp for AMD/Intel |

First-run wizard: detect GPU/VRAM/RAM/disk → recommend a preset → show download size → one button (pause/resume).

| Preset | Hardware | Speech | Translator | ~Download |
|---|---|---|---|---|
| Best | NVIDIA ≥16 GB | large-v3 | Gemma 4 26B-A4B | ~18 GB |
| Balanced | NVIDIA 8–12 GB | large-v3 (int8) | Gemma 4 E4B | ~7 GB |
| Light | AMD/Intel/CPU | small/medium (CPU) | Gemma 4 E2B (Vulkan/CPU) or cloud key (opt-in, privacy notice) | ~3–4 GB |

Trust: code-signing certificate (avoids SmartScreen warning), clear privacy statement ("nothing leaves your PC" unless a cloud key is set), crash logs stay local unless the user sends them.

### Subtitle style (part B)
- Default stays: white text, black outline (works everywhere, written as `.srt`).
- Presets: Classic (default) · Boxed (semi-transparent dark box) · Yellow · Large.
- Custom: font (Arabic-capable fonts listed first), size, text colour, outline, shadow, background box
  (colour + opacity), position (bottom/top), margin, bold.
- Live preview on a real frame of the video, rendered by libass (same engine as VLC/MPV) via ffmpeg, so the
  preview is what players show; scrub to check bright/dark scenes. Nothing changes until "Apply".
- Output: styled `Video.ar.ass` next to the always-written `Video.ar.srt`; burn-in export uses the same style.
- Style saved as the default for next time (per user), resettable to Classic.

Order of work: A engine quality (quality pass, glossary, batch, robustness) → B professional GUI (design first, then review/queue/player/settings/Arabic UI) → C production (code quality, first-run wizard, bundled translator, installer).

## 8. Risks

| Risk | Mitigation |
|---|---|
| Whisper hallucination on music/silence | VAD, junk filter, no prev-text conditioning |
| OCR picks up scene text / watermark | persistence + position + style classification |
| Stylized fonts (variety shows, anime signs) | VLM fallback on low-confidence frames |
| LLM drops/merges lines | JSON schema, ID validation, retry |
| Names inconsistent | glossary + speaker names from OCR |
| Arabic punctuation broken in players | RTL embedding marks |
| Weak user hardware | presets by VRAM, turbo model, smaller LLM, CPU fallback |
