"""Updates: is there a newer Subloc, fetch its installer (checked), and run it.

Only when the user asks (Settings → Check for updates, `subloc update`), or once a day at start-up if they turned
that on: it contacts GitHub, nothing else. The installer comes from the GitHub release and must match the SHA-256
GitHub publishes for it; without that digest nothing is run. The installed app runs it quietly into its own folder
(an update in place: settings, models and projects live in the data folder and are kept), after Subloc has
closed; the window opens again when the update is done. From the source tree (not installed) there is nothing to
install: the user updates with git.
"""

import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import FROZEN, proc
from .config import data_dir
from .download import download
from .errors import SublocError

REPO = "FEzio78/Subloc"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
# Tests point this at a local feed (an older build updating to a newer one, end to end); users never set it.
FEED_ENV = "SUBLOC_UPDATE_FEED"
INSTALLER = re.compile(r"^Subloc-(\d+\.\d+\.\d+)-setup\.exe$")


@dataclass(frozen=True)
class Release:
    tag: str  # "v0.3.0"
    version: str  # "0.3.0"
    page: str  # the release page (notes)
    url: str = ""  # the installer download ("" = the release has no installer)
    size: int = 0
    sha256: str = ""  # from GitHub's asset digest ("" = not published: never run)

    @property
    def installable(self) -> bool:
        return bool(self.url and self.sha256)


def parts(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def is_newer(candidate: str, mine: str) -> bool:
    try:
        return parts(candidate) > parts(mine)
    except ValueError:
        return False


def parse(data: dict) -> Release:
    """A GitHub release (the API's JSON) → Release: its installer and that installer's digest."""
    tag = str(data.get("tag_name") or "")
    version = ".".join(str(n) for n in parts(tag)) if parts(tag) else ""
    rel = Release(tag, version, str(data.get("html_url") or ""))
    for a in data.get("assets") or []:
        name = str(a.get("name") or "")
        m = INSTALLER.match(name)
        if not m or m.group(1) != version:
            continue
        digest = str(a.get("digest") or "")
        sha = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            sha = ""
        return Release(tag, version, rel.page, str(a.get("browser_download_url") or ""), int(a.get("size") or 0), sha)
    return rel


def latest(timeout: float = 8.0) -> Release | None:
    """The newest published release, or None when there is none yet. Raises SublocError when GitHub can't be
    reached or answers something unexpected."""
    url = os.environ.get(FEED_ENV) or LATEST
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"Accept": "application/vnd.github+json"})
    except httpx.HTTPError as e:
        raise SublocError("Couldn't reach GitHub. Check the internet connection.", str(e)) from e
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise SublocError(f"GitHub answered {r.status_code}.", r.text[:300])
    try:
        return parse(r.json())
    except (ValueError, TypeError, AttributeError) as e:
        raise SublocError("GitHub sent an answer Subloc couldn't read.", r.text[:300]) from e


def folder() -> Path:
    return data_dir() / "updates"


def fetch(rel: Release, on_progress: Callable[[int, int], None] = lambda d, t: None,
          cancel: threading.Event | None = None) -> Path:  # fmt: skip
    """Download the release's installer into the data folder, checked against GitHub's SHA-256 (resumes a broken
    download). Raises SublocError when the release can't be installed this way, download.Cancelled when stopped."""
    if not rel.url:
        raise SublocError("This release has no installer to download.")
    if not rel.sha256:
        raise SublocError("GitHub doesn't publish a checksum for this installer, so Subloc won't run it. "
                          "Download it from the release page instead.")  # fmt: skip
    path = folder() / f"Subloc-{rel.version}-setup.exe"
    download(rel.url, path, rel.sha256, on_progress, cancel)
    for old in folder().glob("Subloc-*-setup.exe"):  # keep only this one
        if old != path:
            old.unlink(missing_ok=True)
    return path


def app_dir() -> Path | None:
    """Where the installed app lives (the folder of Subloc.exe / subloc-cli.exe), None in the source tree."""
    return Path(sys.executable).resolve().parent if FROZEN else None


def install_args(installer: Path, target: Path, reopen: bool, wait_pid: int = 0) -> list[str]:
    """The installer, quietly, into the app's own folder: an update in place. Inno Setup keeps the tasks chosen
    the first time (Explorer menu, desktop icon) and closes what still runs from that folder; /REOPEN=1 makes it
    open Subloc again at the end; /WAITPID makes it wait until the Subloc that started it has quit (a Subloc
    still open when it checks for running programs makes it give up) (installer/subloc.iss)."""
    log = folder() / "update-log.txt"
    args = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/CURRENTUSER",
            f"/DIR={target}", f"/LOG={log}"]  # fmt: skip
    if wait_pid:
        args.append(f"/WAITPID={wait_pid}")
    if reopen:
        args.append("/REOPEN=1")
    return args


def other_windows() -> int:
    """How many Subloc windows (Subloc.exe) run besides this process. The installer can't replace the program
    while one is open, so an update asks to close them first."""
    try:
        out = proc.run(["tasklist", "/FI", "IMAGENAME eq Subloc.exe", "/FO", "CSV", "/NH"],
                       capture_output=True, text=True, timeout=10).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return 0
    pids = set()
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) > 1 and cols[0].lower() == "subloc.exe" and cols[1].isdigit():
            pids.add(int(cols[1]))
    pids.discard(os.getpid())
    return len(pids)


def run_installer(installer: Path, reopen: bool = True) -> None:
    """Start the installer on its own (it outlives Subloc, which must quit right after)."""
    target = app_dir()
    if target is None:
        raise SublocError("This copy of Subloc runs from its source folder: update it with git instead.")
    if not installer.exists():
        raise SublocError("The downloaded installer is missing. Check for updates again.")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc.popen(install_args(installer, target, reopen, os.getpid()), close_fds=True, extra_flags=flags)
