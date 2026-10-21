"""The command line, the MCP server for agents and the busy lock they share with the app. The heavy work (Whisper,
translation) is replaced by a fake; placeholder files only."""

import json
import time
from pathlib import Path

import pytest

import subloc.busy
import subloc.config
from subloc import cli, library, recent, service
from subloc.batch import Item
from subloc.mcp_server import PROTOCOL_VERSIONS, Server
from subloc.models import Cue, Project
from subloc.pipeline import project_path


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Data folder in tmp; the app's saved settings aren't read; fake engine instead of Whisper + translator."""
    data = tmp_path / "data"
    for mod in (subloc.config, subloc.busy, recent, library):
        monkeypatch.setattr(mod, "data_dir", lambda: data)
    monkeypatch.setattr(service, "settings", lambda: service.Settings(target="ar"))
    monkeypatch.setattr(library, "read_tracks", lambda v: setattr(v, "probed", f"{v.size}:{v.mtime}"))

    def fake_batch(videos, opt, rep, cancel):
        for i, v in enumerate(videos):
            rep.item(i, Item(v, "listening"))
            rep.stage("transcribe", 0.5)
            v.with_name(f"{v.stem}.{opt.target}.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nمرحبا\n",
                                                                 encoding="utf-8")  # fmt: skip
            rep.item(i, Item(v, "failed", "Couldn't read the sound") if "bad" in v.name else Item(v, "done"))
        return []

    monkeypatch.setattr(service, "run_batch", fake_batch)
    return tmp_path


def make_show(tmp_path):
    s1 = tmp_path / "Show" / "Season 1"
    s1.mkdir(parents=True)
    for n in ("Ep 1.mkv", "Ep 2.mkv"):
        (s1 / n).write_bytes(b"x")
    (s1 / "Ep 1.ar.srt").write_text("x", encoding="utf-8")
    return tmp_path / "Show"


def with_project(video):
    cues = [Cue(id=i, start=float(i), end=i + 1.0, text=f"line {i}", translation=f"سطر {i}") for i in (1, 2, 3)]
    Project(video=str(video), language="en", cues=cues, target_language="ar").save(project_path(video))


def run(capsys, *argv) -> tuple[int, dict | str]:
    code = cli.run_cli(list(argv))
    out = capsys.readouterr().out
    try:
        return code, json.loads(out)
    except ValueError:
        return code, out


# ---------------------------------------------------------------- busy lock


def test_one_heavy_job_at_a_time():
    window, agent = subloc.busy.BusyLock("Subloc's window"), subloc.busy.BusyLock("an agent (MCP)")
    assert window.acquire("Episode 3.mkv")
    assert not agent.acquire("x")
    assert subloc.busy.holder() == "Subloc's window: Episode 3.mkv"
    window.release()
    assert subloc.busy.holder() == ""
    assert agent.acquire("y")
    agent.release()


# ---------------------------------------------------------------- command line


def test_old_command_lines_still_work():
    assert cli._compat(["movie.mkv", "--to", "ar"]) == ["translate", "movie.mkv", "--to", "ar"]
    assert cli._compat(["--models"]) == ["models"]
    assert cli._compat(["movie.mkv", "--info"]) == ["info", "movie.mkv"]
    assert cli._compat(["folder", "x"]) == ["folder", "x"]


def test_folder_status_as_json(capsys, isolated):
    show = make_show(isolated)
    code, r = run(capsys, "folder", str(show), "--json")
    assert code == 0 and isinstance(r, dict)
    assert {Path(it["path"]).name: it["status"] for it in r["items"]} == {"Ep 1.mkv": "done", "Ep 2.mkv": "none"}
    code, r = run(capsys, "folder", str(show), "--missing", "--json")
    assert isinstance(r, dict) and [it["path"].endswith("Ep 2.mkv") for it in r["items"]] == [True]


def test_translate_a_folder(capsys, isolated):
    show = make_show(isolated)
    (show / "Season 1" / "Ep bad.mkv").write_bytes(b"x")
    code, r = run(capsys, "translate", str(show), "--json")
    assert isinstance(r, dict)
    assert code == 1  # one video failed
    assert [v["status"] for v in r["videos"]] == ["done", "done", "failed"]
    assert r["result"] == {"done": 2, "skipped": 0, "failed": 1, "target": "ar"}
    assert any(f.endswith("Ep 2.ar.srt") for f in r["videos"][1]["files"])
    assert [p.name for p in map(lambda it: it.path, recent.load())][:1] == ["Ep bad.mkv"]  # listed on Home


def test_read_and_edit_lines(capsys, isolated):
    show = make_show(isolated)
    video = show / "Season 1" / "Ep 2.mkv"
    with_project(video)
    code, r = run(capsys, "lines", str(video), "--json")
    assert (
        code == 0
        and isinstance(r, dict)
        and [line["translation"] for line in r["lines"]] == ["سطر 1", "سطر 2", "سطر 3"]
    )
    code, r = run(capsys, "edit", str(video), "2", "سطر مصحح", "--json")
    assert code == 0 and isinstance(r, dict) and r["translation"] == "سطر مصحح"
    assert "سطر مصحح" in video.with_name("Ep 2.ar.srt").read_text(encoding="utf-8")
    code, r = run(capsys, "edit", str(video), "99", "x", "--json")
    assert code == 1 and isinstance(r, dict) and "No such line" in r["error"]


def test_busy_without_waiting(capsys):
    other = subloc.busy.BusyLock("Subloc's window")
    other.acquire("Episode 3.mkv")
    try:
        code, r = run(capsys, "translate", "anything.mkv", "--no-wait", "--json")
        assert code == cli.BUSY and isinstance(r, dict) and r["busy"]
    finally:
        other.release()


# ---------------------------------------------------------------- MCP server


def rpc(server: Server, method: str, params: dict | None = None, mid: int = 1) -> dict:
    reply = server.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    assert reply is not None and reply["id"] == mid
    return reply


def call(server: Server, name: str, **args) -> dict:
    return rpc(server, "tools/call", {"name": name, "arguments": args})["result"]


def test_mcp_handshake_and_tools():
    server = Server()
    r = rpc(server, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert r["result"]["protocolVersion"] == "2025-03-26"
    assert r["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert "make_subtitles" in r["result"]["instructions"]
    r = rpc(server, "initialize", {"protocolVersion": "1999-01-01"})
    assert r["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert rpc(server, "ping")["result"] == {}
    tools = rpc(server, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"status", "make_subtitles", "job_status", "read_subtitles", "edit_line", "folder_status"} <= names
    for t in tools:
        assert t["inputSchema"]["type"] == "object" and t["description"]
        assert "readOnlyHint" in t["annotations"]
    assert rpc(server, "no/such")["error"]["code"] == -32601


def test_mcp_errors_are_tool_results():
    server = Server()
    assert call(server, "nope")["isError"]
    r = call(server, "video_info", path="C:/does/not/exist.mkv")
    assert r["isError"] and "Not found" in r["content"][0]["text"]
    assert call(server, "job_status", job_id="zzz")["isError"]


def test_mcp_job_from_start_to_done(isolated):
    show = make_show(isolated)
    server = Server()
    r = call(server, "folder_status", folder=str(show), missing_only=True)
    assert not r["isError"] and [it["status"] for it in r["structuredContent"]["items"]] == ["none"]
    started = call(server, "make_subtitles", paths=[str(show)])["structuredContent"]
    job_id = started["job_id"]
    for _ in range(100):
        st = call(server, "job_status", job_id=job_id)["structuredContent"]
        if st["status"] in ("done", "failed", "stopped"):
            break
        time.sleep(0.05)
    assert st["status"] == "done" and st["progress"] == 1.0
    assert [v["status"] for v in st["videos"]] == ["done", "done"]
    assert json.loads(call(server, "job_status", job_id=job_id)["content"][0]["text"])["job_id"] == job_id
    video = show / "Season 1" / "Ep 2.mkv"
    with_project(video)
    lines = call(server, "read_subtitles", path=str(video), limit=2)["structuredContent"]
    assert lines["total"] == 3 and len(lines["lines"]) == 2
    edited = call(server, "edit_line", path=str(video), line_id=1, text="مرحبا")["structuredContent"]
    assert edited["translation"] == "مرحبا"
