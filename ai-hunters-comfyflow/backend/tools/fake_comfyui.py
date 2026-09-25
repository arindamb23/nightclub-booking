"""A tiny stand-in for ComfyUI used by the test-suite and for UI demos without a GPU.

    python -m tools.fake_comfyui --port 8188

It implements the endpoints ComfyFlow uses (/system_stats, /object_info, /prompt,
/ws, /history, /view, /upload/image, /interrupt). Save*Image nodes return
samples/images/beach.png, video/animation save nodes return samples/videos/sample.webm.
A node with class_type "FailNode" triggers a validation error, "CrashNode" an
execution error.
"""
import argparse
import asyncio
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_IMAGE = ROOT / "samples" / "images" / "beach.png"
SAMPLE_VIDEO = ROOT / "samples" / "videos" / "sample.webm"
PREVIEW_PNG = ROOT / "samples" / "images" / "girl.png"
VIDEO_NODES = ("SaveAnimatedWEBP", "SaveVideo", "VHS_VideoCombine", "SaveWEBM", "SaveAnimatedPNG")

app = FastAPI(title="Fake ComfyUI")
state: Dict[str, Any] = {"clients": {}, "history": {}, "interrupt": False, "dir": Path(tempfile.mkdtemp(prefix="fakecomfy_"))}
(state["dir"] / "output").mkdir()
(state["dir"] / "input").mkdir()
STEP_DELAY = 0.05
HISTORY_DELAY = 0.6


@app.get("/system_stats")
def system_stats():
    return {"system": {"comfyui_version": "fake-1.0", "os": "fake"}, "devices": [{"name": "Fake GPU", "type": "cuda", "vram_total": 8 * 1024**3}]}


@app.get("/object_info")
def object_info():
    return {}


@app.post("/interrupt")
def interrupt():
    state["interrupt"] = True
    return {}


@app.post("/upload/image")
async def upload(image: UploadFile = File(...), subfolder: str = Form(""), overwrite: str = Form("false")):
    (state["dir"] / "input" / image.filename).write_bytes(await image.read())
    return {"name": image.filename, "subfolder": "", "type": "input"}


@app.get("/view")
def view(filename: str, subfolder: str = "", type: str = "output"):
    p = state["dir"] / type / filename
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/history/{prompt_id}")
def history(prompt_id: str):
    h = state["history"].get(prompt_id)
    return {prompt_id: h} if h else {}


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    cid = websocket.query_params.get("clientId", "anon")
    state["clients"][cid] = websocket
    try:
        await websocket.send_json({"type": "status", "data": {"status": {"exec_info": {"queue_remaining": 0}}, "sid": cid}})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        state["clients"].pop(cid, None)


async def _send(cid, msg):
    ws = state["clients"].get(cid)
    if ws is not None:
        try:
            await ws.send_json(msg)
        except Exception:  # noqa: BLE001
            pass


async def _send_bytes(cid, data: bytes):
    ws = state["clients"].get(cid)
    if ws is not None:
        try:
            await ws.send_bytes(data)
        except Exception:  # noqa: BLE001
            pass


def _preview_frame() -> bytes:
    """A binary PREVIEW_IMAGE frame like ComfyUI's --preview-method (event 1, image type 2 = PNG)."""
    png = PREVIEW_PNG.read_bytes() if PREVIEW_PNG.is_file() else b""
    return (1).to_bytes(4, "big") + (2).to_bytes(4, "big") + png


async def _execute(prompt_id: str, prompt: Dict[str, Any], cid: str):
    state.setdefault("running", []).append(prompt_id)
    try:
        await _execute_inner(prompt_id, prompt, cid)
    finally:
        state["running"].remove(prompt_id)


