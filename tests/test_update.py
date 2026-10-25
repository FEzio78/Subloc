import json
import os
import subprocess
from pathlib import Path

import pytest

from subloc import cli, update
from subloc.errors import SublocError

SHA = "1bc609f256ef45c7796d0e0de1c206c069750919a1f81ece4b6b9eaaa04668e4"


def release_json(tag="v0.3.0", name="Subloc-0.3.0-setup.exe", digest=f"sha256:{SHA}"):
    asset = {"name": name, "size": 159_000_000, "browser_download_url": f"https://example.invalid/{name}"}
    if digest is not None:
        asset["digest"] = digest
    return {"tag_name": tag, "html_url": f"https://github.com/FEzio78/Subloc/releases/tag/{tag}",
            "assets": [{"name": "notes.txt", "size": 1}, asset]}  # fmt: skip


def test_a_release_gives_its_installer_and_checksum():
    rel = update.parse(release_json())
    assert (rel.version, rel.size, rel.sha256) == ("0.3.0", 159_000_000, SHA)
    assert rel.url.endswith("Subloc-0.3.0-setup.exe") and rel.installable


def test_no_checksum_or_another_versions_installer_means_not_installable():
    assert not update.parse(release_json(digest=None)).installable
    assert not update.parse(release_json(digest="md5:abc")).installable
    assert not update.parse(release_json(name="Subloc-0.2.9-setup.exe")).installable  # not this release's
    assert update.parse({"tag_name": "v0.3.0", "html_url": "x"}).url == ""


def test_versions_compare_as_numbers():
    assert update.is_newer("0.10.0", "0.9.9") and update.is_newer("v0.2.1", "0.2.0")
    assert not update.is_newer("0.2.0", "0.2.0") and not update.is_newer("0.1.9", "0.2.0")
    assert not update.is_newer("", "0.2.0")


def test_nothing_unchecked_is_ever_downloaded():
    with pytest.raises(SublocError, match="checksum"):
        update.fetch(update.parse(release_json(digest=None)))
    with pytest.raises(SublocError, match="no installer"):
        update.fetch(update.Release("v0.3.0", "0.3.0", "page"))


def test_the_download_is_checked_and_older_installers_are_removed(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLOC_DATA", str(tmp_path))
    old = tmp_path / "updates" / "Subloc-0.2.5-setup.exe"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    seen = {}

    def fake_download(url, dest, sha256, on_progress, cancel):
        seen.update(url=url, sha=sha256)
        dest.write_bytes(b"new")
        return dest

    monkeypatch.setattr(update, "download", fake_download)
    path = update.fetch(update.parse(release_json()))
    assert path.name == "Subloc-0.3.0-setup.exe" and seen["sha"] == SHA and not old.exists()


def test_the_installer_runs_quietly_into_the_apps_own_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLOC_DATA", str(tmp_path))
    args = update.install_args(Path("C:/x/Subloc-0.3.0-setup.exe"), Path("C:/Apps/Subloc"), reopen=True)
    assert args[0].endswith("Subloc-0.3.0-setup.exe")
    for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/CURRENTUSER",
                 "/REOPEN=1"):  # fmt: skip
        assert flag in args
    assert any(a.startswith("/DIR=") and a.endswith("Subloc") for a in args)
    assert not any(a.startswith("/TASKS") for a in args)  # the tasks chosen at the first install stay
    assert "/REOPEN=1" not in update.install_args(Path("i.exe"), Path("d"), reopen=False)
    assert not any(a.startswith("/WAITPID") for a in args)
    assert "/WAITPID=4242" in update.install_args(Path("i.exe"), Path("d"), reopen=True, wait_pid=4242)


def test_from_the_source_folder_nothing_is_installed(tmp_path):
    installer = tmp_path / "Subloc-0.3.0-setup.exe"
    installer.write_bytes(b"x")
    assert update.app_dir() is None  # tests run from source
    with pytest.raises(SublocError, match="git"):
        update.run_installer(installer)


def test_the_installer_starts_detached_from_subloc(monkeypatch, tmp_path):
    installer = tmp_path / "Subloc-0.3.0-setup.exe"
    installer.write_bytes(b"x")
    monkeypatch.setattr(update, "app_dir", lambda: tmp_path / "app")
    started = {}
    monkeypatch.setattr(
        update.proc, "popen", lambda cmd, extra_flags=0, **kw: started.update(cmd=cmd, flags=extra_flags)
    )
    update.run_installer(installer, reopen=True)
    assert started["cmd"][0] == str(installer) and started["flags"] != 0
    assert f"/WAITPID={os.getpid()}" in started["cmd"]  # the installer waits until this Subloc has quit


