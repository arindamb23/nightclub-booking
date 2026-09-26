"""Background model downloads with resume, progress events and cancellation."""
from __future__ import annotations

import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlencode, parse_qsl, urlunparse

import requests

from app.config import get_settings, replace_with_retry
from app.events import bus
from app.services.registry import registry, RegistryError, is_local_source, local_source_path

CHUNK = 256 * 1024  # small chunks: a dropped connection loses at most this much
PUBLISH_EVERY = 0.5


MAX_STALLED_RETRIES = 6  # attempts in a row without any new bytes before giving up
RETRY_DELAY_SCALE = 1.0  # tests shrink the back-off


REPO_PREFIX = "repo:"
HF_BASE = os.environ.get("COMFYFLOW_HF_BASE", "https://huggingface.co")  # tests point this at a local server


class _Cancelled(Exception):
    pass


def repo_key(repo: str, target: Path) -> str:
    """Download key of a repository: repo:<target folder>|<owner/name>."""
    return f"{REPO_PREFIX}{target}|{repo}"


def parse_repo_key(key: str):
    target, _, repo = key[len(REPO_PREFIX):].rpartition("|")
    return repo, Path(target)


def repo_ready(target: Path) -> bool:
    return target.is_dir() and any(p.is_file() and p.stat().st_size > 0 for p in target.rglob("*"))


class DownloadError(RuntimeError):
    """Transient problem: retried automatically."""


class PermanentDownloadError(DownloadError):
    """Retrying cannot help (access denied, not found, web page instead of a file)."""


def _gb(n: int) -> str:
    return f"{n / 1024**3:.2f} GB" if n >= 1024**3 else f"{n / 1024**2:.0f} MB"