async def _execute_inner(prompt_id: str, prompt: Dict[str, Any], cid: str):
    state["interrupt"] = False
    await asyncio.sleep(0.2)
    await _send(cid, {"type": "execution_start", "data": {"prompt_id": prompt_id}})
    outputs: Dict[str, Any] = {}
    for node_id, node in prompt.items():
        if state["interrupt"]:
            await _send(cid, {"type": "execution_interrupted", "data": {"prompt_id": prompt_id, "node_id": node_id}})
            return
        ctype = node["class_type"]
        await _send(cid, {"type": "executing", "data": {"node": node_id, "prompt_id": prompt_id}})
        if ctype == "CrashNode":
            await _send(cid, {"type": "execution_error", "data": {"prompt_id": prompt_id, "node_id": node_id, "node_type": ctype, "exception_type": "RuntimeError", "exception_message": "simulated crash"}})
            return
        steps = int(node["inputs"].get("steps", 0) or 0) if "Sampler" in ctype else 0
        for i in range(1, steps + 1):
            if state["interrupt"]:
                break
            await asyncio.sleep(STEP_DELAY)
            await _send(cid, {"type": "progress", "data": {"value": i, "max": steps, "prompt_id": prompt_id, "node": node_id}})
            if i % 5 == 1 and PREVIEW_PNG.is_file():
                await _send_bytes(cid, _preview_frame())
        prefix = str(node["inputs"].get("filename_prefix", "ComfyUI")).replace("/", "_")
        if ctype in VIDEO_NODES:
            name = f"{prefix}_{node_id}_{uuid.uuid4().hex[:4]}.webm"
            shutil.copy(SAMPLE_VIDEO, state["dir"] / "output" / name)
            outputs[node_id] = {"images": [{"filename": name, "subfolder": "", "type": "output"}], "animated": [True]}
        elif ctype.startswith("Save") or ctype == "PreviewImage":
            batch = max([int(n["inputs"].get("batch_size", 1) or 1) for n in prompt.values()
                         if isinstance(n["inputs"].get("batch_size"), int)] or [1])
            items = []
            for b in range(max(1, min(batch, 4))):
                name = f"{prefix}_{node_id}_{b}_{uuid.uuid4().hex[:4]}.png"
                shutil.copy(SAMPLE_IMAGE, state["dir"] / "output" / name)
                items.append({"filename": name, "subfolder": "", "type": "output"})
            outputs[node_id] = {"images": items}
        if node_id in outputs:
            await _send(cid, {"type": "executed", "data": {"node": node_id, "output": outputs[node_id], "prompt_id": prompt_id}})
    # Same order as real ComfyUI: execution_success first, the history entry is written a moment later
    await _send(cid, {"type": "execution_success", "data": {"prompt_id": prompt_id}})
    await asyncio.sleep(HISTORY_DELAY)
    state["history"][prompt_id] = {"outputs": outputs, "status": {"completed": True, "status_str": "success"}}
    await _send(cid, {"type": "executing", "data": {"node": None, "prompt_id": prompt_id}})


@app.get("/queue")
async def get_queue():
    return {"queue_running": [[i, pid, {}, {}, []] for i, pid in enumerate(state.setdefault("running", []))], "queue_pending": []}


@app.post("/queue")
async def edit_queue(request: Request):
    state.setdefault("queue_edits", []).append(await request.json())
    return {}


@app.post("/prompt")
async def queue_prompt(request: Request):
    body = await request.json()
    prompt = body.get("prompt") or {}
    errors = {
        nid: {"class_type": n["class_type"], "errors": [{"message": "Value not in list", "details": "simulated validation error", "extra_info": {"input_name": "value"}}]}
        for nid, n in prompt.items() if n.get("class_type") == "FailNode"
    }
    if errors:
        return JSONResponse(status_code=400, content={"error": {"message": "Prompt outputs failed validation", "details": ""}, "node_errors": errors})
    prompt_id = str(uuid.uuid4())
    asyncio.create_task(_execute(prompt_id, prompt, body.get("client_id", "anon")))
    return {"prompt_id": prompt_id, "number": 1, "node_errors": {}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8188)
    ap.add_argument("--step-delay", type=float, default=0.05)
    a = ap.parse_args()
    STEP_DELAY = a.step_delay
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
