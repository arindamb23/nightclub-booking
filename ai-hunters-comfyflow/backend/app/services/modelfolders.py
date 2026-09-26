"""Which ComfyUI models folder a node input reads from – asked from ComfyUI itself, not guessed.

ComfyUI lists the files a loader input accepts in ``/object_info`` (a COMBO of file names) and the files of every
models folder in ``/models`` + ``/models/<folder>``. The folder whose file list matches the input's options is the
folder ComfyUI looks in. That works for every custom node (HunyuanVideoWrapper, WanVideoWrapper, …) without a list
of node names. Learned answers are kept in ``data/model_folders.json`` for when ComfyUI is not running.

``ensure_placement`` moves a model that is on disk but in a folder ComfyUI does not read for that input.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.config import get_settings, replace_with_retry
from app.services import comfy

_lock = threading.Lock()
_folders_cache: Dict[str, Any] = {"at": 0.0, "data": None}
FOLDERS_TTL = 20.0
SAFE_FOLDER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
# folders ComfyUI reads together (legacy names)
SAME_FOLDER = [{"unet", "diffusion_models"}, {"clip", "text_encoders"}]
SKIP_FOLDERS = {"configs", "custom_nodes"}


def _norm(name: str) -> str:
    return str(name).replace("\\", "/").strip()


def same_folder(a: str, b: str) -> bool:
    return a == b or any(a in g and b in g for g in SAME_FOLDER)


# ------------------------------------------------------------------ learned answers
def _learned_path() -> Path:
    return get_settings().data_dir / "model_folders.json"


def _read_learned() -> Dict[str, str]:
    p = _learned_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def _learn(key: str, folder: str) -> None:
    with _lock:
        data = _read_learned()
        if data.get(key) == folder:
            return
        data[key] = folder
        p = _learned_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        replace_with_retry(tmp, p)


def learned_folders() -> List[str]:
    return sorted(set(_read_learned().values()))


# ------------------------------------------------------------------ ComfyUI facts
def folder_lists(force: bool = False) -> Optional[Dict[str, set]]:
    """{folder: {file, …}} from ComfyUI's /models endpoints (None when ComfyUI is not reachable)."""
    now = time.time()
    if not force and _folders_cache["data"] is not None and now - _folders_cache["at"] < FOLDERS_TTL:
        return _folders_cache["data"]
    url = get_settings().comfyui_url
    try:
        names = requests.get(f"{url}/models", timeout=5).json()
        if not isinstance(names, list):
            return None
        data = {}
        for f in names:
            if not isinstance(f, str) or f in SKIP_FOLDERS:
                continue
            files = requests.get(f"{url}/models/{f}", timeout=10).json()
            data[f] = {_norm(x) for x in files if isinstance(x, str)} if isinstance(files, list) else set()
    except (requests.RequestException, ValueError):
        return None
    _folders_cache.update(at=now, data=data)
    return data


def invalidate() -> None:
    _folders_cache.update(at=0.0, data=None)


def combo_options(class_type: str, input_name: str) -> Optional[List[str]]:
    spec = comfy.catalog().spec(class_type)
    for entry in (spec or {}).get("inputs") or []:
        if entry["name"] == input_name:
            t = entry.get("type")
            if isinstance(t, list):
                return [_norm(x) for x in t if isinstance(x, str)]
            opts = (entry.get("opts") or {}).get("options")
            if isinstance(opts, list):
                return [_norm(x) for x in opts if isinstance(x, str)]
    return None


def match_folder(options: List[str], folders: Dict[str, set]) -> Optional[str]:
    """The folder whose files best match a COMBO's options (None when unclear)."""
    opts = {o for o in options if "." in o}
    if not opts:
        return None
    # an input's options are the folder's files (maybe older than the folder): count how many are in each folder
    best, best_key = None, (0.0, 0)
    for folder, files in folders.items():
        if not files:
            continue
        share = len(opts & files) / len(opts)
        key = (share, -len(files))  # tie: the smaller (more specific) folder
        if share >= 0.8 and key > best_key:
            best, best_key = folder, key
    return best


def folder_for(class_type: str, input_name: str) -> Tuple[Optional[str], str]:
    """(folder, source): source is "comfyui" (verified now), "learned" (verified earlier) or ""."""
    key = f"{class_type}.{input_name}"
    folders = folder_lists()
    options = combo_options(class_type, input_name) if folders is not None else None
    if folders is not None and options is not None:
        folder = match_folder(options, folders)
        if folder and SAFE_FOLDER.match(folder):
            _learn(key, folder)
            return folder, "comfyui"
    learned = _read_learned().get(key)
    return (learned, "learned") if learned else (None, "")


