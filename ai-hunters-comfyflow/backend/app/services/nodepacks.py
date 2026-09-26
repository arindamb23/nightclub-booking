"""Custom nodes: find the node types a workflow needs that ComfyUI does not have, and install their packages.

Where the package of a missing node type comes from (first match wins):
1. ``data/nodepacks.json`` – what the user entered in the "Custom nodes needed" dialog;
2. the workflow itself – ComfyUI stores ``properties.aux_id`` (GitHub ``owner/repo``) and ``cnr_id`` on every node;
3. ComfyUI-Manager's ``extension-node-map.json`` (node type -> git repository, incl. ``nodename_pattern``);
4. the Comfy Registry (``https://api.comfy.org/nodes/<cnr_id>``) for a ``cnr_id`` without a repository.

Installing = ``git clone`` into ``ComfyUI/custom_nodes``, ``pip install -r requirements.txt`` (and ``install.py``)
with ComfyUI's own Python, adding the URL to ``config/custom-nodes.txt`` (so Setup.bat re-installs it), then
restarting ComfyUI and refreshing the node catalog.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from app.config import get_settings, PROJECT_ROOT, replace_with_retry
from app.events import bus
from app.services import comfy

MANAGER_MAP_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/extension-node-map.json"
MANAGER_STATS_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/github-stats.json"
REGISTRY_URL = "https://api.comfy.org/nodes/{}"
MAP_MAX_AGE = 7 * 24 * 3600
_lock = threading.Lock()
_map_cache: Dict[str, Any] = {"mtime": None, "exact": {}, "patterns": []}


class NodePackError(ValueError):
    pass


class NodesMissing(ValueError):
    """A workflow needs custom nodes that are not installed: the UI offers to install them."""

    def __init__(self, packs: List[Dict[str, Any]]):
        names = sorted({t for p in packs for t in p["class_types"]})
        super().__init__(f"{len(names)} node type(s) are not installed in ComfyUI: {', '.join(names)}.")
        self.packs = packs


# ------------------------------------------------------------------ helpers
def custom_nodes_dir() -> Path:
    return get_settings().comfyui_dir / "custom_nodes"


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", url):  # owner/repo
        url = f"https://github.com/{url}"
    url = re.sub(r"\.git$", "", url.rstrip("/"))
    if not re.match(r"^https?://", url):
        raise NodePackError(f"'{url}' is not a git repository URL (for example https://github.com/owner/repo).")
    return url


def repo_folder(url: str) -> str:
    name = normalize_url(url).rsplit("/", 1)[-1]
    if not re.fullmatch(r"[\w.-]+", name) or name in (".", ".."):
        raise NodePackError(f"Cannot derive a folder name from '{url}'.")
    return name


def _user_map_path() -> Path:
    return get_settings().data_dir / "nodepacks.json"


def _read_user_map() -> Dict[str, Dict[str, str]]:
    p = _user_map_path()
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        return {}


def save_user_mapping(class_types: Iterable[str], url: str, name: str = "") -> None:
    url = normalize_url(url)
    with _lock:
        data = _read_user_map()
        for ct in class_types:
            data[ct] = {"url": url, "name": name or repo_folder(url)}
        p = _user_map_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        replace_with_retry(tmp, p)


# ------------------------------------------------------------------ ComfyUI-Manager map
def _manager_file(name: str, url: str) -> Optional[Path]:
    """A ComfyUI-Manager data file: the local copy inside ComfyUI-Manager, else a weekly cached download."""
    local = custom_nodes_dir() / "ComfyUI-Manager" / name
    if local.is_file():
        return local
    cached = get_settings().data_dir / "cache" / name
    fresh = cached.is_file() and time.time() - cached.stat().st_mtime < MAP_MAX_AGE
    if not fresh:
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            r.json()
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(r.content)
        except (requests.RequestException, ValueError):
            pass
    return cached if cached.is_file() else None


def _manager_map_file() -> Optional[Path]:
    return _manager_file("extension-node-map.json", MANAGER_MAP_URL)


def _stars() -> Dict[str, int]:
    """GitHub stars per repository (ComfyUI-Manager's github-stats.json) to pick the original of forked packs."""
    if "stars" in _map_cache:
        return _map_cache["stars"]
    stars: Dict[str, int] = {}
    path = _manager_file("github-stats.json", MANAGER_STATS_URL)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        for url, info in data.items():
            if isinstance(info, dict):
                stars[url.rstrip("/").lower()] = int(info.get("stars") or 0)
    except (OSError, ValueError, TypeError):
        pass
    _map_cache["stars"] = stars
    return stars


def _curated() -> List[str]:
    """Packages listed in config/custom-nodes.txt (enabled or commented out) are preferred."""
    p = PROJECT_ROOT / "config" / "custom-nodes.txt"
    urls = []
    for line in p.read_text(encoding="utf-8").splitlines() if p.exists() else []:
        m = re.search(r"https?://\S+", line)
        if m:
            urls.append(m.group(0).rstrip("/").lower())
    return urls


def _best(candidates: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Orders the packages that provide one node type: curated first, then most GitHub stars."""
    curated = _curated()
    stars = _stars()

    def score(c):
        u = c["url"].rstrip("/").lower()
        return (0 if u in curated else 1, -stars.get(u, 0))

    seen, out = set(), []
    for c in sorted(candidates, key=score):
        if c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return out


def _manager_map() -> Dict[str, Any]:
    path = _manager_map_file()
    if path is None:
        return _map_cache
    mtime = (str(path), path.stat().st_mtime)
    if _map_cache["mtime"] == mtime:
        return _map_cache
    exact: Dict[str, List[Dict[str, str]]] = {}
    patterns: List[tuple] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for url, entry in data.items():
        if not isinstance(entry, list) or not entry:
            continue
        info = entry[1] if len(entry) > 1 and isinstance(entry[1], dict) else {}
        name = info.get("title_aux") or url.rstrip("/").rsplit("/", 1)[-1]
        for ct in entry[0] or []:
            exact.setdefault(ct, []).append({"url": url, "name": name})
        if info.get("nodename_pattern"):
            try:
                patterns.append((re.compile(info["nodename_pattern"]), {"url": url, "name": name}))
            except re.error:
                pass
    _map_cache.update(mtime=mtime, exact=exact, patterns=patterns)
    _map_cache.pop("stars", None)
    return _map_cache


def _registry_repo(cnr_id: str) -> Optional[str]:
    try:
        r = requests.get(REGISTRY_URL.format(cnr_id), timeout=10)
        if r.ok:
            return (r.json() or {}).get("repository") or None
    except (requests.RequestException, ValueError):
        return None
    return None


# ------------------------------------------------------------------ workflow hints
def hints_from_source(source: Any) -> Dict[str, Dict[str, str]]:
    """{class_type: {aux_id, cnr_id}} from a UI workflow (top level, group nodes and subgraphs)."""
    hints: Dict[str, Dict[str, str]] = {}
    if not isinstance(source, dict):
        return hints
    ui = source.get("workflow") if isinstance(source.get("workflow"), dict) else source
    node_lists = [ui.get("nodes") or []]
    node_lists += [g.get("nodes") or [] for g in ((ui.get("extra") or {}).get("groupNodes") or {}).values() if isinstance(g, dict)]
    node_lists += [sg.get("nodes") or [] for sg in ((ui.get("definitions") or {}).get("subgraphs") or []) if isinstance(sg, dict)]
    for nodes in node_lists:
        for n in nodes:
            if not isinstance(n, dict):
                continue
            props = n.get("properties") or {}
            ct = n.get("type") or props.get("Node name for S&R")
            if not isinstance(ct, str):
                continue
            h = {k: props[k] for k in ("aux_id", "cnr_id") if isinstance(props.get(k), str) and props.get(k)}
            if h and h.get("cnr_id") != "comfy-core":
                hints.setdefault(ct, h)
    return hints


# ------------------------------------------------------------------ detection
_jobs: Dict[str, Dict[str, Any]] = {}  # url -> install job


def _installed_folders() -> set:
    d = custom_nodes_dir()
    return {p.name.lower() for p in d.iterdir() if p.is_dir()} if d.is_dir() else set()


def known_types(refresh: bool = True) -> Optional[set]:
    """Node types ComfyUI has. None when it was never reachable (nothing can be checked)."""
    cat = comfy.catalog()
    types = set(cat.object_info)
    if refresh and comfy.status()["reachable"]:
        try:
            comfy.refresh_catalog()
            types = set(comfy.catalog().object_info)
        except Exception:  # noqa: BLE001 - keep the cached catalog
            pass
    return types or None


def missing_types(class_types: Iterable[str], refresh: bool = True) -> Optional[List[str]]:
    known = known_types(refresh)
    if known is None:
        return None
    from cb2c_py.tools.subgraphs import group_name

    return sorted({ct for ct in class_types if ct and ct not in known and group_name(ct) is None})


def resolve_packs(types: List[str], hints: Optional[Dict[str, Dict[str, str]]] = None) -> List[Dict[str, Any]]:
    """Groups missing node types by the package that provides them."""
    hints = hints or {}
    user = _read_user_map()
    mmap = _manager_map()
    installed = _installed_folders()
    packs: Dict[str, Dict[str, Any]] = {}
    alternatives: Dict[str, List[str]] = {}
    for ct in types:
        found, source = None, ""
        if ct in user:
            found, source = user[ct], "you"
        elif hints.get(ct, {}).get("aux_id"):
            aux = hints[ct]["aux_id"]
            found, source = {"url": f"https://github.com/{aux}", "name": aux.rsplit("/", 1)[-1]}, "workflow"
        elif ct in mmap["exact"]:
            ranked = _best(mmap["exact"][ct])
            found, source = ranked[0], "ComfyUI-Manager list"
            alternatives[ct] = [c["url"] for c in ranked[1:6]]
        else:
            found = next((info for rx, info in mmap["patterns"] if rx.search(ct)), None)
            source = "ComfyUI-Manager list" if found else ""
            if not found and hints.get(ct, {}).get("cnr_id"):
                repo = _registry_repo(hints[ct]["cnr_id"])
                if repo:
                    found, source = {"url": repo, "name": hints[ct]["cnr_id"]}, "Comfy Registry"
        key = normalize_url(found["url"]) if found else f"?{ct}"
        pack = packs.setdefault(key, {
            "url": key if found else "", "name": (found or {}).get("name") or ct, "source": source,
            "class_types": [], "status": "missing" if found else "no_url",
        })
        pack["class_types"].append(ct)
        pack.setdefault("alternatives", [])
        pack["alternatives"] = list(dict.fromkeys(pack["alternatives"] + [u for u in alternatives.get(ct, []) if u != key]))[:5]
    for pack in packs.values():
        if pack["url"]:
            job = _jobs.get(pack["url"])
            folder = repo_folder(pack["url"]).lower()
            if job and job["status"] in ("queued", "installing", "restarting"):
                pack["status"] = job["status"]
            elif job and job["status"] == "error":
                pack["status"], pack["error"] = "error", job.get("error", "")
            elif folder in installed:
                pack["status"] = "restart"  # files are there but ComfyUI has not loaded them (restart or broken install)
            pack["job"] = job and {k: v for k, v in job.items() if k != "log"} | {"log": job["log"][-12:]}
    return sorted(packs.values(), key=lambda p: (p["status"] == "no_url", p["name"].lower()))


def check_prompt(prompt: Dict[str, Any], hints: Optional[Dict[str, Dict[str, str]]] = None, refresh: bool = True) -> Dict[str, Any]:
    types = missing_types((n.get("class_type") for n in prompt.values()), refresh)
    if types is None:
        return {"available": False, "packs": [], "message": "Start ComfyUI to check which custom nodes are installed."}
    return {"available": True, "packs": resolve_packs(types, hints)}


def check_workflow(wid: str, refresh: bool = True) -> Dict[str, Any]:
    from app.services import workflows

    prompt = workflows._prompt(wid)
    source = workflows._root() / wid / "source.json"
    hints = hints_from_source(json.loads(source.read_text(encoding="utf-8"))) if source.is_file() else {}
    return check_prompt(prompt, hints, refresh)


# ------------------------------------------------------------------ install
def _git() -> Optional[str]:
    local = PROJECT_ROOT / "tools" / "git" / "cmd" / ("git.exe" if os.name == "nt" else "git")
    return str(local) if local.is_file() else shutil.which("git")


def _python() -> str:
    s = get_settings()
    return str(s.comfyui_python) if s.comfyui_python.exists() else "python"


def _publish(job: Dict[str, Any]) -> None:
    bus.publish({"type": "nodepack", **{k: v for k, v in job.items() if k != "log"}, "log": job["log"][-12:]})


def _run(job: Dict[str, Any], args: List[str], cwd: Optional[Path] = None, timeout: int = 1800, publish=None) -> None:
    _publish = publish or globals()["_publish"]
    job["log"].append("> " + " ".join(Path(a).name if i == 0 else a for i, a in enumerate(args)))
    _publish(job)
    kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    proc = subprocess.Popen(args, cwd=str(cwd) if cwd else None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", **kwargs)
    last = 0.0
    start = time.time()
    for line in proc.stdout:  # type: ignore[union-attr]
        line = line.rstrip()
        if line:
            job["log"].append(line[:300])
            del job["log"][:-200]
        if time.time() - last > 0.7:
            last = time.time()
            _publish(job)
        if time.time() - start > timeout:
            proc.kill()
            raise NodePackError(f"'{args[0]}' took longer than {timeout // 60} minutes and was stopped.")
    if proc.wait() != 0:
        raise NodePackError(f"{Path(args[0]).name} {' '.join(args[1:3])} failed (exit code {proc.returncode}). See the log.")


def _remember_in_setup(url: str) -> None:
    p = PROJECT_ROOT / "config" / "custom-nodes.txt"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    if any(normalize_url(l.split("#")[0].strip()) == url for l in lines if l.strip() and not l.strip().startswith("#")
           and re.match(r"^\s*(https?://|[\w.-]+/[\w.-]+\s*$)", l)):
        return
    lines.append(f"{url}  # added by ComfyFlow for a workflow")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _install(job: Dict[str, Any]) -> None:
    url = job["url"]
    target = custom_nodes_dir() / repo_folder(url)
    git = _git()
    if git is None:
        raise NodePackError("Git was not found. Run Setup.bat once (it installs a portable Git) and try again.")
    custom_nodes_dir().mkdir(parents=True, exist_ok=True)
    if (target / ".git").is_dir():
        _run(job, [git, "pull", "--ff-only"], cwd=target)
    else:
        if target.exists():
            raise NodePackError(f"{target} exists but is not a git checkout. Delete or rename it and try again.")
        _run(job, [git, "clone", "--depth", "1", url, str(target)])
    req = target / "requirements.txt"
    if req.is_file():
        from app.services.fixes import constraint_args

        _run(job, [_python(), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(req), *constraint_args()], cwd=target)
    if (target / "install.py").is_file():
        _run(job, [_python(), "install.py"], cwd=target)
    _remember_in_setup(url)


def install(url: str, class_types: Optional[List[str]] = None, name: str = "") -> Dict[str, Any]:
    url = normalize_url(url)
    if class_types:
        save_user_mapping(class_types, url, name)
    with _lock:
        job = _jobs.get(url)
        if job and job["status"] in ("queued", "installing", "restarting"):
            return {k: v for k, v in job.items() if k != "log"}
        job = {"url": url, "name": name or repo_folder(url), "status": "queued", "error": "", "log": [],
               "class_types": class_types or [], "started": time.time()}
        _jobs[url] = job
    _publish(job)
    threading.Thread(target=_worker, args=(job,), daemon=True, name=f"nodepack-{job['name']}").start()
    return {k: v for k, v in job.items() if k != "log"}


_install_lock = threading.Lock()  # one package at a time (pip installs must not overlap)


def _worker(job: Dict[str, Any]) -> None:
    with _install_lock:
        try:
            job["status"] = "installing"
            _publish(job)
            _install(job)
            job["status"] = "installed"
            job["log"].append("Installed. ComfyUI must restart to load the new nodes.")
        except (NodePackError, OSError) as e:
            job["status"], job["error"] = "error", str(e)
            job["log"].append(f"ERROR: {e}")
        _publish(job)


def jobs() -> List[Dict[str, Any]]:
    return [{k: v for k, v in j.items() if k != "log"} | {"log": j["log"][-12:]} for j in _jobs.values()]


# ------------------------------------------------------------------ restart
_restart_state: Dict[str, Any] = {"status": "idle", "message": ""}


def restart_status() -> Dict[str, Any]:
    return dict(_restart_state)


def _set_restart(status: str, message: str) -> None:
    _restart_state.update(status=status, message=message, at=time.time())
    bus.publish({"type": "comfy_restart", **_restart_state})


def restart_comfyui(wait: bool = False) -> Dict[str, Any]:
    """Restarts ComfyUI so it loads new custom nodes, then refreshes the node catalog."""
    if _restart_state["status"] == "restarting":
        return restart_status()
    _set_restart("restarting", "Restarting ComfyUI to load the new nodes…")
    t = threading.Thread(target=_restart_worker, daemon=True, name="comfy-restart")
    t.start()
    if wait:
        t.join()
    return restart_status()


def _pids_on_port(port: int) -> List[int]:
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout  # type: ignore[attr-defined]
    except (OSError, subprocess.SubprocessError):
        return []
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
            pids.add(int(parts[4]))
    return sorted(pids)


def _reconvert_unknown_node_workflows() -> None:
    """Widget values of nodes ComfyUI did not know were mapped by position; convert those workflows again."""
    from app.services import workflows

    for wf in workflows.list_all():
        try:
            meta = workflows._read_meta(wf["id"])
            unknown = any("unknown to the node catalog" in w or "not installed" in w for w in meta.get("warnings") or [])
            if unknown and not meta.get("edited_at"):
                workflows.reconvert(wf["id"], "custom nodes installed")
        except Exception:  # noqa: BLE001 - best effort
            continue


def _restart_worker() -> None:
    s = get_settings()
    try:
        was_running = comfy.status()["reachable"]
        rebooted = False
        if was_running:  # ComfyUI-Manager restarts ComfyUI in place (same window, same arguments)
            for path in ("/api/manager/reboot", "/manager/reboot"):
                try:
                    r = requests.get(f"{s.comfyui_url}{path}", timeout=5)
                    if r.status_code < 400:
                        rebooted = True
                        break
                except requests.RequestException:
                    rebooted = True  # the connection drops while it restarts
                    break
        if not rebooted:
            comfy.stop()
            for pid in _pids_on_port(s.comfyui_port):
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)  # type: ignore[attr-defined]
        # wait until it is down (up to 30 s), then until it is back (up to 5 min)
        end = time.time() + 30
        while was_running and time.time() < end and comfy.status()["reachable"]:
            time.sleep(1)
        if not rebooted:
            comfy.start()
        end = time.time() + 300
        while time.time() < end:
            if comfy.status()["reachable"]:
                break
            time.sleep(2)
        else:
            raise NodePackError("ComfyUI did not come back within 5 minutes. Check its window / console for errors.")
        comfy.sync_nodes()
        _reconvert_unknown_node_workflows()
        for job in _jobs.values():
            if job["status"] == "installed":
                job["status"] = "done"
        _set_restart("done", "ComfyUI restarted and the new nodes are loaded.")
    except Exception as e:  # noqa: BLE001 - reported to the UI
        _set_restart("error", f"Restart failed: {e}")
