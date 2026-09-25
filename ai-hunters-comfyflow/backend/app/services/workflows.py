"""Workflow store: import JSON -> convert to .py -> detect models and parameters."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings, PROJECT_ROOT
from app.services import comfy
from app.services.registry import registry, CATEGORIES
from app.services.downloader import downloader
from cb2c_py.lib.workflow import Workflow
from cb2c_py.tools.convert_workflow import convert, sanitize_name

MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".onnx", ".sft", ".pkl")

# input name -> category (generic)
INPUT_CATEGORY = {
    "ckpt_name": "checkpoints",
    "vae_name": "vae",
    "lora_name": "loras",
    "lora": "loras",
    "control_net_name": "controlnet",
    "controlnet_name": "controlnet",
    "unet_name": "diffusion_models",
    "clip_name": "text_encoders",
    "clip_name1": "text_encoders",
    "clip_name2": "text_encoders",
    "clip_name3": "text_encoders",
    "clip_name4": "text_encoders",
    "style_model_name": "style_models",
    "gligen_name": "gligen",
    "upscale_model": "upscale_models",
    "model_name": "upscale_models",
    "model_path": "diffusion_models",
    "photomaker_model_name": "photomaker",
    "hypernetwork_name": "hypernetworks",
    "embedding": "embeddings",
}
# (class_type, input) overrides
CLASS_INPUT_CATEGORY = {
    ("UnetLoaderGGUF", "unet_name"): "unet",
    ("UnetLoaderGGUFAdvanced", "unet_name"): "unet",
    ("CLIPVisionLoader", "clip_name"): "clip_vision",
    ("CLIPLoaderGGUF", "clip_name"): "text_encoders",
    ("ImageOnlyCheckpointLoader", "ckpt_name"): "checkpoints",
}

TEXT_INPUTS = {"text", "prompt", "positive", "negative", "positive_prompt", "negative_prompt", "text_g", "text_l", "caption"}
NUMBER_INPUTS = {
    "seed", "noise_seed", "steps", "cfg", "denoise", "width", "height", "length", "batch_size",
    "guidance", "shift", "fps", "frame_rate", "megapixels", "num_frames", "strength", "lora_strength",
    "strength_model", "strength_clip",
}
SEED_INPUTS = {"seed", "noise_seed"}
MEDIA_LOADERS = {"LoadImage": "image", "LoadImageMask": "image", "LoadImageOutput": "image"}

_lock = threading.Lock()


class WorkflowError(ValueError):
    pass


def _root() -> Path:
    p = get_settings().data_dir / "workflows"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return (s or "workflow")[:48]


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _meta_path(wid: str) -> Path:
    return _root() / wid / "meta.json"


def _check_id(wid: str) -> str:
    if not re.fullmatch(r"[a-z0-9_]+", wid or ""):
        raise WorkflowError("Invalid workflow id.")
    if not _meta_path(wid).exists():
        raise WorkflowError(f"Workflow '{wid}' not found.")
    return wid


# ----------------------------------------------------------------- import
def import_workflow(raw: bytes, filename: str, name: Optional[str] = None) -> Dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise WorkflowError(f"'{filename}' is not valid JSON: {e}") from e
    display = (name or Path(filename).stem).strip() or "workflow"
    with _lock:
        base = _slug(display)
        wid, n = base, 2
        while (_root() / wid).exists():
            wid = f"{base}_{n}"
            n += 1
        try:
            result = convert(data, sanitize_name(wid), filename, comfy.catalog())
        except ValueError as e:
            raise WorkflowError(str(e)) from e
        folder = _root() / wid
        folder.mkdir(parents=True)
        (folder / "source.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        (folder / "workflow.py").write_text(result.script, encoding="utf-8")
        (folder / "prompt.json").write_text(json.dumps(result.prompt, indent=2), encoding="utf-8")
        meta = {
            "id": wid,
            "name": display,
            "source_filename": Path(filename).name,
            "format": result.format,
            "node_count": result.node_count,
            "warnings": result.warnings,
            "notes": result.notes,
            "model_hints": result.model_hints,
            "created_at": _now(),
            "updated_at": _now(),
            "last_run_id": None,
            "last_run_status": None,
        }
        _meta_path(wid).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    # register models that the workflow itself documents (name + url + directory)
    for hint in result.model_hints:
        cat = hint.get("directory") or "checkpoints"
        registry.ensure_entry(hint["name"], cat if cat in CATEGORIES else "checkpoints", hint.get("url", ""))
    detect_models(wid)  # registers unknown models too
    return get(wid)


def import_from_path(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path.strip().strip('"'))
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.is_file():
        raise WorkflowError(f"File not found: {p}")
    if p.suffix.lower() != ".json":
        raise WorkflowError("Please choose a ComfyUI workflow .json file.")
    return import_workflow(p.read_bytes(), p.name, name)


# ----------------------------------------------------------------- queries
def _read_meta(wid: str) -> Dict[str, Any]:
    return json.loads(_meta_path(wid).read_text(encoding="utf-8"))


def _write_meta(wid: str, meta: Dict[str, Any]) -> None:
    meta["updated_at"] = _now()
    _meta_path(wid).write_text(json.dumps(meta, indent=2), encoding="utf-8")


def get(wid: str) -> Dict[str, Any]:
    _check_id(wid)
    meta = _read_meta(wid)
    models = detect_models(wid, register=False)
    meta["models_total"] = len(models)
    meta["models_ready"] = sum(1 for m in models if m["status"] == "ready")
    return meta


def list_all() -> List[Dict[str, Any]]:
    items = []
    for d in sorted(_root().iterdir()):
        if (d / "meta.json").exists():
            try:
                items.append(get(d.name))
            except (WorkflowError, ValueError, OSError):
                continue
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items


def script(wid: str) -> str:
    _check_id(wid)
    return (_root() / wid / "workflow.py").read_text(encoding="utf-8")


def rename(wid: str, name: str) -> Dict[str, Any]:
    _check_id(wid)
    meta = _read_meta(wid)
    meta["name"] = name.strip() or meta["name"]
    _write_meta(wid, meta)
    return get(wid)


def delete(wid: str) -> None:
    _check_id(wid)
    shutil.rmtree(_root() / wid)


def record_run(wid: str, run_id: str, status: str) -> None:
    try:
        meta = _read_meta(wid)
    except OSError:
        return
    meta["last_run_id"], meta["last_run_status"] = run_id, status
    _write_meta(wid, meta)


# ----------------------------------------------------------------- build
def build(wid: str) -> Workflow:
    """Imports the workflow's .py and returns ``build_workflow()``."""
    _check_id(wid)
    path = _root() / wid / "workflow.py"
    mod_name = f"comfyflow_wf_{wid}_{uuid.uuid4().hex[:6]}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise WorkflowError("Cannot load workflow script.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        wf = module.build_workflow()
    except Exception as e:  # noqa: BLE001 - user-editable script
        raise WorkflowError(f"The workflow script failed to build: {type(e).__name__}: {e}") from e
    finally:
        sys.modules.pop(mod_name, None)
    if not isinstance(wf, Workflow):
        raise WorkflowError("build_workflow() must return a Workflow.")
    return wf


