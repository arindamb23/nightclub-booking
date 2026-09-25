"""Workflow import (upload or local path), conversion output, models and parameters."""
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.services import workflows
from app.services.workflows import WorkflowError

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

MAX_JSON = 50 * 1024 * 1024

samples_router = APIRouter(prefix="/api/samples", tags=["samples"])


@samples_router.get("")
def list_samples():
    return {"samples": workflows.list_samples()}


class SampleIn(BaseModel):
    file: str


@samples_router.post("/open")
def open_sample(body: SampleIn):
    return _guard(workflows.open_sample, body.file)


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
    if not (file.filename or "").lower().endswith((".json", ".py")):
        raise HTTPException(400, "Choose a ComfyUI workflow .json file or a Python workflow .py script.")
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


class ResolveItem(BaseModel):
    name: str
    value: str
    category: Optional[str] = None


class ResolveIn(BaseModel):
    items: List[ResolveItem]


@router.post("/{wid}/models/resolve")
def resolve_models(wid: str, body: ResolveIn):
    rows = _guard(workflows.resolve_models, wid, [i.model_dump() for i in body.items])
    return {"models": rows, "ready": sum(1 for r in rows if r["status"] == "ready"), "total": len(rows)}


@router.get("/{wid}/parameters")
def parameters(wid: str):
    return {"parameters": _guard(workflows.parameters, wid)}
