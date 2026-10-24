"""Subloc as an MCP server, so AI agents (Claude Desktop, Claude Code and others) can make and fix subtitles.

    subloc mcp      (stdio transport: one JSON-RPC message per line on stdin and stdout)

Everything stays on this PC. Work that takes minutes (subtitles, re-translating lines, burn-in, reading a library
folder) starts a job and returns its id at once; the agent polls job_status. The protocol is implemented directly
(it is small), so Subloc needs no extra packages for it. See docs/agents.md.
"""

import json
import sys
import threading
import traceback
from collections.abc import Callable
from pathlib import Path

from . import library, service
from .busy import holder

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """\
Subloc makes subtitles for videos on this PC, with local AI only (nothing is uploaded): it listens with Whisper
(or reads subtitles inside the file) and translates with a local language model. Arabic is its strongest
language; any language works. Paths are this PC's paths (Windows). Languages are two-letter codes (ar, en, ja…).

Typical work:
1. status — the user's settings (default subtitle language, translator) and whether Subloc is busy.
2. folder_status or library_list — what still needs subtitles.
3. make_subtitles — returns a job_id at once. Check job_status every 30–60 seconds: a 24-minute episode takes
   about 3–6 minutes on a good graphics card, longer without one. Only one job runs at a time on this PC (also
   shared with the Subloc app); others wait in line.
4. read_subtitles, then edit_line or retranslate_lines to fix lines (for example a name spelled wrongly).
5. burn_subtitles only when the user wants a video with the subtitles drawn in (for phones and TVs).
Subtitles are saved next to each video (Video.ar.srt; Video.ar.ass when a style is set).
"""


class ToolError(Exception):
    pass


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
LANG = {"type": "string", "description": "two-letter language code, e.g. ar, en; default: the user's setting"}
PATH = {"type": "string", "description": "a full path on this PC"}
INT = {"type": "integer", "minimum": 0}
BOOL = {"type": "boolean"}

READ = {"readOnlyHint": True, "openWorldHint": False}
WRITE = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}


