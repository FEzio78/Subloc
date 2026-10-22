# Subloc for AI agents (MCP)

`subloc mcp` runs Subloc as an [MCP](https://modelcontextprotocol.io) server over stdin/stdout. An agent can
then find videos that need subtitles, make them, read and correct lines, and burn them in, using the settings
of your Subloc app. Everything still runs on your PC: the agent only sends commands to Subloc; your videos
aren't uploaded anywhere by Subloc.

## Set it up

With the installed app, the command is `subloc-cli.exe` in Subloc's folder (usually
`%LOCALAPPDATA%\Programs\Subloc`). From source, it is `.venv\Scripts\python.exe -m subloc`.

**Claude Desktop** with the installed app: Settings → Developer → Edit Config (`claude_desktop_config.json`),
with your Windows user name in place of `YOU`:

```json
{
  "mcpServers": {
    "subloc": {
      "command": "C:\\Users\\YOU\\AppData\\Local\\Programs\\Subloc\\subloc-cli.exe",
      "args": ["mcp"]
    }
  }
}
```

**Claude Desktop** from source (replace `C:\path\to\Subloc` with the project folder):

```json
{
  "mcpServers": {
    "subloc": {
      "command": "C:\\path\\to\\Subloc\\.venv\\Scripts\\python.exe",
      "args": ["-m", "subloc", "mcp"]
    }
  }
}
```

**Claude Code**:

```powershell
claude mcp add subloc -- "$env:LOCALAPPDATA\Programs\Subloc\subloc-cli.exe" mcp        # installed app
claude mcp add subloc -- "C:\path\to\Subloc\.venv\Scripts\python.exe" -m subloc mcp  # from source
```

Any other MCP client: run `python -m subloc mcp` (stdio transport).

## Tools

| Tool | What it does | Changes anything? |
|---|---|---|
| `status` | settings, translator ready?, busy?, this session's jobs | no |
| `video_info` | tracks inside, subtitle files next to it, progress | no |
| `folder_status` | every video under a folder: needs subtitles or not (quick) | no |
| `library_list` | the app's library with each video's status | no |
| `make_subtitles` | start subtitles for videos/folders → `job_id` | writes subtitle files |
| `job_status` | progress, per-video status, files written | no |
| `cancel_job` | stop a job (progress is kept) | — |
| `read_subtitles` | lines: id, start/end, original, translation (paged) | no |
| `edit_line` | replace one translated line | rewrites the subtitle files |
| `retranslate_lines` | translate some lines again → `job_id` | rewrites the subtitle files |
| `burn_subtitles` | a copy of the video with subtitles drawn in → `job_id` | writes a new video |
| `library_add_folder` / `library_refresh` | add or re-read library folders → `job_id` | the app's library |

Nothing is ever deleted. Original videos are never changed.

## How agents should work with it

- Long work returns a `job_id` at once; check `job_status` every 30–60 seconds. A 24-minute episode takes
  about 3–6 minutes on a good graphics card.
- One job runs at a time on the PC, also shared with the Subloc window and the command line. A job may show
  `waiting` until the other work is done.
- Videos already done are skipped unless `retranslate` is set; stopped work continues where it left off.
- To fix a recurring name: `read_subtitles`, then `edit_line` for one line or `retranslate_lines` for several.

## Example

> "Make Arabic subtitles for everything in D:\Anime\Night Market that doesn't have them yet, then show me
> episode 3's first lines."

The agent calls `folder_status` (missing only), `make_subtitles` with those paths, polls `job_status` until
`done`, then `read_subtitles` for episode 3.
