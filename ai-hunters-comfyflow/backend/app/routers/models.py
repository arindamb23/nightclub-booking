"""Model registry CRUD and downloads."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.registry import registry, RegistryError, CATEGORIES
from app.services.downloader import downloader

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelIn(BaseModel):
    name: str
    url: str = ""
    category: str = "checkpoints"
    save_dir: str = ""
    original_name: Optional[str] = None


def _row(entry):
    fs = registry.file_status(entry)
    job = downloader.job(entry["name"])
    if fs["exists"]:
        status = "ready"
    elif job and job["status"] in ("queued", "downloading", "error"):
        status = job["status"]
    elif not entry.get("url"):
        status = "no_url"
    else:
        status = "missing"
    return {**entry, "resolved_dir": str(registry.resolve_dir(entry)), "path": fs["path"], "size": fs["size"], "status": status, "job": job}


@router.get("")
def list_models():
    return {"models": [_row(m) for m in registry.all()], "categories": CATEGORIES}


@router.post("")
def save_model(body: ModelIn):
    try:
        entry = registry.upsert(body.model_dump(exclude={"original_name"}), original_name=body.original_name)
    except RegistryError as e:
        raise HTTPException(400, str(e))
    return _row(entry)


@router.delete("/{name:path}")
def delete_model(name: str):
    if downloader.is_active(name):
        raise HTTPException(409, "Cancel the running download before deleting this model.")
    try:
        registry.delete(name)
    except RegistryError as e:
        raise HTTPException(404, str(e))
    return {"deleted": name}


class NameIn(BaseModel):
    name: str
    requested_name: Optional[str] = None


@router.post("/download")
def download(body: NameIn):
    try:
        return downloader.start(body.name, body.requested_name)
    except RegistryError as e:
        raise HTTPException(400, str(e))


@router.post("/download-all")
def download_all():
    started = []
    for m in registry.all():
        row = _row(m)
        if row["status"] in ("missing", "error"):
            started.append(downloader.start(m["name"]))
    return {"started": started}


@router.post("/cancel")
def cancel(body: NameIn):
    try:
        return downloader.cancel(body.requested_name or body.name)
    except RegistryError as e:
        raise HTTPException(404, str(e))
