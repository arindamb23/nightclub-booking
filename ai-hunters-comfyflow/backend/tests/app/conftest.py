"""Shared fixtures: an isolated .env + data dir and a fake ComfyUI server."""
import os
import socket
import tempfile
import threading
import time
import http.server
import functools
from pathlib import Path

import pytest
import uvicorn


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


TMP = Path(tempfile.mkdtemp(prefix="comfyflow_test_"))
COMFY_PORT = _free_port()
FILES_PORT = _free_port()
(TMP / "comfy" / "ComfyUI").mkdir(parents=True)
(TMP / "files").mkdir()
(TMP / ".env").write_text(
    "\n".join([
        "BACKEND_HOST=127.0.0.1", "BACKEND_PORT=3015", "FRONTEND_PORT=5091",
        "COMFYUI_HOST=127.0.0.1", f"COMFYUI_PORT={COMFY_PORT}",
        f"COMFYUI_DIR={TMP / 'comfy' / 'ComfyUI'}", f"MODELS_DIR={TMP / 'models'}",
        f"DATA_DIR={TMP / 'data'}", "MAX_PARALLEL_DOWNLOADS=2", "HF_TOKEN=", "CIVITAI_TOKEN=",
    ]) + "\n",
    encoding="utf-8",
)
os.environ["COMFYFLOW_ENV_FILE"] = str(TMP / ".env")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def _serve_files():
    handler = functools.partial(_Quiet, directory=str(TMP / "files"))
    http.server.ThreadingHTTPServer(("127.0.0.1", FILES_PORT), handler).serve_forever()


@pytest.fixture(scope="session", autouse=True)
def servers():
    import tools.fake_comfyui as fake

    fake.STEP_DELAY = 0.01
    server = uvicorn.Server(uvicorn.Config(fake.app, host="127.0.0.1", port=COMFY_PORT, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    threading.Thread(target=_serve_files, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield
    server.should_exit = True


@pytest.fixture(scope="session")
def client(servers):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def files_dir():
    return TMP / "files"


@pytest.fixture
def files_url():
    return f"http://127.0.0.1:{FILES_PORT}"


def wait_for(fn, timeout=15.0, interval=0.1):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met in {timeout}s (last={last!r})")
