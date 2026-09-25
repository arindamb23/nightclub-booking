"""Workflow runs: execute on ComfyUI in a worker thread and keep results on disk."""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import random
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings, replace_with_retry
from app.events import bus
from app.services import comfy, workflows
from cb2c_py.lib.workflow_runner import ComfyUIError, WorkflowCancelled

MAX_SEED = 2**50
MEDIA_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".webm", ".mov", ".mkv", ".avi",
              ".wav", ".mp3", ".flac", ".ogg", ".m4a"}


class RunError(ValueError):
    pass


class ModelsMissing(RunError):
    """Some models have no usable URL/path: the UI asks the user for them."""

    def __init__(self, models: List[Dict[str, Any]]):
        super().__init__(
            f"{len(models)} model(s) cannot be downloaded automatically. "
            "Enter a download URL or the path of the file on this computer."
        )
        self.models = models


def _model_brief(r: Dict[str, Any]) -> Dict[str, Any]:
    job = r.get("job") or {}
    return {
        "name": r["name"],
        "category": r["category"],
        "url": r.get("url", ""),
        "status": r["status"],
        "error": job.get("error", "") if r["status"] == "error" else "",
        "used_by": r.get("used_by", []),
        "resolved_dir": r.get("resolved_dir", ""),
    }


def _runs_dir() -> Path:
    p = get_settings().data_dir / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def outputs_dir(run_id: str) -> Path:
    return get_settings().data_dir / "outputs" / run_id


def uploads_dir() -> Path:
    p = get_settings().data_dir / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _check_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", run_id or ""):
        raise RunError("Invalid run id.")
    return run_id


class PreviewStore:
    """Latest live preview frame per run (kept in memory only)."""

    def __init__(self) -> None:
        self._frames: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    def put(self, run_id: str, image: bytes, mime: str) -> None:
        if not image:
            return
        with self._lock:
            n = self._frames.get(run_id, (b"", "", 0))[2] + 1
            self._frames[run_id] = (image, mime, n)
            if len(self._frames) > 20:  # forget old runs
                self._frames.pop(next(iter(self._frames)))

    def get(self, run_id: str):
        return self._frames.get(run_id)

    def count(self, run_id: str) -> int:
        f = self._frames.get(run_id)
        return f[2] if f else 0


previews = PreviewStore()


