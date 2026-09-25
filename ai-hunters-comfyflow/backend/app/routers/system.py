"""System, settings, ComfyUI control and the SSE event stream."""
import asyncio
import json

import requests

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Dict, Optional

from app import APP_NAME, APP_VERSION
from app.config import get_settings, update_env, ConfigError, EDITABLE_KEYS, SECRET_KEYS
from app.events import bus
from app.services import comfy
from app.services.registry import registry
from app.services.runs import runs
from app.services import workflows
from app.services.downloader import downloader

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/system")
def system():
    s = get_settings()
    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "backend_port": s.backend_port,
        "frontend_port": s.frontend_port,
        "comfyui": comfy.status(),
        "models_dir": str(s.models_dir),
        "data_dir": str(s.data_dir),
    }


@router.get("/dashboard")
def dashboard():
    models = registry.all()
    ready = sum(1 for m in models if registry.file_status(m)["exists"])
    wfs = workflows.list_all()
    all_runs = runs.list()
    return {
        "workflows": len(wfs),
        "models_total": len(models),
        "models_ready": ready,
        "models_no_url": sum(1 for m in models if not m.get("url")),
        "downloads_active": sum(1 for j in downloader.active_jobs().values() if j["status"] in ("queued", "downloading")),
        "runs_total": len(all_runs),
        "runs_succeeded": sum(1 for r in all_runs if r["status"] == "succeeded"),
        "recent_runs": all_runs[:5],
        "recent_workflows": wfs[:5],
        "comfyui": comfy.status(),
    }


class SettingsUpdate(BaseModel):
    values: Dict[str, str]


@router.get("/settings")
def read_settings():
    s = get_settings()
    return {"settings": s.public(), "editable": list(EDITABLE_KEYS)}


@router.put("/settings")
def write_settings(body: SettingsUpdate):
    values = {k: str(v).strip() for k, v in body.values.items()}
    # A masked secret coming back unchanged means "keep the current value".
    for key in SECRET_KEYS:
        if key in values and values[key].startswith("•"):
            values.pop(key)
    try:
        s = update_env(values)
    except ConfigError as e:
        raise HTTPException(400, str(e))
    comfy.write_extra_model_paths()
    return {"settings": s.public(), "editable": list(EDITABLE_KEYS)}


@router.get("/comfyui/status")
def comfy_status():
    return comfy.status()


@router.post("/comfyui/start")
def comfy_start():
    try:
        return comfy.start()
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/comfyui/log")
def comfy_log(lines: int = 60):
    """Tail of ComfyUI's console (logs/comfyui.log, written when ComfyUI is started by ComfyFlow)."""
    return comfy.log_tail(lines)


@router.get("/comfyui/stats")
def comfy_stats():
    return {"stats": comfy.stats(), "queue": comfy.queue()}


class ClearQueueIn(BaseModel):
    keep_run_id: Optional[str] = None


@router.post("/comfyui/clear-queue")
def comfy_clear_queue(body: ClearQueueIn):
    """Removes other jobs from ComfyUI's queue (and stops the running one) so this run can start."""
    from app.services.runs import RunError

    keep = None
    if body.keep_run_id:
        try:
            keep = runs.get(body.keep_run_id).get("comfy_prompt_id")
        except RunError:
            keep = None
    try:
        return comfy.clear_other_jobs(keep)
    except (RuntimeError, requests.RequestException) as e:
        raise HTTPException(409, str(e))


@router.post("/comfyui/sync-nodes")
def comfy_sync():
    if not comfy.status()["reachable"]:
        raise HTTPException(409, "ComfyUI is not running. Start it first, then sync the nodes.")
    try:
        return comfy.sync_nodes()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Node sync failed: {e}")


@router.get("/events")
async def events(request: Request):
    queue = bus.subscribe()

    async def stream():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