class Server:
    def __init__(self, jobs: service.Jobs | None = None, get_settings: Callable[[], service.Settings] | None = None):
        self.jobs = jobs or service.Jobs("an agent (MCP)")
        self.get_settings = get_settings or service.settings
        self.tools: dict[str, tuple[str, dict, dict, Callable[[dict], dict]]] = {
            "status": (
                "The user's Subloc settings, whether the translator is ready, whether Subloc is busy, and "
                "the jobs started in this session.",
                _obj({}),
                READ,
                self.status,
            ),
            "video_info": (
                "One video: length, audio and subtitle tracks inside it, subtitle files next to it, and "
                "how far Subloc's subtitles are.",
                _obj({"path": PATH, "target": LANG}, ["path"]),
                READ,
                self.video_info,
            ),
            "folder_status": (
                "Every video under a folder (all subfolders) and whether it still needs subtitles in "
                "the target language. Quick: looks at files only.",
                _obj({"folder": PATH, "target": LANG, "missing_only": BOOL, "limit": INT}, ["folder"]),
                READ,
                self.folder_status,
            ),
            "make_subtitles": (
                "Start making subtitles for videos and/or folders (every subfolder). Returns a job_id "
                "at once; poll job_status. Videos already done are skipped unless retranslate is set. "
                "translate=false makes only subtitles in the spoken language.",
                _obj(
                    {
                        "paths": {"type": "array", "items": S, "minItems": 1},
                        "target": LANG,
                        "source": {
                            "type": "string",
                            "description": "spoken language code, or 'mixed'; default: detected",
                        },
                        "quality": {"type": "string", "enum": sorted(service.SPEECH_QUALITY)},
                        "translate": BOOL,
                        "use_subtitles_inside": BOOL,
                        "retranslate": BOOL,
                        "retranscribe": BOOL,
                        "style": S,
                    },
                    ["paths"],
                ),
                WRITE,
                self.make_subtitles,
            ),
            "job_status": (
                "Progress of a job (or of every job of this session when job_id is left out): status "
                "queued | waiting | running | done | failed | stopped, per-video status, files written.",
                _obj({"job_id": S}),
                READ,
                self.job_status,
            ),
            "cancel_job": (
                "Stop a job. Progress is kept: starting the same work again continues it.",
                _obj({"job_id": S}, ["job_id"]),
                WRITE,
                self.cancel_job,
            ),
            "read_subtitles": (
                "The subtitle lines of a video Subloc has worked on: id, start and end in seconds, "
                "original text and translation. Paged with offset and limit (default 200).",
                _obj({"path": PATH, "offset": INT, "limit": INT}, ["path"]),
                READ,
                self.read_subtitles,
            ),
            "edit_line": (
                "Replace the translation of one line (by id); the subtitle files are written again.",
                _obj({"path": PATH, "line_id": INT, "text": S}, ["path", "line_id", "text"]),
                WRITE,
                self.edit_line,
            ),
            "retranslate_lines": (
                "Translate some lines again (with their neighbours as context and the folder's "
                "name list). Returns a job_id; the new lines are in its result. Optional listener: who these "
                "lines are spoken to (man, woman, several), to fix the form of 'you'; it is kept for later.",
                _obj(
                    {
                        "path": PATH,
                        "line_ids": {"type": "array", "items": INT, "minItems": 1},
                        "listener": {"type": "string", "enum": ["man", "woman", "several"]},
                    },
                    ["path", "line_ids"],
                ),
                WRITE,
                self.retranslate_lines,
            ),
            "burn_subtitles": (
                "Start making a copy of the video with its subtitles drawn into the picture (for "
                "devices that can't load subtitle files). Returns a job_id. The original is untouched.",
                _obj({"path": PATH, "style": S, "output": PATH}, ["path"]),
                WRITE,
                self.burn_subtitles,
            ),
            "library_list": (
                "The videos in the Subloc app's library (folders the user added) with their status.",
                _obj({"target": LANG, "missing_only": BOOL, "folder": PATH, "limit": INT}),
                READ,
                self.library_list,
            ),
            "library_add_folder": (
                "Add a folder (movies, series, anime…) to the app's library and read it, every "
                "subfolder included. Returns a job_id.",
                _obj({"folder": PATH}, ["folder"]),
                WRITE,
                self.library_add_folder,
            ),
            "library_refresh": (
                "Read the library folders again (or one folder) to pick up new or changed videos. Returns a job_id.",
                _obj({"folder": PATH}),
                WRITE,
                self.library_refresh,
            ),
        }

    # ---------------------------------------------------------------- protocol

    def handle(self, msg: dict) -> dict | None:
        """One JSON-RPC message in, its response out (None for notifications)."""
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        if mid is None:  # a notification (initialized, cancelled…): nothing to answer
            return None
        try:
            if method == "initialize":
                asked = params.get("protocolVersion")
                result: dict = {
                    "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "subloc", "title": "Subloc", "version": service.version()},
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": n, "description": d, "inputSchema": schema, "annotations": ann}
                                    for n, (d, schema, ann, _) in self.tools.items()]}  # fmt: skip
            elif method == "tools/call":
                result = self.call(params.get("name", ""), params.get("arguments") or {})
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        except Exception as e:  # a bug, not a tool error: still answer
            traceback.print_exc(file=sys.stderr)
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e) or type(e).__name__}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, name: str, args: dict) -> dict:
        if name not in self.tools:
            return _error(f"Unknown tool: {name}")
        try:
            out = self.tools[name][3](args)
        except (ToolError, FileNotFoundError, ValueError, KeyError, StopIteration) as e:
            text = str(e) if not isinstance(e, (KeyError, StopIteration)) else "No such line or job."
            return _error(text)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return _error(f"{type(e).__name__}: {e}")
        return {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=1)}],
                "structuredContent": out, "isError": False}  # fmt: skip

    # ---------------------------------------------------------------- tools

    def _target(self, args: dict, st: service.Settings) -> str:
        return str(args.get("target") or st.target)

    @staticmethod
    def _path(args: dict, key: str = "path", folder: bool = False) -> Path:
        p = Path(str(args.get(key, ""))).expanduser()
        if not str(args.get(key, "")) or not p.exists():
            raise ToolError(f"Not found on this PC: {args.get(key)!r}")
        if folder and not p.is_dir():
            raise ToolError(f"Not a folder: {p}")
        return p

    def status(self, args: dict) -> dict:
        st = self.get_settings()
        return {"version": service.version(), "settings": service.settings_report(st),
                "translator": service.translator_status(st), "busy": holder() or None,
                "jobs": [j.report() for j in self.jobs.items.values()]}  # fmt: skip

    def video_info(self, args: dict) -> dict:
        return service.video_report(self._path(args), self._target(args, self.get_settings()))

    def folder_status(self, args: dict) -> dict:
        st = self.get_settings()
        return service.folder_report(self._path(args, "folder", folder=True), self._target(args, st),
                                     bool(args.get("missing_only")), int(args.get("limit") or 500))  # fmt: skip

    def make_subtitles(self, args: dict) -> dict:
        st = self.get_settings()
        paths = [self._path({"p": p}, "p") for p in args.get("paths") or []]
        if not paths:
            raise ToolError("Give at least one video or folder.")
        st.target = self._target(args, st)
        if args.get("source"):
            st.source = str(args["source"])
        if args.get("quality"):
            st.asr_model = service.SPEECH_QUALITY[str(args["quality"])]
        if args.get("style"):
            st.style = service.style_named(str(args["style"]), st)
        over = {"retranslate": bool(args.get("retranslate")), "retranscribe": bool(args.get("retranscribe"))}
        if args.get("use_subtitles_inside") is False:
            over["prefer_builtin_subs"] = False
        busy = holder()  # before submitting: the job takes the lock itself at once when it's free
        job = service.submit_subtitles(self.jobs, paths, st, translate=args.get("translate", True) is not False,
                                       **over)  # fmt: skip
        return {"job_id": job.id, "videos": [v.path for v in job.videos], "target": st.target,
                "note": "Started. Check job_status every 30–60 seconds." + (
                    f" Subloc is busy ({busy}); this job waits its turn." if busy else "")}  # fmt: skip

    def job_status(self, args: dict) -> dict:
        if args.get("job_id"):
            if args["job_id"] not in self.jobs.items:
                raise ToolError(f"No job {args['job_id']!r} in this session.")
            return self.jobs.items[str(args["job_id"])].report()
        return {"jobs": [j.report() for j in self.jobs.items.values()]}

    def cancel_job(self, args: dict) -> dict:
        if args.get("job_id") not in self.jobs.items:
            raise ToolError(f"No job {args.get('job_id')!r} in this session.")
        return self.jobs.cancel(str(args["job_id"])).report()

    def read_subtitles(self, args: dict) -> dict:
        return service.read_lines(self._path(args), int(args.get("offset") or 0), int(args.get("limit") or 200))

    def edit_line(self, args: dict) -> dict:
        return service.edit_line(self._path(args), int(args["line_id"]), str(args["text"]), self.get_settings())

    def retranslate_lines(self, args: dict) -> dict:
        ids = [int(i) for i in args.get("line_ids") or []]
        listener = str(args["listener"]) if args.get("listener") else None
        job = service.submit_retranslate(self.jobs, self._path(args), ids, self.get_settings(), listener)
        return {"job_id": job.id, "note": "Started. The new lines will be in job_status's result."}

    def burn_subtitles(self, args: dict) -> dict:
        st = self.get_settings()
        style = service.style_named(str(args["style"]), st) if args.get("style") else st.style
        out = Path(str(args["output"])) if args.get("output") else None
        job = service.submit_burn(self.jobs, self._path(args), st, style, out)
        return {"job_id": job.id, "note": "Started. This takes about as long as playing the video, often less."}

    def library_list(self, args: dict) -> dict:
        st = self.get_settings()
        folder = str(args["folder"]) if args.get("folder") else None
        return service.library_report(self._target(args, st), bool(args.get("missing_only")), folder,
                                      int(args.get("limit") or 500))  # fmt: skip

    def library_add_folder(self, args: dict) -> dict:
        job = service.submit_scan(self.jobs, self._path(args, "folder", folder=True), add=True)
        return {"job_id": job.id, "folders": library.load().roots}

    def library_refresh(self, args: dict) -> dict:
        folder = self._path(args, "folder", folder=True) if args.get("folder") else None
        return {"job_id": service.submit_scan(self.jobs, folder).id}


def _error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def serve() -> None:
    """Read messages from stdin, answer on stdout. Anything else that prints goes to stderr, so it can't corrupt
    the protocol stream."""
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8", newline="\n")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout = sys.stderr
    write_lock = threading.Lock()
    server = Server()
    for line in sys.stdin:
        line = line.strip().lstrip(chr(0xFEFF))  # some shells start a pipe with a byte-order mark
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: dict | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = server.handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            with write_lock:
                out.write(json.dumps(reply, ensure_ascii=False) + "\n")
                out.flush()
