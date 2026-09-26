"""Known run errors with a one-click fix (config/known-fixes.json).

A run that fails with a matching error gets ``error_code = "known_fix"`` and the fix's title / explanation; the UI
offers "Apply fix & run again": the actions run (pip into ComfyUI's Python, git pull of a custom node), ComfyUI
restarts, the run starts again.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Dict, List, Optional

from app.config import PROJECT_ROOT
from app.events import bus

FIXES_FILE = PROJECT_ROOT / "config" / "known-fixes.json"
CONSTRAINTS_FILE = PROJECT_ROOT / "config" / "python-constraints.txt"
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


class FixError(ValueError):
    pass


def constraint_args() -> List[str]:
    """``-c config/python-constraints.txt`` for every pip install into ComfyUI's Python."""
    return ["-c", str(CONSTRAINTS_FILE)] if CONSTRAINTS_FILE.is_file() else []


def _load() -> List[Dict[str, Any]]:
    try:
        return json.loads(FIXES_FILE.read_text(encoding="utf-8")).get("fixes") or []
    except (OSError, ValueError):
        return []


def _fill(text: str, values: Dict[str, str]) -> str:
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def match(text: str) -> Optional[Dict[str, Any]]:
    """The first known fix whose pattern matches the error text (placeholders filled from named groups)."""
    for fix in _load():
        try:
            m = re.search(fix.get("match") or "$^", text or "")
        except re.error:
            continue
        if not m:
            continue
        values = {k: v for k, v in m.groupdict().items() if v}
        if "module" in values:
            values.setdefault("package", (fix.get("packages") or {}).get(values["module"], values["module"]))
        actions = [{**a, "args": [_fill(x, values) for x in a.get("args") or []]} for a in fix.get("actions") or []]
        return {"id": fix["id"], "title": _fill(fix.get("title", ""), values), "explain": _fill(fix.get("explain", ""), values),
                "actions": actions, "restart": bool(fix.get("restart", True)), "values": values}
    return None


def _publish(job: Dict[str, Any]) -> None:
    bus.publish({"type": "fix", **{k: v for k, v in job.items() if k != "log"}, "log": job["log"][-15:]})


def apply(fix: Dict[str, Any]) -> Dict[str, Any]:
    """Runs a matched fix in the background (one at a time)."""
    with _lock:
        cur = _jobs.get(fix["id"])
        if cur and cur["status"] in ("running", "restarting"):
            return {k: v for k, v in cur.items() if k != "log"}
        job = {"id": fix["id"], "title": fix["title"], "status": "running", "error": "", "log": [], "started": time.time()}
        _jobs[fix["id"]] = job
    threading.Thread(target=_worker, args=(job, fix), daemon=True, name=f"fix-{fix['id']}").start()
    _publish(job)
    return {k: v for k, v in job.items() if k != "log"}


def _worker(job: Dict[str, Any], fix: Dict[str, Any]) -> None:
    from app.services import nodepacks

    try:
        for action in fix["actions"]:
            if action.get("type") == "pip":
                args = [a for a in action.get("args") or [] if a]
                if not args or any(a.startswith("-") and a not in ("-U", "--upgrade") for a in args):
                    raise FixError("Invalid pip arguments in known-fixes.json.")
                nodepacks._run(job, [nodepacks._python(), "-m", "pip", "install", "--disable-pip-version-check", *args],
                               publish=_publish)
            elif action.get("type") == "update_node":
                folder = nodepacks.custom_nodes_dir() / nodepacks.repo_folder(action["args"][0])
                git = nodepacks._git()
                if git and (folder / ".git").is_dir():
                    nodepacks._run(job, [git, "pull", "--ff-only"], cwd=folder, publish=_publish)
            else:
                raise FixError(f"Unknown fix action '{action.get('type')}'.")
        if fix["restart"]:
            job["status"] = "restarting"
            job["log"].append("Restarting ComfyUI…")
            _publish(job)
            state = nodepacks.restart_comfyui(wait=True)
            if state.get("status") == "error":
                raise FixError(state.get("message") or "ComfyUI did not restart.")
        job["status"] = "done"
        job["log"].append("Fixed.")
    except (FixError, nodepacks.NodePackError, OSError) as e:
        job["status"], job["error"] = "error", str(e)
        job["log"].append(f"ERROR: {e}")
    _publish(job)


def jobs() -> List[Dict[str, Any]]:
    return [{k: v for k, v in j.items() if k != "log"} | {"log": j["log"][-15:]} for j in _jobs.values()]
