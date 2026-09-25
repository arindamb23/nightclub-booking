"""Downloads survive servers that drop the connection mid-file (Hugging Face CDN 'IncompleteRead')."""
import http.server
import os
import socket
import threading

import pytest

from tests.app.conftest import wait_for, TMP

DATA = os.urandom(3 * 1024 * 1024 + 123)


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Flaky(http.server.BaseHTTPRequestHandler):
    drops_left = 3          # the first requests die part-way through
    requests_seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Flaky.requests_seen.append(self.headers.get("Range"))
        if self.path == "/missing.bin":
            self.send_error(404)
            return
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].split("-")[0])
            if start >= len(DATA):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
        else:
            self.send_response(200)
        body = DATA[start:]
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        if Flaky.drops_left > 0:
            Flaky.drops_left -= 1
            self.wfile.write(body[: 700 * 1024])  # promise everything, send a part, hang up
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        self.wfile.write(body)

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(DATA)))
        self.end_headers()


@pytest.fixture(scope="module")
def flaky_url():
    port = _free_port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Flaky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    from app.services import downloader
    monkeypatch.setattr(downloader, "RETRY_DELAY_SCALE", 0.01)


def _row(client, name):
    return next(m for m in client.get("/api/models").json()["models"] if m["name"] == name)


def test_dropped_connections_resume_automatically(client, flaky_url):
    Flaky.drops_left, Flaky.requests_seen = 3, []
    client.post("/api/models", json={"name": "flaky.safetensors", "url": f"{flaky_url}/model.bin", "category": "unet"})
    client.post("/api/models/download", json={"name": "flaky.safetensors"})
    row = wait_for(lambda: (lambda r: r if r["status"] in ("ready", "error") else None)(_row(client, "flaky.safetensors")))
    assert row["status"] == "ready", row
    assert (TMP / "models" / "unet" / "flaky.safetensors").read_bytes() == DATA
    # first request fresh, then three resumes from the bytes already on disk
    assert Flaky.requests_seen[0] is None
    assert all(r and r.startswith("bytes=") for r in Flaky.requests_seen[1:]), Flaky.requests_seen
    assert len(Flaky.requests_seen) == 4
    assert not (TMP / "models" / "unet" / "flaky.safetensors.part").exists()


def test_permanent_errors_fail_without_retrying(client, flaky_url):
    Flaky.drops_left, Flaky.requests_seen = 0, []
    client.post("/api/models", json={"name": "gone404.safetensors", "url": f"{flaky_url}/missing.bin", "category": "unet"})
    client.post("/api/models/download", json={"name": "gone404.safetensors"})
    row = wait_for(lambda: (lambda r: r if r["status"] == "error" else None)(_row(client, "gone404.safetensors")))
    assert "404" in row["job"]["error"] and len(Flaky.requests_seen) == 1


def test_complete_partial_file_is_kept_on_416(client, flaky_url):
    Flaky.drops_left, Flaky.requests_seen = 0, []
    target = TMP / "models" / "unet" / "complete.safetensors"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_name(target.name + ".part").write_bytes(DATA)  # e.g. finished just before a crash
    client.post("/api/models", json={"name": "complete.safetensors", "url": f"{flaky_url}/model.bin", "category": "unet"})
    client.post("/api/models/download", json={"name": "complete.safetensors"})
    row = wait_for(lambda: (lambda r: r if r["status"] in ("ready", "error") else None)(_row(client, "complete.safetensors")))
    assert row["status"] == "ready" and target.read_bytes() == DATA