def _prompt(wid: str) -> Dict[str, Any]:
    try:
        return build(wid).to_prompt()
    except WorkflowError:
        return json.loads((_root() / wid / "prompt.json").read_text(encoding="utf-8"))


# ----------------------------------------------------------------- models
def _category_for(class_type: str, input_name: str, value: str, hints: Dict[str, str]) -> str:
    if value in hints and hints[value] in CATEGORIES:
        return hints[value]
    if (class_type, input_name) in CLASS_INPUT_CATEGORY:
        return CLASS_INPUT_CATEGORY[(class_type, input_name)]
    if "GGUF" in class_type and input_name == "unet_name":
        return "unet"
    if input_name in INPUT_CATEGORY:
        return INPUT_CATEGORY[input_name]
    low = class_type.lower()
    for key, cat in (("lora", "loras"), ("vae", "vae"), ("controlnet", "controlnet"), ("upscale", "upscale_models"), ("clip", "text_encoders"), ("unet", "diffusion_models")):
        if key in low:
            return cat
    return "checkpoints"


def detect_models(wid: str, register: bool = True) -> List[Dict[str, Any]]:
    """Finds model files referenced by the workflow and joins them with the registry."""
    meta = _read_meta(wid)
    hints = {h["name"]: h.get("directory", "") for h in meta.get("model_hints") or []}
    prompt = _prompt(wid)
    found: Dict[str, Dict[str, Any]] = {}
    for node_id, node in prompt.items():
        ctype = node.get("class_type", "")
        title = (node.get("_meta") or {}).get("title") or ctype
        for input_name, value in (node.get("inputs") or {}).items():
            if not isinstance(value, str):
                continue
            is_model_input = input_name in INPUT_CATEGORY or (ctype, input_name) in CLASS_INPUT_CATEGORY
            if not (value.lower().endswith(MODEL_EXTS) or (is_model_input and "." in value)):
                continue
            name = value.replace("\\", "/")
            if name in found:
                found[name]["used_by"].append(f"{title} ({node_id})")
                continue
            found[name] = {
                "name": name,
                "category": _category_for(ctype, input_name, value, hints),
                "node_id": node_id,
                "class_type": ctype,
                "input": input_name,
                "used_by": [f"{title} ({node_id})"],
            }
    rows = []
    for name, item in found.items():
        entry = registry.get(name)
        if entry is None and register:
            entry = registry.ensure_entry(name, item["category"])
        if entry is None:
            entry = {"name": name, "url": "", "category": item["category"], "save_dir": ""}
        fs = registry.file_status(entry, name)
        job = downloader.job(name) or downloader.job(entry["name"])
        if fs["exists"]:
            status = "ready"
        elif job and job["status"] in ("queued", "downloading"):
            status = job["status"]
        elif job and job["status"] == "error":
            status = "error"
        elif not entry.get("url"):
            status = "no_url"
        else:
            status = "missing"
        rows.append({
            **item,
            "registry_name": entry["name"],
            "url": entry.get("url", ""),
            "category": entry.get("category", item["category"]),
            "save_dir": entry.get("save_dir", ""),
            "resolved_dir": str(registry.resolve_dir(entry)),
            "path": fs["path"],
            "size": fs["size"],
            "status": status,
            "job": job,
        })
    return rows


