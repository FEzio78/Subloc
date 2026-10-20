import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from subloc.download import download
from subloc.errors import SublocError

DATA = bytes(range(256)) * 4096  # 1 MiB


class Handler(BaseHTTPRequestHandler):
    """Serves DATA with HTTP Range support, like Hugging Face's CDN."""

    def do_GET(self):
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(DATA):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
        else:
            self.send_response(200)
        body = DATA[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/model.gguf"
    srv.shutdown()


def test_download_resumes_and_verifies(server, tmp_path):
    dest = tmp_path / "model.gguf"
    part = tmp_path / "model.gguf.part"
    part.write_bytes(DATA[:300_000])  # an interrupted earlier download
    seen = []
    download(server, dest, hashlib.sha256(DATA).hexdigest(), lambda d, t: seen.append((d, t)))
    assert dest.read_bytes() == DATA
    assert not part.exists()
    assert seen[0][0] > 300_000 and seen[-1] == (len(DATA), len(DATA))  # continued, didn't restart


def test_checksum_mismatch_removes_the_file(server, tmp_path):
    dest = tmp_path / "model.gguf"
    with pytest.raises(SublocError, match="damaged"):
        download(server, dest, "0" * 64)
    assert not dest.exists() and not (tmp_path / "model.gguf.part").exists()


def test_already_downloaded_file_is_not_fetched_again(tmp_path):
    dest = tmp_path / "model.gguf"
    dest.write_bytes(DATA)
    download("http://127.0.0.1:9/never", dest, hashlib.sha256(DATA).hexdigest())  # no server needed
    assert dest.read_bytes() == DATA
