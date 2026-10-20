"""Resumable, verified downloads (multi-GB model files over home connections).

Data goes to `<name>.part` and continues from where it stopped (HTTP Range); the finished file is checked
against its sha256 before it replaces the target, so a broken download never looks like a good model.
"""

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path

import httpx

from .errors import SublocError

CHUNK = 1024 * 1024


class Cancelled(Exception):
    pass


def download(
    url: str,
    dest: Path,
    sha256: str | None = None,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    cancel: threading.Event | None = None,
    timeout: float = 30.0,
) -> Path:
    """Fetch `url` to `dest`. Calls on_progress(bytes_done, bytes_total). Raises Cancelled / SublocError."""
    cancel = cancel or threading.Event()
    if dest.exists() and (not sha256 or _sha256(dest) == sha256):
        size = dest.stat().st_size
        on_progress(size, size)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                          timeout=httpx.Timeout(timeout, read=120)) as r:  # fmt: skip
            if r.status_code == 416:  # the .part is already complete
                total = have
            elif r.status_code in (200, 206):
                if r.status_code == 200:  # server ignored Range: start over
                    have = 0
                total = have + int(r.headers.get("content-length", 0))
                with part.open("ab" if have else "wb") as f:
                    for chunk in r.iter_bytes(CHUNK):
                        if cancel.is_set():
                            raise Cancelled()
                        f.write(chunk)
                        have += len(chunk)
                        on_progress(have, total)
            else:
                raise SublocError(f"The download server answered {r.status_code}.", url)
    except httpx.HTTPError as e:
        raise SublocError("The download was interrupted. Check the internet connection and press Install "
                          "again — it continues where it stopped.", str(e)) from e  # fmt: skip
    except OSError as e:
        from .errors import friendly_os_error

        raise friendly_os_error(e, dest.name) from e
    if sha256 and _sha256(part) != sha256:
        part.unlink(missing_ok=True)
        raise SublocError("The downloaded file was damaged (checksum mismatch) and was removed. Please try again.")
    part.replace(dest)
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK * 8):
            h.update(block)
    return h.hexdigest()