def download_missing(wid: str) -> List[Dict[str, Any]]:
    started = []
    for row in detect_models(wid):
        if row["status"] in ("missing", "error"):
            started.append(downloader.start(row["registry_name"], row["name"]))
    return started


# ----------------------------------------------------------------- params
def parameters(wid: str) -> List[Dict[str, Any]]:
    """Editable inputs shown in the Run step (prompts, seed, sizes, input media)."""
    prompt = _prompt(wid)
    params: List[Dict[str, Any]] = []
    for node_id, node in prompt.items():
        ctype = node.get("class_type", "")
        title = (node.get("_meta") or {}).get("title") or ctype
        for input_name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list):
                continue  # link
            kind = None
            if ctype in MEDIA_LOADERS and input_name == MEDIA_LOADERS[ctype]:
                kind = "image"
            elif "LoadVideo" in ctype and input_name == "video":
                kind = "video"
            elif input_name in TEXT_INPUTS and isinstance(value, str):
                kind = "text"
            elif input_name == "filename_prefix" and isinstance(value, str):
                kind = "string"
            elif input_name in NUMBER_INPUTS and isinstance(value, (int, float)) and not isinstance(value, bool):
                kind = "seed" if input_name in SEED_INPUTS else "number"
            if kind:
                params.append({
                    "node_id": node_id,
                    "class_type": ctype,
                    "title": title,
                    "input": input_name,
                    "kind": kind,
                    "value": value,
                    "is_float": isinstance(value, float),
                })
    order = {"image": 0, "video": 0, "text": 1, "seed": 2, "number": 3, "string": 4}
    def text_rank(p):
        t = f'{p["title"]} {p["input"]}'.lower()
        return 2 if "neg" in t else 0 if "pos" in t else 1

    params.sort(key=lambda p: (order[p["kind"]], text_rank(p) if p["kind"] == "text" else 0, p["title"], p["input"]))
    return params
