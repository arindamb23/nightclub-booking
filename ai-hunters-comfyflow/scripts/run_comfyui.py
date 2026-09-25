"""Starts ComfyUI and copies its console output to logs/comfyui.log (shown in ComfyFlow's live node view).

Usage: <comfyui python> scripts/run_comfyui.py <ComfyUI dir> [ComfyUI arguments...]
The console window keeps showing everything ComfyUI prints; the log file is rotated on every start.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG = LOG_DIR / "comfyui.log"
MAX_LOG = 20 * 1024 * 1024  # start a fresh file when it gets bigger than this


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    comfy_dir = Path(sys.argv[1]).resolve()
    LOG_DIR.mkdir(exist_ok=True)
    if LOG.exists():
        LOG.replace(LOG.with_name("comfyui.previous.log"))
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        [sys.executable, "-u", str(comfy_dir / "main.py"), *sys.argv[2:]],
        cwd=str(comfy_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    out = getattr(sys.stdout, "buffer", None)
    log = open(LOG, "ab")
    try:
        while True:
            chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
            if not chunk:
                break
            if out is not None:
                try:
                    out.write(chunk)
                    out.flush()
                except OSError:
                    out = None  # console closed: keep logging
            log.write(chunk)
            log.flush()
            if log.tell() > MAX_LOG:
                log.close()
                log = open(LOG, "wb")
    except KeyboardInterrupt:
        proc.terminate()
    finally:
        log.close()
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