class RunManager:
    def __init__(self) -> None:
        self._cancel: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ storage
    def _path(self, run_id: str) -> Path:
        return _runs_dir() / f"{_check_run_id(run_id)}.json"

    def _save(self, run: Dict[str, Any]) -> None:
        # atomic: readers (Results page, API polling) never see a half-written file
        path = self._path(run["id"])
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(run, indent=2), encoding="utf-8")
        replace_with_retry(tmp, path)

    def get(self, run_id: str) -> Dict[str, Any]:
        p = self._path(run_id)
        if not p.exists():
            raise RunError(f"Run '{run_id}' not found.")
        return json.loads(p.read_text(encoding="utf-8"))

    def list(self, workflow_id: Optional[str] = None, template_id: Optional[str] = None) -> List[Dict[str, Any]]:
        runs = []
        for p in _runs_dir().glob("*.json"):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if workflow_id and r.get("workflow_id") != workflow_id:
                continue
            if template_id and r.get("template_id") != template_id:
                continue
            runs.append(r)
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return runs

    def delete(self, run_id: str) -> None:
        run = self.get(run_id)
        if run["status"] in ("queued", "running"):
            raise RunError("Cancel the run before deleting it.")
        shutil.rmtree(outputs_dir(run_id), ignore_errors=True)
        self._path(run_id).unlink(missing_ok=True)

    def file_path(self, run_id: str, filename: str) -> Path:
        run = self.get(run_id)
        names = {o["filename"] for o in run.get("outputs", [])}
        if filename not in names:
            raise RunError("File not found in this run.")
        return outputs_dir(run_id) / filename

    def zip_bytes(self, run_id: str) -> bytes:
        run = self.get(run_id)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for o in run.get("outputs", []):
                p = outputs_dir(run_id) / o["filename"]
                if p.exists():
                    z.write(p, o["filename"])
        return buf.getvalue()

    # ------------------------------------------------------------ running
    def start(self, workflow_id: str, overrides: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        meta = workflows.get(workflow_id)
        rows = workflows.detect_models(workflow_id)
        return self._launch(
            {"workflow_id": workflow_id, "workflow_name": meta["name"], "overrides": overrides},
            rows, meta["node_count"],
        )

    def start_template(self, template_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
        """Runs a Python template (text/image to image/video) with the form values."""
        from app.services import templates

        t = templates.get(template_id)
        templates.build(template_id, values)  # validates the inputs before anything is queued
        rows = templates.detect_models(template_id, values)
        return self._launch(
            {"workflow_id": None, "template_id": template_id, "template_values": values,
             "workflow_name": t["name"], "task": t["task"], "overrides": {}},
            rows, 0,
        )

    def _detect(self, run: Dict[str, Any]) -> List[Dict[str, Any]]:
        if run.get("template_id"):
            from app.services import templates

            return templates.detect_models(run["template_id"], run.get("template_values") or {}, register=False)
        return workflows.detect_models(run["workflow_id"], register=False)

    def _launch(self, source: Dict[str, Any], rows: List[Dict[str, Any]], node_count: int) -> Dict[str, Any]:
        need_input = [_model_brief(r) for r in rows if r["status"] in ("no_url", "error")]
        if need_input:
            raise ModelsMissing(need_input)
        if not comfy.status()["reachable"]:
            raise RunError(
                "ComfyUI is not running. Start it from Settings or with Start-all.bat, then try again."
            )
        pending = [r for r in rows if r["status"] != "ready"]
        for r in pending:
            if r["status"] == "missing":
                workflows.downloader.start(r["registry_name"], r["name"])
        run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]
        run = {
            "id": run_id,
            **source,
            "status": "preparing" if pending else "queued",
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            "finished_at": None,
            "duration": None,
            "progress": {"node": None, "class_type": None, "value": 0, "max": 0, "done": 0, "total": node_count,
                         "models": None},
            "outputs": [],
            "error": None,
            "error_code": None,
            "error_details": [],
            "failed_models": [],
        }
        self._save(run)
        cancel = threading.Event()
        with self._lock:
            self._cancel[run_id] = cancel
        threading.Thread(target=self._execute, args=(run, cancel), daemon=True, name=f"run-{run_id}").start()
        self._publish(run)
        return run

    def _prepare_models(self, run: Dict[str, Any], cancel: threading.Event) -> None:
        """Waits until every model of the workflow is on disk (downloads were started in start())."""
        last_pub = 0.0
        while True:
            if cancel.is_set():
                raise WorkflowCancelled("Run cancelled")
            rows = self._detect(run)
            failed = [_model_brief(r) for r in rows if r["status"] in ("error", "no_url")]
            if failed:
                raise ModelsMissing(failed)
            for r in rows:  # restart a download that stopped (e.g. cancelled in the Models page)
                if r["status"] == "missing":
                    workflows.downloader.start(r["registry_name"], r["name"])
            ready = sum(1 for r in rows if r["status"] == "ready")
            run["progress"]["models"] = {
                "ready": ready,
                "total": len(rows),
                "items": [
                    {"name": r["name"], "status": r["status"], "percent": (r.get("job") or {}).get("percent")}
                    for r in rows
                ],
            }
            if ready == len(rows):
                return
            if time.time() - last_pub > 1.0:
                last_pub = time.time()
                self._publish(run)
            time.sleep(1.0)

    def _watch(self, run: Dict[str, Any], finished: threading.Event) -> None:
        """While a run is in ComfyUI: GPU/RAM usage, and why it has not started (queued behind another job)."""
        prog = run["progress"]
        while not finished.wait(2.0):
            changed = False
            st = comfy.stats()
            if st and st != prog.get("resources"):
                prog["resources"] = st
                changed = True
            pid = run.get("comfy_prompt_id")
            if pid and prog.get("node") is None:
                q = comfy.queue()
                if q is not None:
                    running_ids = [p for _, p in q["running"]]
                    mine = next((n for n, p in q["pending"] if p == pid), None)
                    if pid in running_ids:
                        ahead, phase = 0, "ComfyUI is preparing the workflow"
                    elif mine is not None:
                        ahead = len(running_ids) + sum(1 for n, p in q["pending"] if n < mine)
                        phase = (f"Waiting in the ComfyUI queue: {ahead} job(s) ahead"
                                 + (" (another workflow is still running in ComfyUI)" if running_ids else ""))
                    else:
                        ahead, phase = 0, prog.get("phase") or ""
                    if (ahead, phase) != (prog.get("queue_ahead"), prog.get("phase")):
                        prog["queue_ahead"], prog["phase"] = ahead, phase
                        changed = True
            if changed and not finished.is_set():
                self._publish(run)

    def cancel(self, run_id: str) -> Dict[str, Any]:
        ev = self._cancel.get(run_id)
        if ev is None:
            raise RunError("This run is not active.")
        ev.set()
        return self.get(run_id)

    @staticmethod
    def _publish(run: Dict[str, Any]) -> None:
        bus.publish({"type": "run", "run": {k: v for k, v in run.items() if k != "overrides"}})

    def _apply_overrides(self, wf, overrides: Dict[str, Dict[str, Any]], runner) -> None:
        for node_id, values in (overrides or {}).items():
            if str(node_id) not in wf.nodes:
                continue
            node = wf.get_node(node_id)
            for input_name, value in (values or {}).items():
                if isinstance(value, dict) and value.get("upload"):
                    local = uploads_dir() / Path(value["upload"]).name
                    if not local.exists():
                        raise RunError(f"Uploaded file '{value['upload']}' is missing; upload it again.")
                    value = runner.upload_file(str(local))
                elif isinstance(value, dict) and value.get("random_seed"):
                    value = random.randint(0, MAX_SEED)
                node.set_input(input_name, value)

    @staticmethod
    def _upload_local_media(wf, runner) -> None:
        """Any input that is a path to an image/video on this PC is uploaded to ComfyUI's input folder."""
        for node in wf.get_nodes():
            for name, value in list(node.input_values.items()):
                if (
                    isinstance(value, str)
                    and os.path.isabs(value)
                    and Path(value).suffix.lower() in MEDIA_EXTS
                    and os.path.isfile(value)
                ):
                    node.input_values[name] = runner.upload_file(value)

    def _execute(self, run: Dict[str, Any], cancel: threading.Event) -> None:
        started = time.time()
        runner = comfy.runner()
        executed: set = set()
        finished = threading.Event()

        prog = run["progress"]
        prog.setdefault("nodes", {})  # node id -> {"state": running|done|cached|error, "started", "ended"}
        prog.setdefault("phase", "")

        def mark(nid: str, state: str) -> None:
            entry = prog["nodes"].setdefault(nid, {"order": len(prog["nodes"]) + 1})
            now = round(time.time(), 3)
            if state == "running":
                entry["started"] = now
            elif entry.get("state") == "running" or state in ("cached", "error"):
                entry["ended"] = now
            entry["state"] = state

        def finish_running() -> None:
            for nid, entry in prog["nodes"].items():
                if entry.get("state") == "running":
                    mark(nid, "done")

        def on_message(message: Dict[str, Any]) -> None:
            mtype = message.get("type")
            data = message.get("data") or {}
            if mtype == "preview_image":  # binary latent preview frame from ComfyUI
                previews.put(run["id"], data.get("image") or b"", data.get("mime") or "image/jpeg")
                bus.publish({"type": "run_preview", "run_id": run["id"], "node": prog.get("node"), "n": previews.count(run["id"])})
                return
            prog["last_event"] = round(time.time(), 1)
            if mtype == "prompt_queued":
                run["comfy_prompt_id"] = data.get("prompt_id")
                prog["phase"] = "Queued in ComfyUI"
                self._publish(run)
                return
            if mtype == "status":
                remaining = ((data.get("status") or {}).get("exec_info") or {}).get("queue_remaining")
                if prog["node"] is None and remaining:
                    prog["phase"] = f"Queued in ComfyUI ({remaining} job(s) in the queue)"
                else:
                    return
            elif mtype == "execution_start":
                prog["phase"] = "ComfyUI started the workflow"
            elif mtype == "executing" and data.get("node") is not None:
                nid = str(data["node"])
                finish_running()
                executed.add(nid)
                mark(nid, "running")
                prog["node"] = nid
                node = wf.nodes.get(nid)
                prog["class_type"] = node._original_name if node is not None else None
                prog["value"], prog["max"] = 0, 0
                prog["phase"] = ""
            elif mtype == "executing":  # node None: the prompt is finished
                finish_running()
            elif mtype == "execution_cached":
                for n in data.get("nodes") or []:
                    executed.add(str(n))
                    mark(str(n), "cached")
            elif mtype == "executed" and data.get("node") is not None:
                executed.add(str(data["node"]))
                if prog["nodes"].get(str(data["node"]), {}).get("state") == "running":
                    mark(str(data["node"]), "done")
            elif mtype == "execution_error" and data.get("node_id") is not None:
                mark(str(data["node_id"]), "error")
            elif mtype == "progress":
                prog["value"], prog["max"] = data.get("value", 0), data.get("max", 0)
            else:
                return
            prog["done"] = min(len(executed), prog["total"])
            self._publish(run)

        try:
            if run["status"] == "preparing":
                self._save(run)
                self._prepare_models(run, cancel)
                run["status"] = "queued"
                self._publish(run)
            if run.get("template_id"):
                from app.services import templates

                wf = templates.build(run["template_id"], run.get("template_values") or {})
            else:
                wf = workflows.build(run["workflow_id"])
            run["progress"]["total"] = len(wf.nodes)
            prog["phase"] = "Uploading input files to ComfyUI"
            self._apply_overrides(wf, run["overrides"], runner)
            self._upload_local_media(wf, runner)
            prog["phase"] = "Sending the workflow to ComfyUI"
            run["status"] = "running"
            self._save(run)
            self._publish(run)
            threading.Thread(target=self._watch, args=(run, finished), daemon=True, name=f"watch-{run['id']}").start()
            outputs = runner.run_workflow(
                wf,
                progress_callback=on_message,
                output_dir=str(outputs_dir(run["id"])),
                cancel_event=cancel,
            )
            run["outputs"] = [
                {k: o[k] for k in ("filename", "kind", "size", "node_id", "type")} for o in outputs
            ]
            run["status"] = "succeeded"
            finish_running()
            run["progress"]["done"] = run["progress"]["total"]
            if not outputs:
                run["error"] = "The workflow finished but produced no output files (add a Save/Preview node)."
        except WorkflowCancelled:
            run["status"] = "cancelled"
        except ModelsMissing as e:
            run["status"] = "failed"
            run["error"] = "Some models could not be downloaded. Enter the correct URL or file path and run again."
            run["error_code"] = "models_missing"
            run["failed_models"] = e.models
            run["error_details"] = [f"{m['name']}: {m['error'] or 'no download URL'}" for m in e.models]
        except ComfyUIError as e:
            run["status"] = "failed"
            run["error"] = e.args[0] if e.args else str(e)
            run["error_details"] = e.details
        except (workflows.WorkflowError, RunError, ValueError) as e:
            run["status"] = "failed"
            run["error"] = str(e)
        except Exception as e:  # noqa: BLE001 - never leave a run hanging
            run["status"] = "failed"
            run["error"] = f"{type(e).__name__}: {e}"
        finally:
            finished.set()
            prog["phase"] = ""
            if run["status"] != "succeeded":
                for entry in prog["nodes"].values():
                    if entry.get("state") == "running":
                        entry["state"] = "error" if run["status"] == "failed" else "stopped"
                        entry["ended"] = round(time.time(), 2)
            run["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
            run["duration"] = round(time.time() - started, 1)
            self._save(run)
            self._publish(run)
            if run.get("workflow_id"):
                workflows.record_run(run["workflow_id"], run["id"], run["status"])
            with self._lock:
                self._cancel.pop(run["id"], None)


runs = RunManager()
