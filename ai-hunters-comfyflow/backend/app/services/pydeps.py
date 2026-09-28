"""Which pip package provides a missing Python module – verified, never guessed.

``No module named 'x'`` does not say which package to install: the import name and the PyPI name often differ
(cv2 → opencv-python) and a same-named PyPI package can be an unrelated library (nunchaku). Order:

1. what the user entered before (data/module_packages.json)
2. an engine in config/node-engines.json (compiled wheels: nunchaku, sageattention, flash_attn, triton …)
3. the custom node pack's own requirements.txt – the entry that provides the module (checked like 5.)
4. config/module-packages.json (well-known import name → package name)
5. the same-named PyPI package, **only after checking its wheel really contains that module**

Nothing found → the UI asks the user for the package name.
"""
from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.config import PROJECT_ROOT, get_settings, replace_with_retry

PYPI = "https://pypi.org"
KNOWN_FILE = PROJECT_ROOT / "config" / "module-packages.json"
MAX_WHEEL = 80 * 1024 * 1024  # bigger wheels are not downloaded just to look inside
_lock = threading.Lock()


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", (name or "").strip().lower())


def _user_path() -> Path:
    return get_settings().data_dir / "module_packages.json"


def _cache_path() -> Path:
    return get_settings().data_dir / "cache" / "pypi_modules.json"


def _read(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        return {}


def _write(path: Path, data: Dict[str, Any]) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        replace_with_retry(tmp, path)


def known_packages() -> Dict[str, List[str]]:
    """{module: [package, equivalent packages…]} – the first one is installed when the pack names none of them."""
    data = _read(KNOWN_FILE)
    return {k: (v if isinstance(v, list) else [v]) for k, v in data.items() if not k.startswith("_") and v}


def save_user_package(module: str, package: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.]+", module or "") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-\[\],<>=!~ ]*", package or ""):
        raise ValueError("Enter a pip package name, e.g. opencv-python or insightface==0.7.3")
    data = _read(_user_path())
    data[module] = package.strip()
    _write(_user_path(), data)


# ------------------------------------------------------------------ requirements.txt
def requirement_names(req_file: Path) -> List[Dict[str, str]]:
    """[{name, line}] of a requirements file (options, URLs and comments skipped)."""
    out = []
    if not req_file.is_file():
        return out
    for raw in req_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if m:
            out.append({"name": m.group(1), "line": line})
    return out


# ------------------------------------------------------------------ PyPI: does package X contain module Y?
def pypi_provides(package: str, module: str, imports: Optional[List[Dict[str, Any]]] = None) -> Optional[bool]:
    """True/False when a wheel of ``package`` was inspected, None when that is not possible (no wheel, too big …).

    ``imports`` are the failing import statements from the traceback ({"module": "a.b", "names": ["X"]}): the wheel
    must contain those sub-modules and names, so a same-named but unrelated package is rejected."""
    imports = [i for i in imports or [] if i["module"].split(".", 1)[0] == module]
    key = f"{normalize(package)}::{module}::" + json.dumps(imports, sort_keys=True)
    cache = _read(_cache_path())
    if key in cache:
        return cache[key]
    try:
        r = requests.get(f"{PYPI}/pypi/{package}/json", timeout=15)
        if r.status_code == 404:
            result: Optional[bool] = False  # no such package at all
        else:
            r.raise_for_status()
            urls = [u for u in r.json().get("urls") or [] if u.get("packagetype") == "bdist_wheel"]
            # any wheel shows the file layout; prefer the smallest (pure-Python / one platform)
            urls.sort(key=lambda u: (0 if u["filename"].endswith("-none-any.whl") else 1, u.get("size") or 0))
            if not urls or (urls[0].get("size") or 0) > MAX_WHEEL:
                result = None
            else:
                data = requests.get(urls[0]["url"], timeout=120).content
                result = module in wheel_modules(data) and all(wheel_has_import(data, i) for i in imports)
    except (requests.RequestException, ValueError, zipfile.BadZipFile):
        return None  # not cached: try again next time
    cache[key] = result
    _write(_cache_path(), cache)
    return result


