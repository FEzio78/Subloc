<p align="center">
  <img src="docs/screenshots/home.png" width="860" alt="Subloc — drop a video">
</p>

# Subloc

**Subtitles for any video, made on your own PC.** Drop in a movie, a series episode or an anime, and get
subtitles in your language — translated by AI running locally. Nothing is uploaded, no account, no
subscription.

Built first for **Arabic** viewers of Korean, Japanese, Chinese, Russian, Turkish, Filipino and English
content, and designed so anyone can use it.

> **Status:** beta, Windows. Runs from source today; a one-click installer is next.

## What it does

- **Listens and writes** — Whisper turns the speech into timed text, on your graphics card.
- **Translates with context** — a local language model translates whole scenes, not single lines, keeps
  names spelled the same in every episode, and never touches the timing.
- **Uses existing subtitles** — if the file already has subtitles (say, English), it translates those
  instead: faster, with professional timing.
- **Handles real-world files** — several audio tracks, mixed-language videos, damaged downloads (timing
  stays right, you get a warning), whole season folders.
- **Lets you fix things** — click any line to edit it or translate it again; rename a character once and
  every line follows.
- **Looks the way you want** — subtitle styles with an exact preview; play inside the app, or burn the
  subtitles into a new video for phones and TVs.
- **Speaks your language** — English and Arabic interface (full right-to-left layout).

| Working | Reviewing |
|---|---|
| ![Working](docs/screenshots/working.png) | ![Reviewing](docs/screenshots/review.png) |

| Subtitle style | Setup | واجهة عربية |
|---|---|---|
| ![Style](docs/screenshots/style.png) | ![Setup](docs/screenshots/setup.png) | ![Arabic](docs/screenshots/working-ar.png) |

## How it works

```
video ─► ffmpeg ─► Whisper (speech → timed lines) ─┐
     └─► built-in subtitles (if any) ──────────────┤
                                                   ▼
          name list (one spelling per name, per series folder)
                                                   ▼
          local LLM translates numbered lines in batches, with context
          (timestamps never leave the app; each answer is checked line by line)
                                                   ▼
          Video.ar.srt  +  styled Video.ar.ass  +  optional burned-in MP4
```

The translator is either **built in** (Subloc runs [llama.cpp](https://github.com/ggml-org/llama.cpp)
with a model chosen for your PC) or **your own server** — LM Studio, Ollama or any OpenAI-compatible
address.

### Recommended setups

| Setup | For | Speech | Translator | Download |
|---|---|---|---|---|
| Best | NVIDIA, 20 GB+ | Whisper large-v3 | Gemma 4 26B | ~20 GB |
| Balanced | NVIDIA, 6–12 GB | Whisper large-v3 | Gemma 4 E4B | ~8 GB |
| Light | any PC | Whisper small | Gemma 4 E2B | ~4 GB |

On a strong GPU an 87-minute film takes about 9 minutes. The Light setup runs on the processor: it works,
but a 1-hour episode can take 1–3 hours on a laptop.

## Run from source (Windows)

Needs [ffmpeg](https://ffmpeg.org) on `PATH`, [uv](https://docs.astral.sh/uv/) and
[7-Zip](https://www.7-zip.org) (to unpack the player library).

```powershell
git clone https://github.com/FEzio78/Subloc
cd Subloc
. .\env.ps1 -Setup                         # Python 3.12 + packages, all inside this folder
.venv\Scripts\python tools\fetch_vendor.py # llama.cpp + libmpv (pinned, checksum-verified)
.\Subloc.bat                               # first launch opens Setup
```

Command line:

```powershell
.venv\Scripts\python -m subloc.cli "movie.mkv" --to ar
.venv\Scripts\python -m subloc.cli "D:\Shows\Season 1"     # a whole folder
.venv\Scripts\python -m subloc.cli "movie.mkv" --subs 1    # translate built-in subtitle track 1
.venv\Scripts\python -m subloc.cli "clip.mp4" --from mixed # language changes during the video
.venv\Scripts\python -m subloc.cli --help
```

## Output

Saved next to the video, so VLC, MPV, Plex and most TVs pick the subtitles up automatically:

| File | What |
|---|---|
| `Video.ar.srt` | translated subtitles |
| `Video.ar.ass` | the same, in your chosen style (when a style is set) |
| `Video.<lang>.srt` | the original-language transcript |
| `Video.subloc.json` | saved progress — stop anytime and continue later |
| `subloc.glossary.json` | names in this folder and how they are written — edit to fix a name everywhere |

## Privacy

Everything runs on your computer. Videos, audio and subtitles are never sent anywhere. The only network
traffic is downloading models during Setup (from Hugging Face) — or talking to the translator server
*you* configure.

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Design notes and the
roadmap are in [PLAN.md](PLAN.md).

## License

[GPL-3.0-or-later](LICENSE), with an additional permission for NVIDIA's CUDA libraries. Third-party
components and their licences: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Fonts: IBM Plex (OFL-1.1).