def _short(e: Exception) -> str:
    text = str(e)
    if "IncompleteRead" in text or "Connection broken" in text:
        return "the server closed the connection"
    if "timed out" in text.lower():
        return "the connection timed out"
    return text[:160]


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
        self.note = ""  # e.g. "Connection dropped at 1.20 GB — resuming in 4s"
        self.attempt = 0
        self.cancel = threading.Event()
        self.updated = time.time()
        self.parent: Optional["Job"] = None  # set for one file of a repository download
        self.base = 0
        self.file_note = ""
        self.repo = ""

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
            "note": self.note,
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
        if name.startswith(REPO_PREFIX):
            return self.start_repo(name)
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
        ahead = sum(1 for j in self._jobs.values() if j is not job and j.status in ("queued", "downloading"))
        workers = get_settings().max_parallel_downloads
        if ahead >= workers:
            job.note = (f"Waiting in the queue ({ahead} ahead) — models download one at a time"
                        if workers == 1 else f"Waiting in the queue ({ahead} ahead, {workers} at a time)")
        self._publish(job)
        self._pool().submit(self._run, job)
        return job.to_dict()

    def clear(self, *names: str) -> None:
        """Forgets finished/failed jobs (called when a model's URL or path changes)."""
        with self._lock:
            for n in names:
                j = self._jobs.get(n)
                if j and j.status not in ("queued", "downloading"):
                    del self._jobs[n]

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
        parent = getattr(job, "parent", None)
        if parent is not None:  # one file of a repository: report it as progress of the whole repository
            parent.downloaded = parent.base + job.downloaded
            parent.speed = job.speed
            parent.note = job.note or parent.file_note
            job = parent
        job.updated = time.time()
        bus.publish({"type": "download", **job.to_dict()})

    # ---------------------------------------------------------------- Hugging Face repositories
    def start_repo(self, key: str) -> Dict[str, Any]:
        """Downloads a whole Hugging Face repository (models some nodes load by repo id, e.g. a text-encoder LLM)."""
        repo, target = parse_repo_key(key)
        with self._lock:
            current = self._jobs.get(key)
            if current and current.status in ("queued", "downloading"):
                return current.to_dict()
            job = Job(key, target, f"{HF_BASE}/{repo}")
            job.repo = repo
            self._jobs[key] = job
        if repo_ready(target):
            job.status = "done"
            self._publish(job)
            return job.to_dict()
        ahead = sum(1 for j in self._jobs.values() if j is not job and j.status in ("queued", "downloading"))
        if ahead >= get_settings().max_parallel_downloads:
            job.note = f"Waiting in the queue ({ahead} ahead) — models download one at a time"
        self._publish(job)
        self._pool().submit(self._run_repo, job)
        return job.to_dict()

    def _repo_files(self, repo: str) -> list:
        url, headers = self._prepare_request(f"{HF_BASE}/api/models/{repo}/tree/main?recursive=true")
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code in (401, 403):
            raise PermanentDownloadError(f"Access denied to {repo} (HTTP {r.status_code}). Add a Hugging Face token in Settings "
                                         "and accept the model's licence on its page.")
        if r.status_code == 404:
            raise PermanentDownloadError(f"Hugging Face repository '{repo}' was not found.")
        r.raise_for_status()
        files = []
        for item in r.json():
            if item.get("type") == "file":
                size = (item.get("lfs") or {}).get("size") or item.get("size") or 0
                files.append({"path": item["path"], "size": int(size)})
        if not files:
            raise PermanentDownloadError(f"Repository '{repo}' has no files.")
        return files

    def _run_repo(self, job: Job) -> None:
        tmp = job.path.with_name(job.path.name + ".partial")  # the node only checks that the folder exists
        try:
            if job.cancel.is_set():
                raise _Cancelled()
            job.status = "downloading"
            job.note = "Listing the repository files…"
            self._publish(job)
            files = self._repo_files(job.repo)
            job.total = sum(f["size"] for f in files)
            job.base = 0
            for i, f in enumerate(files, 1):
                dest = tmp.joinpath(*f["path"].split("/"))
                if dest.is_file() and (not f["size"] or dest.stat().st_size == f["size"]):
                    job.base += f["size"]
                    continue
                job.file_note = f"File {i}/{len(files)}: {f['path']}"
                sub = Job(job.name, dest, f"{HF_BASE}/{job.repo}/resolve/main/{f['path']}")
                sub.cancel = job.cancel
                sub.parent = job
                self._run(sub)
                if sub.status == "cancelled":
                    raise _Cancelled()
                if sub.status != "done":
                    raise PermanentDownloadError(f"{f['path']}: {sub.error}")
                job.base += dest.stat().st_size
            if job.path.exists():
                shutil.rmtree(job.path, ignore_errors=True)
            replace_with_retry(tmp, job.path)
            job.status, job.note, job.error = "done", "", ""
            job.downloaded = job.total = job.base
        except _Cancelled:
            job.status, job.note = "cancelled", ""
        except (requests.RequestException, OSError, DownloadError) as e:
            job.status, job.note = "error", ""
            job.error = str(e) if isinstance(e, DownloadError) else f"Could not download {job.repo}: {_short(e)}"
        self._publish(job)

    def _run(self, job: Job) -> None:
        """Downloads with automatic resume: dropped connections / timeouts retry from the bytes on disk."""
        if job.cancel.is_set():
            job.status = "cancelled"
            self._publish(job)
            return
        if is_local_source(job.url):
            self._copy_local(job)
            return
        part = job.path.with_name(job.path.name + ".part")
        failures = 0
        while True:
            before = part.stat().st_size if part.exists() else 0
            try:
                if self._attempt(job, part):
                    return  # done or cancelled
            except PermanentDownloadError as e:
                job.status = "error"
                job.error = str(e)
                job.note = ""
                self._publish(job)
                return
            except (requests.RequestException, OSError, DownloadError) as e:
                after = part.stat().st_size if part.exists() else 0
                failures = 0 if after > before else failures + 1  # progress resets the counter
                if failures >= MAX_STALLED_RETRIES:
                    job.status = "error"
                    saved = f" {_gb(after)} is saved and will be resumed." if after else ""
                    job.error = f"Download interrupted {failures} times in a row ({_short(e)}).{saved} Press Download to try again."
                    job.note = ""
                    self._publish(job)
                    return
                wait = min(30, 2 ** (failures + 1)) * RETRY_DELAY_SCALE
                job.attempt += 1
                job.note = f"Connection dropped at {_gb(after)} — resuming in {wait:.0f}s (attempt {job.attempt + 1})"
                self._publish(job)
                if job.cancel.wait(wait):
                    job.status = "cancelled"
                    job.note = ""
                    self._publish(job)
                    return

    def _attempt(self, job: Job, part: Path) -> bool:
        """One HTTP request. Returns True when finished (done/cancelled); raises to trigger a retry."""
        job.path.parent.mkdir(parents=True, exist_ok=True)
        url, headers = self._prepare_request(job.url)
        headers["Accept-Encoding"] = "identity"  # byte ranges must match the file on disk
        offset = part.stat().st_size if part.exists() else 0
        if offset:
            headers["Range"] = f"bytes={offset}-"
        job.status = "downloading"
        self._publish(job)
        with requests.get(url, headers=headers, stream=True, allow_redirects=True, timeout=(20, 120)) as r:
            if r.status_code == 416 and offset:
                # nothing left to fetch: the partial file is already complete (or larger than the file)
                size = self._remote_size(url, headers)
                if size and offset == size:
                    return self._finish(job, part, offset)
                part.unlink(missing_ok=True)
                raise DownloadError("The saved partial file did not match; starting over.")
            if r.status_code in (401, 403):
                raise PermanentDownloadError(
                    f"Access denied (HTTP {r.status_code}). This model may need a Hugging Face or "
                    "Civitai token (Settings) or accepting its licence on the website."
                )
            if r.status_code == 404:
                raise PermanentDownloadError(f"404 File not found at {job.url}. Check the download URL.")
            if 400 <= r.status_code < 500:
                raise PermanentDownloadError(f"The server refused the download (HTTP {r.status_code}).")
            r.raise_for_status()  # 5xx -> retried
            if "text/html" in r.headers.get("content-type", ""):
                raise PermanentDownloadError("The URL returned a web page, not a model file. Use the direct download link.")
            if r.status_code != 206 and offset:
                offset = 0  # server ignored Range: start over
            length = int(r.headers.get("content-length") or 0)
            job.total = offset + length if length else 0
            job.downloaded = offset
            job.note = ""
            last_pub, last_bytes, last_t = 0.0, job.downloaded, time.time()
            with open(part, "ab" if offset else "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK):
                    if job.cancel.is_set():
                        job.status = "cancelled"
                        self._publish(job)
                        return True
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
            raise DownloadError("the server closed the connection early")
        return self._finish(job, part, job.downloaded)

    def _finish(self, job: Job, part: Path, size: int) -> bool:
        replace_with_retry(part, job.path)
        job.status = "done"
        job.note = ""
        job.error = ""
        job.downloaded = size
        job.total = job.total or size
        self._publish(job)
        return True

    @staticmethod
    def _remote_size(url: str, headers: Dict[str, str]) -> int:
        h = {k: v for k, v in headers.items() if k.lower() != "range"}
        try:
            r = requests.head(url, headers=h, allow_redirects=True, timeout=20)
            return int(r.headers.get("content-length") or 0)
        except (requests.RequestException, ValueError):
            return 0

    def _copy_local(self, job: Job) -> None:
        """Model given as a local file: hard-link it (same drive, instant) or copy it."""
        part = job.path.with_name(job.path.name + ".part")
        try:
            src = local_source_path(job.url)
            if not src.is_file():
                raise DownloadError(f"Local model file not found: {src}")
            job.path.parent.mkdir(parents=True, exist_ok=True)
            job.total = src.stat().st_size
            job.status = "downloading"
            self._publish(job)
            if src.resolve() != job.path.resolve():
                try:
                    os.link(src, job.path)
                except OSError:
                    last = 0.0
                    with open(src, "rb") as fin, open(part, "wb") as fout:
                        while True:
                            if job.cancel.is_set():
                                job.status = "cancelled"
                                self._publish(job)
                                part.unlink(missing_ok=True)
                                return
                            chunk = fin.read(8 * CHUNK)
                            if not chunk:
                                break
                            fout.write(chunk)
                            job.downloaded += len(chunk)
                            if time.time() - last >= PUBLISH_EVERY:
                                last = time.time()
                                self._publish(job)
                    replace_with_retry(part, job.path)
            job.downloaded = job.total
            job.status = "done"
            self._publish(job)
        except (OSError, DownloadError) as e:
            part.unlink(missing_ok=True)
            job.status = "error"
            job.error = str(e)
            self._publish(job)


downloader = Downloader()
