# Subloc from the command line

Everything the app does, without the window: same engine, same settings. The language, speech model,
translator, model and subtitle style you chose in the app are used unless you override them.

```powershell
subloc translate "D:\Anime\Night Market"          # every video in the folder and its subfolders → your language
subloc translate "Episode 3.mkv" --to en          # one video, into English
subloc transcribe "Lecture.mp4"                   # subtitles in the spoken language only
subloc folder "D:\Anime" --missing                # what still needs subtitles (quick: files only)
subloc info "Episode 3.mkv"                       # tracks inside, subtitle files, progress
subloc lines "Episode 3.mkv"                      # read the lines: id, time, [speaker m/f], original, translation
subloc edit "Episode 3.mkv" 42 "النص المصحح"        # correct line 42
subloc retranslate "Episode 3.mkv" 40 41 42       # translate lines again (after fixing a name, say)
subloc burn "Episode 3.mkv" --style Boxed         # a copy with the subtitles drawn in
subloc library add "D:\Anime"                     # the app's library: add, refresh, list --missing, remove
subloc queue add "D:\Anime\Night Market"          # hand videos to the app's queue (start it in the app)
subloc status                                     # settings, translator ready?, busy?
```

With the installed app the command is `subloc-cli.exe` in Subloc's folder (usually
`%LOCALAPPDATA%\Programs\Subloc`); from source it is `.venv\Scripts\python -m subloc`.

## translate / transcribe

| Option | |
|---|---|
| `--to ar` | subtitle language (two-letter code) |
| `--from ko` / `--from mixed` | spoken language, or `mixed` when it changes during the video (default: detected) |
| `--quality best\|balanced\|light` | speech recognition model |
| `--model ID` | translator model on your server (LM Studio…) |
| `--style Boxed` / `--style none` | the look of the `.ass` file (presets: `subloc styles`) |
| `--listen` | always listen, even when the file has subtitles inside |
| `--subs N` / `--audio-track N` | use subtitle track N / audio track N (1 = first) |
| `--retranslate` / `--retranscribe` | do it again even if it was done |
| `--no-names` | skip the name pass (faster, names less consistent) |
| `--no-wait` | exit with code 3 instead of waiting when Subloc is busy |

Videos already done are skipped. Ctrl+C stops; progress is kept, and the same command continues.
Subtitles are written next to each video: `Video.ar.srt` (and `Video.ar.ass` with a style).

## For scripts: `--json`

Every command takes `--json`: one JSON document on stdout, progress on stderr.

```powershell
subloc folder "D:\Anime" --missing --json | ConvertFrom-Json
```

Exit codes: `0` done · `1` failed (the message says why) · `2` wrong usage · `3` busy (`--no-wait`).

## One job at a time

Whisper and the translator need the graphics card. Subloc's window, the command line and agents share one
lock: if one is working, the others wait their turn (or exit with code 3 when given `--no-wait`).
`subloc status` says who is busy.

## AI agents

`subloc mcp` runs Subloc as an MCP server, so an agent (Claude Desktop, Claude Code and others) can make and
fix subtitles for you: see [agents.md](agents.md).
