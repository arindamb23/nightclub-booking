"""Workflow store: import JSON -> convert to .py -> detect models and parameters."""
from __future__ import annotations

import datetime as dt
import importlib.util
import inspect
import json
import os
import re
import shutil
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings, PROJECT_ROOT, replace_with_retry
from app.services import comfy
from app.services.registry import registry, CATEGORIES, RegistryError, is_local_source, local_source_path
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
def _new_id(display: str) -> str:
    base = _slug(display)
    wid, n = base, 2
    while (_root() / wid).exists():
        wid = f"{base}_{n}"
        n += 1
    return wid


def _finish_import(wid: str, meta: Dict[str, Any], model_hints: List[Dict[str, str]]) -> Dict[str, Any]:
    _atomic_write(_meta_path(wid), json.dumps(meta, indent=2))
    # register models that the workflow itself documents (name + url + directory)
    for hint in model_hints:
        cat = hint.get("directory") or "checkpoints"
        registry.ensure_entry(hint["name"], cat if cat in CATEGORIES else "checkpoints", hint.get("url", ""))
    detect_models(wid)  # registers unknown models too
    return get(wid)


def import_workflow(raw: bytes, filename: str, name: Optional[str] = None, source_path: Optional[str] = None) -> Dict[str, Any]:
    """Imports a ComfyUI workflow (.json) or a cb2c_py workflow script (.py)."""
    if filename.lower().endswith(".py"):
        return import_script(raw, filename, name, source_path)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise WorkflowError(f"'{filename}' is not valid JSON: {e}") from e
    display = (name or Path(filename).stem).strip() or "workflow"
    with _lock:
        wid = _new_id(display)
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
            "source_path": source_path,
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
    return _finish_import(wid, meta, result.model_hints)


def import_script(raw: bytes, filename: str, name: Optional[str] = None, source_path: Optional[str] = None) -> Dict[str, Any]:
    """Imports an existing Python workflow script (it must build a cb2c_py Workflow)."""
    try:
        code = raw.decode("utf-8-sig")
        compile(code, filename, "exec")
    except (UnicodeDecodeError, SyntaxError) as e:
        raise WorkflowError(f"'{filename}' is not a valid Python file: {e}") from e
    tree_name = re.search(r'^WORKFLOW_NAME\s*=\s*["\'](.+?)["\']', code, re.M)
    display = (name or (tree_name.group(1) if tree_name else Path(filename).stem)).strip() or "workflow"
    with _lock:
        wid = _new_id(display)
        folder = _root() / wid
        folder.mkdir(parents=True)
        (folder / "workflow.py").write_text(code, encoding="utf-8")
        try:
            wf = _load_script(folder / "workflow.py", wid)
        except WorkflowError:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        prompt = wf.to_prompt()
        (folder / "prompt.json").write_text(json.dumps(prompt, indent=2), encoding="utf-8")
        doc = re.match(r'\s*(?:"""|\'\'\')(.+?)(?:"""|\'\'\')', code, re.S)
        meta = {
            "id": wid,
            "name": display,
            "source_filename": Path(filename).name,
            "source_path": source_path,
            "format": "python",
            "node_count": len(prompt),
            "warnings": [],
            "notes": [doc.group(1).strip()] if doc else [],
            "model_hints": [],
            "created_at": _now(),
            "updated_at": _now(),
            "last_run_id": None,
            "last_run_status": None,
        }
    return _finish_import(wid, meta, [])


def import_from_path(path: str, name: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path.strip().strip('"'))
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.is_file():
        raise WorkflowError(f"File not found: {p}")
    if p.suffix.lower() not in (".json", ".py"):
        raise WorkflowError("Please choose a ComfyUI workflow .json file or a Python workflow .py script.")
    return import_workflow(p.read_bytes(), p.name, name, source_path=str(p.resolve()))


# ----------------------------------------------------------------- sample library
def _samples_dir() -> Path:
    return PROJECT_ROOT / "samples" / "workflows"


