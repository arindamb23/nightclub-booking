"""ComfyUI connection: status, node catalog cache, node sync and process start."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from app.config import get_settings
from cb2c_py.lib.workflow_runner import WorkflowRunner
from cb2c_py.tools.convert_workflow import NodeCatalog

_catalog_lock = threading.Lock()
_catalog: Optional[NodeCatalog] = None
_catalog_mtime: float = -1.0
_process: Optional[subprocess.Popen] = None


def runner() -> WorkflowRunner:
    return WorkflowRunner(get_settings().comfyui_address)


def object_info_path() -> Path:
    return get_settings().data_dir / "object_info.json"


def catalog() -> NodeCatalog:
    """NodeCatalog backed by the cached /object_info (falls back to generated wrappers)."""
    global _catalog, _catalog_mtime
    path = object_info_path()
    mtime = path.stat().st_mtime if path.exists() else 0.0
    with _catalog_lock:
        if _catalog is None or mtime != _catalog_mtime:
            info = None
            if path.exists():
                try:
                    info = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    info = None
            _catalog = NodeCatalog(info)
            _catalog_mtime = mtime
        return _catalog


def installed() -> bool:
    s = get_settings()
    return (s.comfyui_dir / "main.py").is_file()


def status() -> Dict[str, Any]:
    s = get_settings()
    result: Dict[str, Any] = {
        "url": s.comfyui_url,
        "installed": installed(),
        "dir": str(s.comfyui_dir),
        "python": str(s.comfyui_python),
        "reachable": False,
        "starting": _process is not None and _process.poll() is None,
        "version": None,
        "devices": [],
        "catalog_nodes": 0,
        "catalog_cached": object_info_path().exists(),
    }
    try:
        r = requests.get(f"{s.comfyui_url}/system_stats", timeout=2.5)
        if r.ok:
            data = r.json()
            result["reachable"] = True
            result["version"] = (data.get("system") or {}).get("comfyui_version")
            result["devices"] = [
                {"name": d.get("name"), "vram_total": d.get("vram_total"), "type": d.get("type")}
                for d in data.get("devices") or []
            ]
    except (requests.RequestException, ValueError):
        pass
    cat = catalog()
    result["catalog_nodes"] = len(cat.object_info)
    if result["reachable"] and not result["catalog_cached"]:
        threading.Thread(target=_safe_refresh_catalog, daemon=True).start()
    return result


def _safe_refresh_catalog() -> None:
    try:
        refresh_catalog()
    except Exception:  # noqa: BLE001 - background best effort
        pass


def refresh_catalog() -> int:
    """Downloads /object_info from ComfyUI into data/object_info.json."""
    info = runner().object_info()
    path = object_info_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(info), encoding="utf-8")
    os.replace(tmp, path)
    return len(info)


def sync_nodes() -> Dict[str, int]:
    """Refreshes the catalog and regenerates the typed node wrappers."""
    from cb2c_py.nodes.generate_nodes import generate_node_files

    count = refresh_catalog()
    info = json.loads(object_info_path().read_text(encoding="utf-8"))
    generated = generate_node_files(node_definitions=info, models_json_path=str(get_settings().models_db_path))
    global _catalog
    with _catalog_lock:
        _catalog = None
    import importlib

    importlib.invalidate_caches()
    return {"nodes": count, "generated": generated}


def write_extra_model_paths() -> Optional[Path]:
    """When MODELS_DIR points outside ComfyUI, tell ComfyUI where the models are."""
    s = get_settings()
    if not s.models_dir_custom or not installed():
        return None
    target = s.comfyui_dir / "extra_model_paths.yaml"
    from app.services.registry import CATEGORIES

    lines = [
        "# Written by AI Hunters ComfyFlow - models live in MODELS_DIR",
        "comfyflow:",
        f"  base_path: {s.models_dir.as_posix()}",
        "  is_default: true",
    ]
    for c in CATEGORIES:
        if c != "other":
            lines.append(f"  {c}: {c}/")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def start() -> Dict[str, Any]:
    """Starts ComfyUI in a new console window (Windows) or background process."""
    global _process
    s = get_settings()
    if not installed():
        raise RuntimeError(f"ComfyUI is not installed at {s.comfyui_dir}. Run Setup.bat first.")
    if status()["reachable"]:
        return {"started": False, "message": "ComfyUI is already running."}
    if _process is not None and _process.poll() is None:
        return {"started": False, "message": "ComfyUI is starting..."}
    python = s.comfyui_python if s.comfyui_python.exists() else Path("python")
    write_extra_model_paths()
    args = [str(python), str(s.comfyui_dir / "main.py"), "--listen", s.comfyui_host, "--port", str(s.comfyui_port)]
    if s.comfyui_extra_args:
        args += shlex.split(s.comfyui_extra_args, posix=os.name != "nt")
    kwargs: Dict[str, Any] = {"cwd": str(s.comfyui_dir)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
    else:
        log = open(s.data_dir / "comfyui.log", "ab")
        kwargs.update(stdout=log, stderr=subprocess.STDOUT)
    _process = subprocess.Popen(args, **kwargs)
    return {"started": True, "message": "ComfyUI is starting. It can take a minute the first time.", "pid": _process.pid}


def wait_until_ready(timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if status()["reachable"]:
            return True
        time.sleep(0.5)
    return False
