"""config/controlmap.json: which node inputs are uploads / prompts / outputs, and their Run-time default."""
from __future__ import annotations

import fnmatch
import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import PROJECT_ROOT

PATH = PROJECT_ROOT / "config" / "controlmap.json"
ROLES = ("input", "prompt", "model", "generate", "output")

_lock = threading.Lock()
_cache: Dict[str, Any] = {"mtime": None, "data": {"nodes": {}, "patterns": []}}


def load() -> Dict[str, Any]:
    """Returns the control map, re-reading the file when it changes."""
    try:
        mtime = PATH.stat().st_mtime
    except OSError:
        return _cache["data"]
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                data = json.loads(PATH.read_text(encoding="utf-8"))
            except ValueError as e:
                raise ValueError(f"config/controlmap.json is not valid JSON: {e}") from e
            data.setdefault("nodes", {})
            data.setdefault("patterns", [])
            _cache.update(mtime=mtime, data=data)
        return _cache["data"]


def _match(expr: Optional[str], value: str) -> bool:
    if not expr:
        return True
    v = (value or "").lower()
    return any(fnmatch.fnmatchcase(v, g.strip().lower()) for g in str(expr).split("|") if g.strip())


def _type_matches(expected: Optional[str], input_type: Any) -> bool:
    if not expected:
        return True
    if isinstance(input_type, list):
        return expected.upper() in ("COMBO", "LIST")
    return str(input_type).upper() == expected.upper()


def node_info(class_type: str) -> Dict[str, Any]:
    """Role, icon, expected output and summary keys for a node class."""
    cm = load()
    exact = cm["nodes"].get(class_type) or {}
    info = {"role": exact.get("role"), "icon": exact.get("icon"), "output": exact.get("output"), "summary": exact.get("summary")}
    if not info["role"]:
        for p in cm["patterns"]:
            if "class_name" in p and "role" in p and not any(k in p for k in ("input_name", "input_flag")):
                if _match(p["class_name"], class_type):
                    info["role"] = p["role"]
                    break
    if info["role"] not in ROLES:
        info["role"] = "generate"
    if info["role"] == "output" and not info["output"]:
        low = class_type.lower()
        info["output"] = "audio" if "audio" in low else "video" if any(k in low for k in ("video", "animated", "webm", "gif")) else "image"
    return info


def field_rule(class_type: str, input_name: str, input_type: Any, opts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The control-map rule for one input: {control?, runtime?, label?} (empty dict = no rule)."""
    cm = load()
    exact = ((cm["nodes"].get(class_type) or {}).get("inputs") or {}).get(input_name)
    if exact:
        return dict(exact)
    opts = opts or {}
    for p in cm["patterns"]:
        if not any(k in p for k in ("input_name", "input_flag")):
            continue
        if "input_flag" in p and not opts.get(p["input_flag"]):
            continue
        if "input_name" in p and not _match(p["input_name"], input_name):
            continue
        if "class_name" in p and not _match(p["class_name"], class_type):
            continue
        if not _type_matches(p.get("type"), input_type):
            continue
        return {k: v for k, v in p.items() if k in ("control", "runtime", "label")}
    return {}