def list_samples() -> List[Dict[str, Any]]:
    folder = _samples_dir()
    index = {}
    lib = folder / "library.json"
    if lib.exists():
        index = {e["file"]: e for e in json.loads(lib.read_text(encoding="utf-8"))}
    opened = {}
    for d in _root().iterdir():
        if (d / "meta.json").exists():
            sp = json.loads((d / "meta.json").read_text(encoding="utf-8")).get("source_path")
            if sp:
                opened[Path(sp).name if Path(sp).parent == folder.resolve() else sp] = d.name
    items = []
    for f in sorted(folder.glob("*")):
        if f.suffix.lower() not in (".json", ".py") or f.name == "library.json":
            continue
        e = index.get(f.name, {})
        items.append({
            "file": f.name,
            "name": e.get("name", f.stem.replace("_", " ").title()),
            "description": e.get("description", ""),
            "kind": e.get("kind", "image"),
            "format": "python" if f.suffix.lower() == ".py" else "json",
            "path": str(f),
            "workflow_id": opened.get(f.name),
        })
    order = list(index)
    items.sort(key=lambda i: order.index(i["file"]) if i["file"] in order else len(order))
    return items


def open_sample(file: str) -> Dict[str, Any]:
    sample = next((s for s in list_samples() if s["file"] == file), None)
    if sample is None:
        raise WorkflowError(f"Sample '{file}' not found.")
    if sample["workflow_id"] and _meta_path(sample["workflow_id"]).exists():
        return get(sample["workflow_id"])
    p = Path(sample["path"])
    return import_workflow(p.read_bytes(), p.name, sample["name"], source_path=str(p.resolve()))


def seed_samples() -> None:
    """Adds the sample library to the Workflows list once (first start)."""
    marker = get_settings().data_dir / ".samples_added"
    if marker.exists():
        return
    for sample in list_samples():
        try:
            open_sample(sample["file"])
        except (WorkflowError, OSError):
            continue
    marker.write_text(_now(), encoding="utf-8")


# ----------------------------------------------------------------- queries
def _read_meta(wid: str) -> Dict[str, Any]:
    return json.loads(_meta_path(wid).read_text(encoding="utf-8"))


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    replace_with_retry(tmp, path)


def _write_meta(wid: str, meta: Dict[str, Any]) -> None:
    meta["updated_at"] = _now()
    _atomic_write(_meta_path(wid), json.dumps(meta, indent=2))


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
_prompt_cache: Dict[str, Any] = {}


def _load_script(path: Path, wid: str) -> Workflow:
    """Executes a workflow script and returns its Workflow.

    Uses ``build_workflow()``; older scripts are accepted too when they define a
    single function without required arguments that returns a Workflow.
    """
    mod_name = f"comfyflow_wf_{wid}_{uuid.uuid4().hex[:6]}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise WorkflowError("Cannot load workflow script.")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        builder = getattr(module, "build_workflow", None)
        if builder is None:
            candidates = [
                f for n, f in vars(module).items()
                if inspect.isfunction(f) and f.__module__ == mod_name and not n.startswith("_")
                and all(p.default is not inspect.Parameter.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                        for p in inspect.signature(f).parameters.values())
            ]
            if len(candidates) != 1:
                raise WorkflowError(
                    "The script must define build_workflow() returning a Workflow "
                    "(see samples/workflows/*.py for examples)."
                )
            builder = candidates[0]
        wf = builder()
    except WorkflowError:
        raise
    except Exception as e:  # noqa: BLE001 - user-editable script
        raise WorkflowError(f"The workflow script failed to build: {type(e).__name__}: {e}") from e
    finally:
        sys.modules.pop(mod_name, None)
    if not isinstance(wf, Workflow):
        raise WorkflowError("build_workflow() must return a cb2c_py Workflow.")
    return wf


def build(wid: str) -> Workflow:
    """Imports the workflow's .py and returns its Workflow."""
    _check_id(wid)
    return _load_script(_root() / wid / "workflow.py", wid)


