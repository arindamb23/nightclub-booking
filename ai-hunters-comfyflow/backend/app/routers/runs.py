"""Runs, results, previews/downloads and input uploads."""
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from fastapi.responses import JSONResponse

from app.services.runs import runs, RunError, ModelsMissing, uploads_dir, previews
from app.services.workflows import WorkflowError

router = APIRouter(prefix="/api", tags=["runs"])

UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".webm", ".mov", ".mkv", ".avi",
               ".wav", ".mp3", ".flac", ".ogg", ".m4a"}


class RunIn(BaseModel):
    workflow_id: str
    overrides: Dict[str, Dict[str, Any]] = {}


@router.post("/runs")
def start_run(body: RunIn):
    try:
        return runs.start(body.workflow_id, body.overrides)
    except ModelsMissing as e:
        return JSONResponse(status_code=409, content={"detail": {
            "code": "models_missing", "message": str(e), "workflow_id": body.workflow_id, "models": e.models}})
    except (RunError, WorkflowError) as e:
        raise HTTPException(409, str(e))


@router.get("/runs")
def list_runs(workflow_id: Optional[str] = None, template_id: Optional[str] = None):
    return {"runs": runs.list(workflow_id, template_id)}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    try:
        return runs.get(run_id)
    except RunError as e:
        raise HTTPException(404, str(e))


@router.get("/runs/{run_id}/graph")
def run_graph(run_id: str):
    """Nodes and connections of the run, for the live node-by-node view."""
    from app.services import graph

    try:
        return graph.run_graph(runs.get(run_id))
    except RunError as e:
        raise HTTPException(404, str(e))
    except (WorkflowError, ValueError) as e:
        raise HTTPException(409, f"The node view is not available for this run: {e}")


@router.get("/runs/{run_id}/preview")
def run_preview(run_id: str):
    """Latest live preview frame ComfyUI sent while sampling (404 when there is none)."""
    frame = previews.get(run_id)
    if not frame:
        raise HTTPException(404, "No live preview yet.")
    return Response(frame[0], media_type=frame[1], headers={"Cache-Control": "no-store"})


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    try:
        return runs.cancel(run_id)
    except RunError as e:
        raise HTTPException(409, str(e))


@router.delete("/runs/{run_id}")
def delete_run(run_id: str):
    try:
        runs.delete(run_id)
    except RunError as e:
        raise HTTPException(409, str(e))
    return {"deleted": run_id}


@router.get("/runs/{run_id}/files/{filename}")
def run_file(run_id: str, filename: str, download: bool = False):
    try:
        path = runs.file_path(run_id, filename)
    except RunError as e:
        raise HTTPException(404, str(e))
    if not path.exists():
        raise HTTPException(404, "File was removed from disk.")
    if download:
        return FileResponse(path, filename=filename)
    return FileResponse(path)


@router.get("/runs/{run_id}/zip")
def run_zip(run_id: str):
    try:
        data = runs.zip_bytes(run_id)
    except RunError as e:
        raise HTTPException(404, str(e))
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="comfyflow_{run_id}.zip"'},
    )


@router.post("/uploads")
async def upload_input(file: UploadFile = File(...)):
    name = Path(file.filename or "input.png").name
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_EXTS:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use an image, video or audio file.")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).stem)[:60] or "input"
    stored = f"{safe}_{uuid.uuid4().hex[:6]}{ext}"
    (uploads_dir() / stored).write_bytes(await file.read())
    return {"filename": stored, "original": name}


@router.get("/uploads/{filename}")
def get_upload(filename: str):
    path = uploads_dir() / Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Upload not found.")
    return FileResponse(path)