def visible_to_comfyui(class_type: str, input_name: str, value: str) -> Optional[bool]:
    """True/False when ComfyUI's option list for the input is known, None otherwise."""
    options = combo_options(class_type, input_name)
    if options is None or not options:
        return None
    return _norm(value) in set(options)


# ------------------------------------------------------------------ moving files
def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)  # same drive: instant
    except OSError:
        shutil.move(str(src), str(dst))  # another drive: copy + delete


def find_on_disk(name: str) -> Optional[Path]:
    """A model file anywhere under the models folder (any category / sub-folder)."""
    root = get_settings().models_dir
    base = _norm(name).split("/")[-1]
    direct = [root / d / Path(*_norm(name).split("/")) for d in (os.listdir(root) if root.is_dir() else [])]
    for p in direct:
        if p.is_file() and p.stat().st_size > 0:
            return p
    if root.is_dir():
        for p in root.rglob(base):
            if p.is_file() and p.stat().st_size > 0:
                return p
    return None


def relocate(name: str, folder: str, reason: str = "") -> Optional[Dict[str, Any]]:
    """Points the model's registry entry at ``folder`` and moves the file (and a .part) there."""
    from app.services.downloader import downloader
    from app.services.registry import registry

    entry = registry.get(name)
    if entry is None or (entry.get("save_dir") or "").strip():
        return None  # a custom save location chosen by the user is left alone
    if same_folder(entry.get("category", ""), folder):
        return None
    if downloader.is_active(name) or downloader.is_active(entry["name"]):
        return None
    old = registry.resolve_path(entry, name)
    if not old.is_file():
        found = find_on_disk(name)
        old = found or old
    new_entry = {**entry, "category": folder}
    new = registry.resolve_path(new_entry, name)
    moved = False
    if old.is_file() and old.resolve() != new.resolve():
        if new.is_file():
            old.unlink()  # the right folder already has it
        else:
            _move(old, new)
        moved = True
    part = old.with_name(old.name + ".part")
    if part.is_file() and not new.is_file():
        _move(part, new.with_name(new.name + ".part"))
    registry.upsert(new_entry, original_name=entry["name"])
    downloader.clear(name, entry["name"])
    invalidate()
    return {"name": name, "from": entry.get("category"), "to": folder, "moved": moved, "path": str(new), "reason": reason}


def ensure_placement(prompt: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Before a run: every model ComfyUI cannot see for its input is moved to the folder that input reads."""
    changes = []
    for row in rows:
        node = prompt.get(str(row.get("node_id"))) or {}
        ctype, inp = node.get("class_type") or row.get("class_type"), row.get("input")
        value = (node.get("inputs") or {}).get(inp, row["name"])
        if not ctype or not inp or not isinstance(value, str):
            continue
        folder, source = folder_for(ctype, inp)
        if not folder:
            continue
        if visible_to_comfyui(ctype, inp, value) is True and source == "comfyui":
            continue
        change = relocate(row["name"], folder, f"{ctype} reads '{inp}' from models/{folder}")
        if change:
            changes.append(change)
    return changes


# ------------------------------------------------------------------ ComfyUI validation errors
_NOT_IN_LIST = re.compile(
    r"Node (?P<ctype>[^\s(]+) \(ID (?P<nid>[^)]+)\) input '(?P<input>[^']+)': [^:]*: '(?P<value>[^']+)' not in \[(?P<opts>.*?)\]$"
)


def parse_value_not_in_list(details: List[str]) -> List[Dict[str, Any]]:
    """Model inputs ComfyUI refused because the file is not in the folder it reads."""
    out = []
    for d in details or []:
        m = _NOT_IN_LIST.search(str(d).strip())
        if not m:
            continue
        opts = [_norm(x) for x in re.findall(r"'([^']*)'", m.group("opts"))]
        out.append({"class_type": m.group("ctype"), "node_id": m.group("nid"), "input": m.group("input"),
                    "value": _norm(m.group("value")), "options": opts})
    return out


def fix_from_validation(details: List[str]) -> List[Dict[str, Any]]:
    """Moves models named in "value not in list" errors to the folder whose files match the list."""
    folders = folder_lists(force=True)
    changes = []
    for item in parse_value_not_in_list(details):
        if folders is None or not re.search(r"\.[A-Za-z0-9]{2,12}$", item["value"]):
            continue
        folder = match_folder(item["options"], folders)
        if not folder:
            # empty option list: the folder ComfyUI knows for this input (learned) is the best we have
            folder = _read_learned().get(f"{item['class_type']}.{item['input']}")
        if not folder:
            continue
        _learn(f"{item['class_type']}.{item['input']}", folder)
        change = relocate(item["value"], folder, f"ComfyUI: {item['class_type']} reads '{item['input']}' from models/{folder}")
        if change:
            changes.append(change)
    return changes