def reconvert(wid: str, reason: str = "") -> bool:
    """Converts ``source.json`` again with the current converter and node catalog (keeps a backup of workflow.py).

    Used when a workflow was imported before group nodes/subgraphs were expanded, or before its custom nodes
    were installed (their widget values can only be mapped exactly once ComfyUI knows the node).
    """
    _check_id(wid)
    folder = _root() / wid
    source = folder / "source.json"
    if not source.is_file():
        return False
    meta = _read_meta(wid)
    data = json.loads(source.read_text(encoding="utf-8"))
    result = convert(data, sanitize_name(wid), meta.get("source_filename", "workflow.json"), comfy.catalog())
    if (folder / "workflow.py").read_text(encoding="utf-8") == result.script:
        return False
    history = folder / "history"
    history.mkdir(exist_ok=True)
    shutil.copyfile(folder / "workflow.py", history / f"workflow_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}_before_reconvert.py")
    _atomic_write(folder / "workflow.py", result.script)
    _atomic_write(folder / "prompt.json", json.dumps(result.prompt, indent=2))
    meta.update(node_count=result.node_count, warnings=result.warnings, notes=result.notes,
                model_hints=result.model_hints or meta.get("model_hints", []), updated_at=_now(),
                reconverted_at=_now(), reconvert_reason=reason)
    _write_meta(wid, meta)
    _prompt_cache.clear()
    for hint in result.model_hints:
        cat = hint.get("directory") or "checkpoints"
        registry.ensure_entry(hint["name"], cat if cat in CATEGORIES else "checkpoints", hint.get("url", ""))
    return True


def needs_expansion(prompt: Dict[str, Any]) -> bool:
    """True when an old conversion left a group node / subgraph instance in the prompt."""
    from cb2c_py.tools.subgraphs import group_name

    return any(group_name(n.get("class_type")) is not None or re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{27}", str(n.get("class_type")))
               for n in prompt.values())


def migrate_group_nodes() -> List[str]:
    """Start-up: re-convert workflows imported with group nodes / subgraphs before v1.0.8."""
    done = []
    for d in _root().iterdir() if _root().exists() else []:
        try:
            if (d / "source.json").is_file() and needs_expansion(json.loads((d / "prompt.json").read_text(encoding="utf-8"))):
                if reconvert(d.name, "group nodes / subgraphs expanded"):
                    done.append(d.name)
        except (OSError, ValueError, WorkflowError):
            continue
    return done


def _prompt(wid: str) -> Dict[str, Any]:
    path = _root() / wid / "workflow.py"
    key = f"{wid}:{path.stat().st_mtime_ns}"
    if key in _prompt_cache:
        return _prompt_cache[key]
    try:
        prompt = build(wid).to_prompt()
    except WorkflowError:
        prompt = json.loads((_root() / wid / "prompt.json").read_text(encoding="utf-8"))
    _prompt_cache[key] = prompt
    return prompt


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
    return detect_models_in_prompt(_prompt(wid), hints, register)


def detect_models_in_prompt(
    prompt: Dict[str, Any], hints: Optional[Dict[str, str]] = None, register: bool = True
) -> List[Dict[str, Any]]:
    """Model files referenced by an API-format graph (workflow or template), with download status."""
    hints = hints or {}
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
            "partial": fs["partial"],
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


def resolve_models(wid: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Saves the URL or local file path the user entered for missing models.

    ``items``: ``[{name, value, category?}]`` where value is a download URL or the
    full path of the model file (or of the folder that contains it).
    """
    resolve_rows(detect_models(wid), items)
    return detect_models(wid)


def resolve_rows(detected: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validates and saves URLs / local paths for detected model rows (workflows and templates)."""
    rows = {r["name"]: r for r in detected}
    errors: List[str] = []
    updates = []
    for it in items:
        name = it.get("name", "")
        value = str(it.get("value") or "").strip().strip('"')
        row = rows.get(name)
        if row is None:
            errors.append(f"{name}: this model is not used by the workflow.")
            continue
        if not value:
            errors.append(f"{name}: enter a download URL or the path of the model file.")
            continue
        if is_local_source(value):
            p = local_source_path(value)
            if p.is_dir():
                p = p / Path(name).name
            if not p.is_file():
                errors.append(f"{name}: no file at {p}")
                continue
            value = str(p)
        elif not value.lower().startswith(("http://", "https://")):
            errors.append(f"{name}: '{value}' is neither a URL nor a file path.")
            continue
        entry = registry.get(row["registry_name"]) or {"name": row["registry_name"], "save_dir": ""}
        category = it.get("category") or row["category"]
        updates.append(({**entry, "url": value, "category": category}, entry["name"]))
    if errors:
        raise WorkflowError("Some entries need a fix:\n" + "\n".join(errors))
    for entry, original in updates:
        try:
            registry.upsert(entry, original_name=original)
        except RegistryError as e:
            raise WorkflowError(str(e)) from e
        downloader.clear(original, *[n for n, r in rows.items() if r["registry_name"] == original])
    return []
