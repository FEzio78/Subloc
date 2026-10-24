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

### 2.7 Speakers and who is spoken to (research 2026-10-22; steps (a) and (b) built 2026-10-24 on `dev`)

**Problem.** English "do you want this?" is هل تريد هذا؟ to a man and هل تريدين هذا؟ to a woman, أتريدان/أتريدون/
أتريدن for two or a group. The speaker's own gender matters less (أنا متعب/متعبة) than the **addressee's**, which
the audio alone never gives. Idea (the user's): transcribe first, then translate with context + who speaks + who
is present (male/female) + same scene or not.

**Experiment** (scratch, not in repo; 64 s synthetic 5-voice scene with truth + two real Korean clips, 6.5 and
9.2 min, processed locally only):
- **NVIDIA Nemotron 3 Diarization** (OpenMDW-1.1, not gated, max 8 speakers) via **NeMo-Speech.cpp v0.2.0**
  (Apache-2.0, ggml, Windows CUDA/Vulkan/CPU builds, `Nemotron-3-Diarization.q8_0.gguf`):
  `nemo-speech diarize WAV --model GGUF --device cuda --format json --preset v3-streaming --onset 0.4 --offset 0.35`.
  Synthetic: 22/24 lines right, 0 missed (defaults 20/24; v3-offline 19; full attention 10). Real: 7 and 5
  speakers. Speed: GPU 3.6 s / 5.5 s per clip, CPU ~4x real time.
- **sherpa-onnx** (pyannote seg 3.0 + TitaNet or CAM++ + clustering): 16–18/24 synthetic, and badly over-splits
  real audio (24–99 "speakers", <45% agreement with Nemotron at any threshold). Rejected.
- pyannote models are gated (HF account), audeering gender model is non-commercial: both excluded.
- **Gender:** Common-Voice-Gender-Detection-ONNX (Apache; 0=female, normalized input), voice-gender-classifier-
  onnx-q8-v2 (MIT; 1=female, raw input), autocorrelation pitch (>165 Hz). 5/5 on synthetic; on real voices they
  disagree for ~half the speakers (all agree on low voices; at 220–260 Hz classifier B + pitch say female,
  classifier A leans male).
- **User's listening check (Korean clips):** gender is right; *who* speaks is unreliable when many talk at once.

**Design (proposal):**
1. **Per-line voice facts, not just clusters.** Each line gets `gender` (+ confidence, from that line's own
   audio, all methods must agree, else unknown) and `speaker` (Nemotron label, optional, may be wrong in crowds).
   Gender per line is the robust part; speaker identity is a bonus.
2. **Scenes.** Split by shot changes (ffmpeg `select='gt(scene,0.4)'`) + long silences + change in the set of
   speakers. Each scene has a roster: `S1 male, S2 female, S3 male?`.
3. **Translate per scene** with lines tagged `{id, speaker, gender, text}` and the roster, and ask the LLM for an
   extra JSON field `to`: a speaker id / `group` / `unknown`, before `text` (forces it to decide the addressee
   first; the existing enforced JSON + id checks stay). Cheap rules first: two people in a scene → the addressee
   is the other one; the next speaker after a question is usually the addressee.
4. **Clues already in the source:** Korean 오빠/형/언니/누나 encode speaker *and* addressee gender, honorifics give
   relationships; Spanish/French/Russian/Arabic sources mark gender in adjectives/verbs; names in the vocative
   ("Minji, …") + the next speaker → link name ↔ voice ↔ gender and store it in the folder glossary
   (Minji = female) so later episodes know.
5. **When unsure:** fall back to the masculine/generic form (the MSA convention), never guess feminine on weak
   evidence. Mark such lines in the Lines view; one click flips the addressee (male/female/group) and
   re-translates just that line.
6. **Optional "deep context" mode:** a first LLM pass reads the whole scene and writes who-is-who, names,
   relationships and the addressee per line; the second pass translates with it (about 2x LLM time).
7. Later, heavy: faces / active speaker on screen (lip movement) to tell who speaks and who listens.

**Order:** (a) bundle nemo-speech + the GGUF (Setup download, licence notices) and save per-line speaker/gender
in the project, shown in Lines, no translation change; (b) scene roster + `to` field in translation, measured on
real videos that have official Arabic subtitles (score only the second-person lines, locally); (c) name ↔ voice
in the glossary; (d) one-click fix; (e) deep-context mode.

**Step (a) built (2026-10-24, `subloc/voices.py`), with what the build changed:**
- **Vulkan build only** (19 MB zip, bundled in vendor/nemo-speech): on the 4090 it is nearly as fast as CUDA
  (6.5 min clip: 4.3 s vs 3.6 s; 9.2 min: 5.9 vs 4.8 s) and agrees with it on 87–95% of the speech; the CPU
  fallback is ~4x real time. No CUDA build to download.
- **One gender classifier, no pitch.** Per line on 5 real clips (Turkish, English podcast, Hindi, 2× Korean):
  pitch is useless on TV audio (a man both classifiers agree on measures 244 Hz); classifier A (Common Voice,
  95 MB) calls Korean women male on most lines; classifier B (ECAPA, 16 MB, MIT) per line matches every
  per-speaker label the user confirmed by ear, at ~70 ms a line (A: ~190 ms). So: B only.
- **Rule:** a line with P ≥ 0.9 (or ≤ 0.1) keeps its own answer (one diarized "speaker" sometimes holds two
  people: Conan clip, 22 of 45 lines confidently the other gender); else the speaker's duration-weighted P if
  ≥ 0.75 / ≤ 0.25 over ≥ 4 s; else a line leaning ≥ 0.75; else unknown.
- Runs after listening (also for built-in subtitles), saved in the project (`Cue.speaker` "S1"…, `Cue.gender`,
  `meta.voices` = key + speakers), redone only when the lines change; a failure is a warning only. Shown in
  Lines under the time; Settings → Speakers and voices (On/Off, Download 0.12 GB); Setup item; `subloc lines`
  and `read_subtitles` report it. Not sent to the translator yet (step b).
- First real runs: Turkish couple 4.2 min → 3 speakers, voice known on 93/94 lines, 5 s; Conan 6.5 min →
  6 speakers incl. one woman (37/42 of her lines female), 204/205 known, 7 s.

**Step (b) built (2026-10-24, `translate.py`):** only when a project has voices (else requests are unchanged).
- Scenes = a pause of ≥ 5 s (`voices.scenes`); each request lists the people per scene with their overall voice
  ("scene 3: S1 (man), S2 (woman)", 2/3 of a speaker's lines must agree); each line carries `scene`, `speaker`,
  `voice`; context lines are prefixed `[S1]`. The answer has `to` (a speaker / `several` / `unknown`) before
  `text`, saved as `Cue.to` and shown in Lines ("to S2"). Rule text: `translate.VOICES_RULE`.
- Answer format: one schema per position (`prefixItems`) so `to` can't be the line's own speaker. llama.cpp
  (LM Studio, built-in) enforces prefixItems only without `items` beside it (tested: with both, `items` wins).
- **Measured** (synthetic English scenes with known truth, 22 lines whose Arabic depends on the listener's or
  speaker's gender/number: couple, two sisters, coach + team, woman asking a man, two men), en → ar:
  Gemma 4 26B: before 12–13/22, after 21–22/22 (149/154 over 7 runs; general schema 215/220, same within
  noise); with messy voices (a third unknown, 2 lines on the wrong speaker) 21–22/22. Gemma 4 E4B: before
  10/22, after 19–21/22, messy 19–20/22 (17–19 with the general schema). Remaining misses: the right `to` but
  a masculine verb now and then; E4B names the one speaking player when a coach talks to his team.
- Real clip (Turkish couple → ar): the man's lines go to the woman (48/63), e.g. هل أنت مستعد؟ → هل أنتِ مستعدة؟.
- Real series (Turkish, 2 episodes of 20 min, tr -> ar, without -> with voices): lines to a woman with a
  feminine "you" 2 -> 10 (of 66) and 3 -> 9 (of 82); wrong feminine on lines to men 11 -> 9, 7 -> 6.
- **Scored on a film** (English, 96 min, official Arabic subtitles, 209 "you" lines matched by time; forms read
  without diacritics, so only visible feminine/plural counts): feminine where the official is feminine
  19 -> 20 of 34, plural 3 -> 4 of 10, feminine where the official isn't 42 -> 29. When our listener is a
  woman the form is right (12/15); the misses are lines whose listener came out a man or unknown (`to` is
  empty on 30% of the film's lines vs 16% in the series): many minor characters (a shop counter), and Whisper
  run-on lines that hold two speakers (182 lines start lowercase). Next for this: voice fingerprints so a
  character keeps one id through a film (ECAPA embeddings), then the deep-context pass (e).
- Found on the film and fixed: Nemotron follows at most 8 speakers at a time, so later characters were not
  heard at all (114 of 660 lines). Long audio now goes in 10-minute windows with 60 s overlap, linked by who
  talks together in the overlap: 11 such lines left, 61 s instead of 197 s for the step. Side effect: a
  character who returns later gets a new id (44 ids on the film).
- Arabic feminine "you" is written with a visible ي (أنتي، لكي، يمكنكي، كنتي; the user's choice: a kasra is easy
  to miss on screen), `langs.visible_feminine`.
- Not done: shot changes as scene cuts.

## 3. Data model

```python
Cue:
  id: int
  start: float          # seconds
  end: float
  source: "asr" | "ocr" | "merged"
  kind: "dialogue" | "caption" | "sfx" | "narration"
  speaker: str | None   # "S1"… (voices)
  gender: str | None    # voice: "male" | "female" | None (voices)
  to: str | None        # who the line is spoken to, as the translator decided: "S2" | "several" | None
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
    voices.py        # who speaks each line (Nemotron via nemo-speech) + man/woman voice (ONNX classifier)
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
