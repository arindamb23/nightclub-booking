"""Background model downloads with resume, progress events and cancellation."""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlencode, parse_qsl, urlunparse

import requests

from app.config import get_settings
from app.events import bus
from app.services.registry import registry, RegistryError

CHUNK = 1024 * 1024
PUBLISH_EVERY = 0.5


class DownloadError(RuntimeError):
    pass


class Job:
    def __init__(self, name: str, path: Path, url: str):
        self.name = name
        self.path = path
        self.url = url
        self.status = "queued"  # queued | downloading | done | error | cancelled
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0
        self.error = ""
        self.cancel = threading.Event()
        self.updated = time.time()

    def to_dict(self) -> Dict[str, Any]:
        percent = round(self.downloaded * 100 / self.total, 1) if self.total else None
        return {
            "name": self.name,
            "status": self.status,
            "downloaded": self.downloaded,
            "total": self.total,
            "percent": percent,
            "speed": round(self.speed),
            "error": self.error,
            "path": str(self.path),
        }


class Downloader:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._workers = 0

    def _pool(self) -> ThreadPoolExecutor:
        workers = get_settings().max_parallel_downloads
        if self._executor is None or workers != self._workers:
            self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="download")
            self._workers = workers
        return self._executor

    def job(self, name: str) -> Optional[Dict[str, Any]]:
        j = self._jobs.get(name)
        return j.to_dict() if j else None

    def active_jobs(self) -> Dict[str, Dict[str, Any]]:
        return {n: j.to_dict() for n, j in self._jobs.items()}

    def is_active(self, name: str) -> bool:
        j = self._jobs.get(name)
        return bool(j and j.status in ("queued", "downloading"))

    def start(self, name: str, requested_name: Optional[str] = None) -> Dict[str, Any]:
        entry = registry.get(name)
        if entry is None:
            raise RegistryError(f"Model '{name}' is not in the model list.")
        if not entry.get("url"):
            raise RegistryError(f"Model '{entry['name']}' has no download URL. Add one first.")
        path = registry.resolve_path(entry, requested_name)
        key = requested_name or entry["name"]
        with self._lock:
            current = self._jobs.get(key)
            if current and current.status in ("queued", "downloading"):
                return current.to_dict()
            job = Job(key, path, entry["url"])
            self._jobs[key] = job
        if path.is_file() and path.stat().st_size > 0:
            job.status = "done"
            job.downloaded = job.total = path.stat().st_size
            self._publish(job)
            return job.to_dict()
        self._publish(job)
        self._pool().submit(self._run, job)
        return job.to_dict()

    def cancel(self, name: str) -> Dict[str, Any]:
        j = self._jobs.get(name)
        if j is None:
            raise RegistryError(f"No download running for '{name}'.")
        j.cancel.set()
        if j.status == "queued":
            j.status = "cancelled"
            self._publish(j)
        return j.to_dict()

    # ---------------------------------------------------------------- worker
    @staticmethod
    def _prepare_request(url: str):
        settings = get_settings()
        headers = {"User-Agent": "AI-Hunters-ComfyFlow/1.0"}
        host = (urlparse(url).hostname or "").lower()
        if settings.hf_token and host.endswith("huggingface.co"):
            headers["Authorization"] = f"Bearer {settings.hf_token}"
        if settings.civitai_token and host.endswith("civitai.com"):
            parts = urlparse(url)
            query = dict(parse_qsl(parts.query))
            query.setdefault("token", settings.civitai_token)
            url = urlunparse(parts._replace(query=urlencode(query)))
        return url, headers

    def _publish(self, job: Job) -> None:
        job.updated = time.time()
        bus.publish({"type": "download", **job.to_dict()})

    def _run(self, job: Job) -> None:
        if job.cancel.is_set():
            job.status = "cancelled"
            self._publish(job)
            return
        part = job.path.with_name(job.path.name + ".part")
        try:
            job.path.parent.mkdir(parents=True, exist_ok=True)
            url, headers = self._prepare_request(job.url)
            offset = part.stat().st_size if part.exists() else 0
            if offset:
                headers["Range"] = f"bytes={offset}-"
            job.status = "downloading"
            self._publish(job)
            with requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=(20, 120)) as r:
                if r.status_code == 416:  # range not satisfiable: part already complete
                    offset = 0
                    part.unlink(missing_ok=True)
                    raise DownloadError("Partial file was invalid; please retry the download.")
                if r.status_code in (401, 403):
                    raise DownloadError(
                        f"Access denied (HTTP {r.status_code}). This model may need a Hugging Face or "
                        "Civitai token (Settings) or accepting its licence on the website."
                    )
                r.raise_for_status()
                ctype = r.headers.get("content-type", "")
                if "text/html" in ctype:
                    raise DownloadError("The URL returned a web page, not a model file. Use the direct download link.")
                if r.status_code != 206 and offset:
                    offset = 0  # server ignored Range: start over
                length = int(r.headers.get("content-length") or 0)
                job.total = offset + length if length else 0
                job.downloaded = offset
                mode = "ab" if offset else "wb"
                last_pub, last_bytes, last_t = 0.0, job.downloaded, time.time()
                with open(part, mode) as f:
                    for chunk in r.iter_content(chunk_size=CHUNK):
                        if job.cancel.is_set():
                            job.status = "cancelled"
                            self._publish(job)
                            return
                        if not chunk:
                            continue
                        f.write(chunk)
                        job.downloaded += len(chunk)
                        now = time.time()
                        if now - last_pub >= PUBLISH_EVERY:
                            job.speed = (job.downloaded - last_bytes) / max(now - last_t, 1e-6)
                            last_bytes, last_t, last_pub = job.downloaded, now, now
                            self._publish(job)
            if job.total and job.downloaded < job.total:
                raise DownloadError("Download ended early; press Download again to resume.")
            os.replace(part, job.path)
            job.status = "done"
            job.total = job.total or job.downloaded
            self._publish(job)
        except (requests.RequestException, OSError, DownloadError) as e:
            job.status = "error"
            job.error = str(e)
            self._publish(job)


downloader = Downloader()
