"""Workflow import (upload or local path), conversion output, models and parameters."""
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.services import workflows
from app.services.workflows import WorkflowError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

MAX_JSON = 50 * 1024 * 1024


def _guard(fn, *args, status=400):
    try:
        return fn(*args)
    except WorkflowError as e:
        raise HTTPException(404 if str(e).startswith("Workflow '") else status, str(e))


@router.get("")
def list_workflows():
    return {"workflows": workflows.list_all()}


@router.post("/upload")
async def upload(file: UploadFile = File(...), name: Optional[str] = Form(None)):
    raw = await file.read()
    if len(raw) > MAX_JSON:
        raise HTTPException(413, "Workflow file is larger than 50 MB.")
    return _guard(workflows.import_workflow, raw, file.filename or "workflow.json", name)


class PathIn(BaseModel):
    path: str
    name: Optional[str] = None


@router.post("/import-path")
def import_path(body: PathIn):
    return _guard(workflows.import_from_path, body.path, body.name)


@router.get("/{wid}")
def get_workflow(wid: str):
    return _guard(workflows.get, wid)


class RenameIn(BaseModel):
    name: str


@router.patch("/{wid}")
def rename(wid: str, body: RenameIn):
    return _guard(workflows.rename, wid, body.name)


@router.delete("/{wid}")
def delete(wid: str):
    _guard(workflows.delete, wid)
    return {"deleted": wid}


@router.get("/{wid}/script", response_class=PlainTextResponse)
def script(wid: str):
    return _guard(workflows.script, wid)


@router.get("/{wid}/models")
def models(wid: str):
    rows = _guard(workflows.detect_models, wid)
    return {"models": rows, "ready": sum(1 for r in rows if r["status"] == "ready"), "total": len(rows)}


@router.post("/{wid}/models/download-missing")
def download_missing(wid: str):
    return {"started": _guard(workflows.download_missing, wid)}


@router.get("/{wid}/parameters")
def parameters(wid: str):
    return {"parameters": _guard(workflows.parameters, wid)}