def wheel_has_import(data: bytes, imp: Dict[str, Any]) -> bool:
    """The wheel has the sub-module ``a.b.c`` and defines (or re-exports) each imported name."""
    parts = imp["module"].split(".")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        files = set(z.namelist())
        stem = "/".join(parts)
        candidates = [f"{stem}.py", f"{stem}/__init__.py"]
        compiled = [f for f in files if f.startswith(stem + ".") and f.endswith((".pyd", ".so"))]
        src = next((c for c in candidates if c in files), None)
        if src is None and not compiled and not any(f.startswith(stem + "/") for f in files):
            return False
        names = [n for n in imp.get("names") or [] if n != "*"]
        if not names or src is None:
            return True  # a compiled / namespace module: the sub-module existing is what can be checked
        text = z.read(src).decode("utf-8", "replace")
        for name in names:
            if re.search(rf"\b{re.escape(name)}\b", text):
                continue
            sub = f"{stem}/{name}.py" in files or f"{stem}/{name}/__init__.py" in files  # a sub-module named like it
            if not sub:
                return False
        return True


def wheel_modules(data: bytes) -> set:
    """Top-level import names inside a wheel (top_level.txt, packages and single-file modules)."""
    names = set()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.endswith(".dist-info/top_level.txt"):
                names |= {l.strip() for l in z.read(n).decode("utf-8", "replace").splitlines() if l.strip()}
            first = n.split("/", 1)[0]
            if first.endswith((".dist-info", ".data")):
                continue
            if "/" in n:
                names.add(first)
            else:
                names.add(re.split(r"[.]", first, 1)[0])  # module.py, module.cp312-win_amd64.pyd, module.so
    return names


# ------------------------------------------------------------------ the answer
def resolve_module(module: str, pack_dir: Optional[Path] = None, imports: Optional[List[Dict[str, Any]]] = None,
                   check_pypi: bool = True) -> Dict[str, Any]:
    """{package | engine, source, verified} or {package: None, reason} for a missing import name.

    ``check_pypi=False`` (the Settings page) skips downloading wheels: unanswered modules come back ``pending``."""
    from app.services import engines

    base = module.split(".", 1)[0]
    user = _read(_user_path())
    if base in user:
        return {"module": base, "package": user[base], "source": "you", "verified": True}
    engine = engines.for_module(base)
    if engine:
        return {"module": base, "engine": engine, "package": engine.get("title", base), "source": "engine", "verified": True}
    known = known_packages()
    reqs = requirement_names(pack_dir / "requirements.txt") if pack_dir else []
    aliases = {normalize(base)} | {normalize(p) for p in known.get(base, [])}
    for req in reqs:  # the pack lists it – maybe under another name (opencv-python-headless for cv2)
        if normalize(req["name"]) in aliases:
            return {"module": base, "package": req["line"], "source": "pack requirements", "verified": True}
    if not check_pypi:
        if base in known:
            return {"module": base, "package": known[base][0], "source": "known names", "verified": True}
        return {"module": base, "package": None, "pending": True, "source": "",
                "reason": "Checked on PyPI when you press Repair (the package must really contain this module)."}
    for req in reqs[:15]:
        if pypi_provides(req["name"], base, imports):
            return {"module": base, "package": req["line"], "source": "pack requirements", "verified": True}
    if base in known:
        return {"module": base, "package": known[base][0], "source": "known names", "verified": True}
    same = pypi_provides(base, base, imports)
    if same:
        return {"module": base, "package": base, "source": "PyPI (checked)", "verified": True}
    reason = (f"The PyPI package '{base}' is a different library (it does not contain the module '{base}')."
              if same is False and _exists_on_pypi(base) else
              f"No PyPI package named '{base}'." if same is False else
              f"Could not check which package provides '{base}'.")
    return {"module": base, "package": None, "source": "", "verified": False, "reason": reason + " Enter the pip package name."}


def _exists_on_pypi(package: str) -> bool:
    try:
        return requests.get(f"{PYPI}/pypi/{package}/json", timeout=10).status_code == 200
    except requests.RequestException:
        return False
