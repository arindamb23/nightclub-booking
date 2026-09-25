# AI Hunters ComfyFlow - cb2c_py/lib/workflow_runner.py
"""Executes workflows on a ComfyUI server through its HTTP + WebSocket API."""

import json
import os
import time
import uuid
import threading
from pathlib import Path
from typing import Callable, Optional, Dict, Any, List

import requests
import websocket

from cb2c_py.lib.workflow_interface import WorkflowInterface

DEFAULT_COMFYUI_SERVER_ADDRESS = "127.0.0.1:8188"
DEBUG_JSON_WORKFLOW = os.getenv("DEBUG_JSON_WORKFLOW", "false").lower() == "true"

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".apng"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v"}
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def file_kind(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    return "file"


class ComfyUIError(Exception):
    """Raised when ComfyUI rejects or fails a workflow. ``details`` is a list of strings."""

    def __init__(self, message: str, details: Optional[List[str]] = None):
        super().__init__(message)
        self.details = details or []

    def __str__(self):
        base = super().__str__()
        return base + ("\n" + "\n".join(self.details) if self.details else "")


class WorkflowCancelled(Exception):
    """Raised when a run is cancelled or interrupted."""


class WorkflowRunner:
    """Queue a workflow, stream its progress and download its outputs."""

    def __init__(
        self,
        comfyui_server_address: Optional[str] = None,
        http_timeout: float = 30.0,
        max_duration: Optional[float] = None,
    ):
        self.comfyui_server_address = (
            comfyui_server_address
            or os.getenv("COMFYUI_SERVER_ADDRESS")
            or DEFAULT_COMFYUI_SERVER_ADDRESS
        )
        self.http_timeout = http_timeout
        self.max_duration = max_duration

    # ---------------------------------------------------------------- helpers
    @property
    def base_url(self) -> str:
        return f"http://{self.comfyui_server_address}"

    def is_available(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/system_stats", timeout=3).ok
        except requests.RequestException:
            return False

    def system_stats(self) -> Dict[str, Any]:
        r = requests.get(f"{self.base_url}/system_stats", timeout=self.http_timeout)
        r.raise_for_status()
        return r.json()

    def object_info(self) -> Dict[str, Any]:
        r = requests.get(f"{self.base_url}/object_info", timeout=120)
        r.raise_for_status()
        return r.json()

    def interrupt(self) -> None:
        try:
            requests.post(f"{self.base_url}/interrupt", timeout=self.http_timeout)
        except requests.RequestException:
            pass

    def cancel_prompt(self, prompt_id: str) -> None:
        """Cancels one job: removes it from ComfyUI's queue, or interrupts it only if it is the one running."""
        try:
            requests.post(f"{self.base_url}/queue", json={"delete": [prompt_id]}, timeout=self.http_timeout)
            running = requests.get(f"{self.base_url}/queue", timeout=self.http_timeout).json().get("queue_running") or []
            if any(isinstance(it, list) and len(it) > 1 and it[1] == prompt_id for it in running):
                self.interrupt()
        except (requests.RequestException, ValueError):
            self.interrupt()

    def upload_file(self, file_path: str, subfolder: str = "") -> str:
        """Uploads an image/video to ComfyUI's input folder; returns the name to use."""
        with open(file_path, "rb") as f:
            files = {"image": (os.path.basename(file_path), f)}
            data = {"overwrite": "true"}
            if subfolder:
                data["subfolder"] = subfolder
            r = requests.post(f"{self.base_url}/upload/image", files=files, data=data, timeout=300)
        r.raise_for_status()
        info = r.json()
        name = info["name"]
        return f"{info['subfolder']}/{name}" if info.get("subfolder") else name

    # kept for backwards compatibility
    def _upload_file(self, file_path: str) -> Dict[str, Any]:
        return {"name": self.upload_file(file_path)}

    def _queue_prompt(self, prompt: Dict[str, Any], client_id: str) -> Dict[str, Any]:
        workflow_data = prompt.get("prompt", prompt)
        payload = {"prompt": workflow_data, "client_id": client_id}
        try:
            r = requests.post(f"{self.base_url}/prompt", json=payload, timeout=self.http_timeout)
        except requests.RequestException as e:
            raise ComfyUIError(f"Cannot reach ComfyUI at {self.base_url}: {e}") from e
        if r.ok:
            return r.json()
        details: List[str] = []
        message = f"ComfyUI rejected the workflow (HTTP {r.status_code})"
        try:
            data = r.json()
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                message = err["message"] + (f": {err['details']}" if err.get("details") else "")
            for node_id, node_error in (data.get("node_errors") or {}).items():
                class_type = node_error.get("class_type", "Unknown node")
                for e in node_error.get("errors", []):
                    input_name = (e.get("extra_info") or {}).get("input_name", "")
                    where = f" input '{input_name}'" if input_name else ""
                    details.append(
                        f"Node {class_type} (ID {node_id}){where}: {e.get('details') or e.get('message')}"
                    )
        except ValueError:
            details.append(r.text[:500])
        raise ComfyUIError(message, details)

    def _get_file(self, filename: str, subfolder: str, folder_type: str) -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        r = requests.get(f"{self.base_url}/view", params=params, timeout=300)
        r.raise_for_status()
        return r.content

    def _get_history(self, prompt_id: str) -> Dict[str, Any]:
        r = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=self.http_timeout)
        r.raise_for_status()
        return r.json()

    def _wait_for_history(self, prompt_id: str, timeout: float = 30.0) -> Dict[str, Any]:
        """ComfyUI sends ``execution_success`` *before* it stores the history entry: poll until it is there."""
        deadline = time.time() + timeout
        entry: Dict[str, Any] = {}
        while True:
            try:
                entry = self._get_history(prompt_id).get(prompt_id) or {}
            except requests.RequestException:
                entry = {}
            if entry:  # ComfyUI stores the entry once, complete with outputs and status
                return entry
            if time.time() >= deadline:
                return entry
            time.sleep(0.5)

    @staticmethod
    def collect_output_refs(history_entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Returns unique file references from a history entry, in node order."""
        refs, seen = [], set()
        for node_id, node_output in (history_entry.get("outputs") or {}).items():
            animated_flags = node_output.get("animated") or []
            animated = any(bool(a) for a in animated_flags) if isinstance(animated_flags, list) else bool(animated_flags)
            for key, items in node_output.items():
                if not isinstance(items, list) or key == "animated":
                    continue
                for item in items:
                    if not isinstance(item, dict) or "filename" not in item:
                        continue
                    ident = (item["filename"], item.get("subfolder", ""), item.get("type", "output"))
                    if ident in seen:
                        continue
                    seen.add(ident)
                    kind = file_kind(item["filename"])
                    if kind == "image" and (key == "gifs" or animated):
                        kind = "animation"
                    refs.append(
                        {
                            "node_id": node_id,
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                            "kind": kind,
                        }
                    )
        return refs

    # --------------------------------------------------------------- running
    @staticmethod
    def _decode_preview(frame: bytes) -> Optional[Dict[str, Any]]:
        """Decodes a ComfyUI binary WebSocket frame (live latent preview) into ``{image, mime}``."""
        if not isinstance(frame, (bytes, bytearray)) or len(frame) < 8:
            return None
        event = int.from_bytes(frame[0:4], "big")
        if event == 1:  # PREVIEW_IMAGE: [event][image type 1=jpeg 2=png][bytes]
            kind = int.from_bytes(frame[4:8], "big")
            return {"image": bytes(frame[8:]), "mime": "image/png" if kind == 2 else "image/jpeg"}
        if event == 4:  # PREVIEW_IMAGE_WITH_METADATA: [event][metadata length][json][bytes]
            size = int.from_bytes(frame[4:8], "big")
            try:
                meta = json.loads(frame[8:8 + size].decode("utf-8"))
            except ValueError:
                meta = {}
            return {"image": bytes(frame[8 + size:]), "mime": meta.get("image_type") or "image/jpeg"}
        return None

    def _wait_for_completion(
        self,
        ws: websocket.WebSocket,
        prompt_id: str,
        progress_callback: ProgressCallback,
        cancel_event: Optional[threading.Event],
        ws_outputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        started = time.time()
        ws.settimeout(1.0)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                self.cancel_prompt(prompt_id)  # never stops another workflow that happens to be running
                raise WorkflowCancelled("Run cancelled")
            if self.max_duration and time.time() - started > self.max_duration:
                self.interrupt()
                raise ComfyUIError(f"Run exceeded {self.max_duration:.0f}s and was stopped")
            try:
                out = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except websocket.WebSocketConnectionClosedException as e:
                raise ComfyUIError("Connection to ComfyUI was closed during the run") from e
            if not isinstance(out, str):
                preview = self._decode_preview(out)
                if preview and progress_callback:
                    progress_callback({"type": "preview_image", "data": preview})
                continue
            message = json.loads(out)
            data = message.get("data") or {}
            if data.get("prompt_id") not in (None, prompt_id):
                continue
            if progress_callback:
                progress_callback(message)
            mtype = message.get("type")
            if mtype == "executed" and ws_outputs is not None and data.get("node") is not None:
                ws_outputs[str(data["node"])] = data.get("output") or {}
            if mtype == "execution_error":
                raise ComfyUIError(
                    f"{data.get('node_type', 'A node')} (ID {data.get('node_id')}) failed: "
                    f"{data.get('exception_type', '')} {data.get('exception_message', '')}".strip()
                )
            if mtype == "execution_interrupted":
                raise WorkflowCancelled("Run interrupted in ComfyUI")
            if mtype == "execution_success":
                return
            if mtype == "executing" and data.get("node") is None and data.get("prompt_id") == prompt_id:
                return

    def _get_outputs(
        self,
        ws: websocket.WebSocket,
        prompt: Dict[str, Any],
        client_id: str,
        progress_callback: ProgressCallback = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        """Queues ``prompt`` and yields ``(bytes, filename, ref)`` for every output file."""
        prompt_id = self._queue_prompt(prompt, client_id)["prompt_id"]
        if progress_callback:
            progress_callback({"type": "prompt_queued", "data": {"prompt_id": prompt_id}})
        ws_outputs: Dict[str, Any] = {}
        self._wait_for_completion(ws, prompt_id, progress_callback, cancel_event, ws_outputs)
        history = self._wait_for_history(prompt_id)
        refs = self.collect_output_refs(history)
        if not refs and ws_outputs:  # history had no outputs: use the ones ComfyUI sent over the WebSocket
            refs = self.collect_output_refs({"outputs": ws_outputs})
        for ref in refs:
            data = self._get_file(ref["filename"], ref["subfolder"], ref["type"])
            yield data, ref["filename"], ref

    def run_workflow(
        self,
        workflow: WorkflowInterface,
        progress_callback: ProgressCallback = None,
        output_dir: str = "outputs",
        cancel_event: Optional[threading.Event] = None,
    ) -> List[Dict[str, Any]]:
        """Runs the workflow, saves outputs into ``output_dir`` and returns their metadata."""
        if DEBUG_JSON_WORKFLOW:  # dry run: print the API JSON, contact nothing
            print(json.dumps({"prompt": workflow.to_prompt()}, indent=2))
            return []
        for node in workflow.get_nodes():
            props = node.__dict__.get("_properties", {})
            if props.get("upload") is True:
                value = node.input_values.get("image")
                if isinstance(value, str) and os.path.isfile(value):
                    node.input_values["image"] = self.upload_file(value)

        prompt = workflow.to_prompt()

        client_id = str(uuid.uuid4())
        ws = websocket.WebSocket()
        try:
            ws.connect(f"ws://{self.comfyui_server_address}/ws?clientId={client_id}", timeout=10)
        except Exception as e:  # noqa: BLE001 - surface a readable error
            raise ComfyUIError(f"Cannot open ComfyUI WebSocket at {self.comfyui_server_address}: {e}") from e

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        saved: List[Dict[str, Any]] = []
        try:
            for data, filename, ref in self._get_outputs(ws, prompt, client_id, progress_callback, cancel_event):
                target = out_dir / filename
                stem, suffix, n = target.stem, target.suffix, 1
                while target.exists():
                    target = out_dir / f"{stem}_{n}{suffix}"
                    n += 1
                target.write_bytes(data)
                saved.append({**ref, "filename": target.name, "path": str(target), "size": len(data)})
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        return saved