def test_other_subloc_windows_are_counted_but_not_this_one(monkeypatch):
    out = (f'"Subloc.exe","{os.getpid()}","Console","1","200,000 K"\n'
           '"Subloc.exe","777","Console","1","180,000 K"\n'
           "INFO: No tasks are running which match the specified criteria.\n")  # fmt: skip
    monkeypatch.setattr(update.proc, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, out, ""))
    assert update.other_windows() == 1
    none = "INFO: No tasks are running which match the specified criteria.\n"
    monkeypatch.setattr(update.proc, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, none, ""))
    assert update.other_windows() == 0


def test_cli_update_asks_to_close_the_window_first(monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "version", lambda: "0.2.0")
    monkeypatch.setattr(update, "latest", lambda: update.parse(release_json()))
    monkeypatch.setattr(update, "app_dir", lambda: Path("C:/Apps/Subloc"))
    monkeypatch.setattr(cli, "holder", lambda: "")
    monkeypatch.setattr(update, "other_windows", lambda: 1)
    monkeypatch.setattr(update, "fetch", lambda *a, **k: pytest.fail("must not download while the window is open"))
    code, _ = run(["update"], capsys)
    assert code == cli.BUSY


class Answer:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.text = status, data, json.dumps(data or {})

    def json(self):
        return self._data


def test_latest_reads_github_or_a_test_feed(monkeypatch):
    urls = []
    monkeypatch.setattr(update.httpx, "get", lambda url, **kw: urls.append(url) or Answer(200, release_json()))
    assert update.latest().version == "0.3.0" and urls[-1] == update.LATEST
    monkeypatch.setenv(update.FEED_ENV, "http://127.0.0.1:9/latest.json")
    update.latest()
    assert urls[-1] == "http://127.0.0.1:9/latest.json"
    monkeypatch.setattr(update.httpx, "get", lambda url, **kw: Answer(404))
    assert update.latest() is None  # nothing published yet
    monkeypatch.setattr(update.httpx, "get", lambda url, **kw: Answer(500))
    with pytest.raises(SublocError):
        update.latest()


def run(argv, capsys):
    code = cli.run_cli(argv)
    return code, capsys.readouterr().out


def test_cli_update_check_says_whether_there_is_a_newer_one(monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "version", lambda: "0.2.0")
    monkeypatch.setattr(update, "latest", lambda: update.parse(release_json()))
    code, out = run(["update", "--check", "--json"], capsys)
    assert code == 0 and json.loads(out) == {"current": "0.2.0", "latest": "0.3.0", "newer": True,
                                             "page": release_json()["html_url"], "installing": False}  # fmt: skip
    same = release_json(tag="v0.2.0", name="Subloc-0.2.0-setup.exe")
    monkeypatch.setattr(update, "latest", lambda: update.parse(same))
    code, out = run(["update"], capsys)
    assert code == 0 and "latest version (0.2.0)" in out


def test_cli_update_from_source_points_to_git(monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "version", lambda: "0.2.0")
    monkeypatch.setattr(update, "latest", lambda: update.parse(release_json()))
    code, out = run(["update"], capsys)
    assert code == 0 and "git" in out


def test_cli_update_waits_for_running_work(monkeypatch, capsys):
    monkeypatch.setattr(cli.service, "version", lambda: "0.2.0")
    monkeypatch.setattr(update, "latest", lambda: update.parse(release_json()))
    monkeypatch.setattr(update, "app_dir", lambda: Path("C:/Apps/Subloc"))
    monkeypatch.setattr(cli, "holder", lambda: "Subloc's window: Episode 3")
    monkeypatch.setattr(update, "fetch", lambda *a, **k: pytest.fail("must not download while busy"))
    code, _ = run(["update"], capsys)
    assert code == cli.BUSY


def test_cli_update_downloads_and_starts_the_installer(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli.service, "version", lambda: "0.2.0")
    monkeypatch.setattr(update, "latest", lambda: update.parse(release_json()))
    monkeypatch.setattr(update, "app_dir", lambda: tmp_path / "app")
    monkeypatch.setattr(cli, "holder", lambda: "")
    monkeypatch.setattr(update, "other_windows", lambda: 0)
    installer = tmp_path / "Subloc-0.3.0-setup.exe"
    monkeypatch.setattr(update, "fetch", lambda rel, progress: progress(1, 1) or installer)
    ran = []
    monkeypatch.setattr(update, "run_installer", lambda path, reopen: ran.append((path, reopen)))
    code, out = run(["update", "--json"], capsys)
    assert code == 0 and json.loads(out)["installing"] is True and ran == [(installer, False)]
