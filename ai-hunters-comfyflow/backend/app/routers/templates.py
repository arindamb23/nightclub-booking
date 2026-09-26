"""Python templates: list, upload, model check/resolve, generate (run) and sample input images."""
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from app.services.nodepacks import NodesMissing
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.services import templates
from app.services.templates import TemplateError, TASKS, SAMPLE_IMAGES
from app.services.runs import runs, RunError, ModelsMissing

router = APIRouter(prefix="/api/templates", tags=["templates"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except TemplateError as e:
        raise HTTPException(404 if "not found" in str(e) else 400, str(e))


def _summary(rows):
    return {"models": rows, "ready": sum(1 for r in rows if r["status"] in ("ready", "node")), "total": len(rows)}


@router.get("")
def list_templates():
    return {"templates": templates.list_templates(), "tasks": TASKS}


@router.get("/sample-images")
def sample_images():
    return {"images": sorted(p.name for p in SAMPLE_IMAGES.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))}


@router.get("/sample-images/{name}")
def sample_image(name: str):
    p = SAMPLE_IMAGES / Path(name).name
    if not p.is_file():
        raise HTTPException(404, "Sample image not found.")
    return FileResponse(p)


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "Template file is larger than 2 MB.")
    return {"templates": _guard(templates.save_upload, raw, file.filename or "template.py")}


@router.delete("/{tid}")
def delete(tid: str):
    _guard(templates.delete, tid)
    return {"deleted": tid}


class ValuesIn(BaseModel):
    values: Dict[str, Any] = {}


@router.post("/{tid}/models")
def models(tid: str, body: ValuesIn):
    return _summary(_guard(templates.detect_models, tid, body.values))


class ResolveItem(BaseModel):
    name: str
    value: str
    category: Optional[str] = None


class ResolveIn(BaseModel):
    items: List[ResolveItem]
    values: Dict[str, Any] = {}


@router.post("/{tid}/models/resolve")
def resolve(tid: str, body: ResolveIn):
    return _summary(_guard(templates.resolve_models, tid, body.values, [i.model_dump() for i in body.items]))


@router.post("/{tid}/models/download-missing")
def download_missing(tid: str, body: ValuesIn):
    from app.services.workflows import downloader

    started = []
    for r in _guard(templates.detect_models, tid, body.values):
        if r["status"] in ("missing", "error") and r["url"]:
            started.append(downloader.start(r["registry_name"], r["name"]))
    return {"started": started}


@router.post("/{tid}/generate")
def generate(tid: str, body: ValuesIn):
    try:
        return runs.start_template(tid, body.values)
    except NodesMissing as e:
        return JSONResponse(status_code=409, content={"detail": {
            "code": "nodes_missing", "message": str(e), "template_id": tid, "packs": e.packs}})
    except ModelsMissing as e:
        return JSONResponse(status_code=409, content={"detail": {
            "code": "models_missing", "message": str(e), "template_id": tid, "models": e.models}})
    except (RunError, TemplateError) as e:
        raise HTTPException(409 if isinstance(e, RunError) else 400, str(e))
