"""Python engines of custom node packs that are not plain pip packages (config/node-engines.json).

Compiled CUDA packages (nunchaku, sageattention, flash-attn, triton on Windows, …) exist as separate wheels per
Python, PyTorch, CUDA and platform – or under another name on PyPI. Each engine names a *resolver*:

* ``versions_list``  – a published JSON list with file-name / URL templates (the way nunchaku.tech publishes Nunchaku)
* ``github_release`` – the .whl assets of a project's GitHub releases, chosen by parsing their file names
* ``pip_by_torch``   – a pip package (per OS) with a version range chosen by the installed PyTorch

Every install pins the installed PyTorch (``torch``, ``torchvision``, ``torchaudio``) so no wheel can replace it.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from app.config import PROJECT_ROOT, get_settings

ENGINES_FILE = PROJECT_ROOT / "config" / "node-engines.json"
GITHUB_API = "https://api.github.com"
TORCH_PACKAGES = ("torch", "torchvision", "torchaudio")
ENV_SCRIPT = r"""
import importlib.metadata as md, json, platform, sys
def ver(n):
    try: return md.version(n)
    except md.PackageNotFoundError: return None
cuda = abi = None
try:
    import torch
    cuda = torch.version.cuda
    abi = bool(torch._C._GLIBCXX_USE_CXX11_ABI)
except Exception:
    pass
osn = platform.system().lower()
print(json.dumps({
  "python_version": f"cp{sys.version_info.major}{sys.version_info.minor}",
  "os": "linux" if osn == "linux" else "win" if osn == "windows" else osn,
  "platform_tag": "linux_x86_64" if osn == "linux" else "win_amd64" if osn == "windows" else "unsupported",
  "torch": ver("torch"), "cuda": cuda, "cxx11abi": abi,
  "pinned": {n: ver(n) for n in ("torch", "torchvision", "torchaudio")},
  "modules": {n: ver(n) for n in sys.argv[1:]},
}))
"""


class EngineError(ValueError):
    pass


# ------------------------------------------------------------------ config
def load() -> Dict[str, Dict[str, Any]]:
    """{key: engine}; keys are lower-case pack folder names or engine names."""
    try:
        data = json.loads(ENGINES_FILE.read_text(encoding="utf-8")).get("engines", {})
        return {k.lower(): v for k, v in data.items()}
    except (OSError, ValueError):
        return {}


def for_folder(folder: str) -> Optional[Dict[str, Any]]:
    folder = folder.lower()
    for key, e in load().items():
        if key == folder or folder in [f.lower() for f in e.get("folders") or []]:
            return e
    return None


def for_module(module: str) -> Optional[Dict[str, Any]]:
    return next((e for e in load().values() if e.get("module") == module), None)


# ------------------------------------------------------------------ ComfyUI's Python
def comfy_python() -> str:
    s = get_settings()
    return str(s.comfyui_python) if s.comfyui_python.exists() else "python"


def environment(modules: List[str]) -> Dict[str, Any]:
    """Python / platform tags, torch + CUDA and module versions of ComfyUI's own Python."""
    try:
        out = subprocess.run([comfy_python(), "-c", ENV_SCRIPT, *modules], capture_output=True, text=True, timeout=120)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
        raise EngineError(f"Could not inspect ComfyUI's Python ({comfy_python()}): {e}") from e


def torch_pin_args(env: Optional[Dict[str, Any]] = None) -> List[str]:
    """``-c <file>``: the installed torch / torchvision / torchaudio + config/python-constraints.txt."""
    from app.services.fixes import CONSTRAINTS_FILE

    try:
        env = env or environment([])
    except EngineError:
        env = {"pinned": {}}
    lines = [f"{n}=={v}" for n, v in (env.get("pinned") or {}).items() if v]
    if CONSTRAINTS_FILE.is_file():
        lines += [l for l in CONSTRAINTS_FILE.read_text(encoding="utf-8").splitlines() if l.strip() and not l.strip().startswith("#")]
    if not lines:
        return []
    path = Path(tempfile.gettempdir()) / "comfyflow-constraints.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ["-c", str(path)]


# ------------------------------------------------------------------ versions
def _vtuple(v: str) -> tuple:
    out = []
    for part in re.split(r"[.]", str(v).replace("torch", "").split("+")[0]):
        num = re.match(r"\d+", part)
        out.append(int(num.group(0)) if num else 0)
    return tuple(out)


def torch_mm(env: Dict[str, Any]) -> str:
    if not env.get("torch"):
        raise EngineError("PyTorch is not installed in ComfyUI's Python.")
    return ".".join(env["torch"].split("+")[0].split(".")[:2])


# ------------------------------------------------------------------ wheel file names (PEP 427 + local tags)
_WHEEL = re.compile(r"^(?P<name>[^-]+)-(?P<version>[^-]+)(?:-(?P<build>\d[^-]*))?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$")


def parse_wheel(filename: str) -> Optional[Dict[str, Any]]:
    """Name, version, python/abi/platform tags and the torch / CUDA versions a wheel was built for."""
    m = _WHEEL.match(filename)
    if not m:
        return None
    w = m.groupdict()
    tags = (w["version"] + " " + filename).lower()
    t = re.search(r"torch[-_]?(\d+)\.?(\d+)", tags)
    c = re.search(r"cu(\d{2,3})(?!\d)", tags)
    w["torch"] = f"{t.group(1)}.{t.group(2)}" if t else None
    if c:
        digits = c.group(1)
        # cu128 = 12.8, cu118 = 11.8, but cu12 = "any CUDA 12" (flash-attn's Linux wheels)
        w["cuda"] = f"{digits[:-1]}.{digits[-1]}" if len(digits) == 3 else digits
    else:
        w["cuda"] = None
    a = re.search(r"cxx11abi(true|false)", tags)
    w["cxx11abi"] = None if not a else a.group(1) == "true"
    return w


def wheel_score(w: Dict[str, Any], env: Dict[str, Any]) -> Optional[Tuple]:
    """Higher is better; None = not installable here."""
    plats = w["plat"].split(".")
    if not any(p == env["platform_tag"] or p == "any" or (env["os"] == "linux" and p.startswith("manylinux") and p.endswith("x86_64")) for p in plats):
        return None
    py = env["python_version"]  # cp312
    ok_py = False
    for tag in w["py"].split("."):
        if tag == py or tag in ("py3", "py2.py3"):
            ok_py = True
        elif w["abi"] == "abi3" and tag.startswith("cp") and _vtuple(tag[2:3] + "." + tag[3:]) <= _vtuple(py[2:3] + "." + py[3:]):
            ok_py = True  # abi3 wheels work on newer Pythons
    if not ok_py:
        return None
    exact_torch = 1
    if w["torch"]:
        if w["torch"] != torch_mm(env):
            return None  # a compiled extension must match the PyTorch it was built for
        exact_torch = 2
    cuda_score = 0
    if w["cuda"]:
        if not env.get("cuda"):
            return None  # CUDA build, CPU PyTorch
        have, want = _vtuple(env["cuda"]), _vtuple(w["cuda"])
        if have[:1] != want[:1] or (len(want) > 1 and want > have):
            return None  # other CUDA major, or newer CUDA than PyTorch's
        cuda_score = 2 if len(want) > 1 and have[:2] == want[:2] else 1
    if w.get("cxx11abi") is not None and env.get("cxx11abi") is not None and w["cxx11abi"] != env["cxx11abi"]:
        return None  # Linux: must match how PyTorch was compiled
    return (exact_torch, cuda_score, _vtuple(w["version"]))


def choose_wheel(assets: List[Dict[str, str]], env: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    best, best_score = None, None
    for a in assets:
        w = parse_wheel(a["name"])
        if not w:
            continue
        score = wheel_score(w, env)
        if score is not None and (best_score is None or score > best_score):
            best, best_score = {**w, **a}, score  # the asset's file name wins over the parsed package name
    return best


# ------------------------------------------------------------------ resolvers -> pip arguments
def _pick(value: Any, env: Dict[str, Any]) -> Any:
    """A value, or {"win": …, "linux": …} per operating system."""
    return value.get(env["os"]) if isinstance(value, dict) else value


def _resolve_versions_list(engine: Dict[str, Any], env: Dict[str, Any], pack_dir) -> List[Tuple[str, str]]:
    """[(pip argument, description)] per mirror, from a versions list (nunchaku.tech)."""
    config = _fetch_json(engine["versions_url"], pack_dir / engine["local_copy"] if pack_dir and engine.get("local_copy") else None)
    versions = config.get("versions") or []
    if not versions:
        raise EngineError("The versions list is empty.")
    if env["python_version"] not in (config.get("supported_python") or []):
        raise EngineError(f"No build for Python {env['python_version']} (supported: {', '.join(config.get('supported_python') or [])}).")
    mm = "torch" + torch_mm(env)
    supported = config.get("supported_torch") or []
    if mm in supported:
        chosen = mm
    else:  # like the pack's own installer: the closest lower PyTorch it has a build for
        lower = sorted((t for t in supported if _vtuple(t) <= _vtuple(mm)), key=_vtuple, reverse=True)
        if not lower:
            raise EngineError(f"No build for PyTorch {env['torch']} (supported: {', '.join(supported)}).")
        chosen = lower[0]
    version = versions[0]
    filename = config["filename_template"].format(version=version, torch_version=chosen,
                                                  python_version=env["python_version"], platform=env["platform_tag"])
    tag = "v" + version.replace(".dev", "dev") if "dev" in version else "v" + version
    out = []
    for source in engine.get("sources") or list((config.get("url_templates") or {}).keys()):
        url_t = (config.get("url_templates") or {}).get(source)
        if url_t:
            note = "" if chosen == mm else f" — built for {chosen}, closest to your PyTorch {env['torch']}"
            out.append((url_t.format(version_tag=tag, filename=filename), f"{filename} ({source}){note}"))
    if not out:
        raise EngineError("The versions list has no download template.")
    return out


def github_assets(repo: str, releases: int = 15) -> List[Dict[str, str]]:
    r = requests.get(f"{GITHUB_API}/repos/{repo}/releases?per_page={releases}", timeout=20,
                     headers={"Accept": "application/vnd.github+json", "User-Agent": "AI-Hunters-ComfyFlow"})
    if r.status_code == 403:
        raise EngineError("GitHub's rate limit was reached (60 requests per hour without login). Try again later.")
    r.raise_for_status()
    assets = []
    for rel in r.json():
        if rel.get("draft"):
            continue
        for a in rel.get("assets") or []:
            if a.get("name", "").endswith(".whl"):
                assets.append({"name": a["name"], "url": a["browser_download_url"], "release": rel.get("tag_name", ""),
                               "prerelease": bool(rel.get("prerelease"))})
    return assets


def _resolve_github_release(engine: Dict[str, Any], env: Dict[str, Any], pack_dir) -> List[Tuple[str, str]]:
    repo = _pick(engine["repo"], env)
    if not repo:
        raise EngineError(f"No prebuilt wheels are configured for {env['os']}.")
    try:
        assets = github_assets(repo)
    except requests.RequestException as e:
        raise EngineError(f"Could not read the releases of {repo}: {e}") from e
    stable = [a for a in assets if not a["prerelease"]] or assets
    wheel = choose_wheel(stable, env) or choose_wheel(assets, env)
    if not wheel:
        seen = sorted({f"torch{w['torch']}/cu{w['cuda']}/{w['py']}/{w['plat']}" for a in assets for w in [parse_wheel(a["name"])] if w})[:12]
        raise EngineError(f"{repo} has no wheel for Python {env['python_version']}, PyTorch {env.get('torch')}, "
                          f"CUDA {env.get('cuda')}, {env['platform_tag']}. Available: {', '.join(seen) or 'none'}.")
    return [(wheel["url"], f"{wheel['name']} (GitHub {repo} {wheel['release']})")]


def _resolve_pip_by_torch(engine: Dict[str, Any], env: Dict[str, Any], pack_dir) -> List[Tuple[str, str]]:
    package = _pick(engine["package"], env)
    if not package:
        raise EngineError(f"{engine.get('title', engine['module'])} is not available for {env['os']}.")
    spec = ""
    mm = torch_mm(env)
    for torch_v, rng in (engine.get("by_torch") or {}).items():
        if torch_v == mm:
            spec = rng
    return [(package + spec, f"{package}{spec} (for PyTorch {mm})")]


RESOLVERS = {"versions_list": _resolve_versions_list, "nunchaku_cdn": _resolve_versions_list,
             "github_release": _resolve_github_release, "pip_by_torch": _resolve_pip_by_torch}


def _fetch_json(url: str, local: Optional[Path]) -> Dict[str, Any]:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "AI-Hunters-ComfyFlow"})
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        if local and local.is_file():  # e.g. nunchaku_versions.json written by the pack's own installer node
            return json.loads(local.read_text(encoding="utf-8"))
        raise EngineError(f"Could not download {url} (internet / firewall?).")


# ------------------------------------------------------------------ install
def ensure(engine: Dict[str, Any], pack_dir, run: Callable[[List[str]], None], log: Callable[[str], None]) -> bool:
    """Installs the engine into ComfyUI's Python when missing (or when an unrelated same-named package is there)."""
    module = engine["module"]
    dists = engine.get("distribution", module)
    names = list(dists.values()) if isinstance(dists, dict) else [dists]
    env = environment(names)
    dist = _pick(dists, env) or module
    have = next((v for v in ((env.get("modules") or {}).get(n) for n in names) if v), None)
    wrong_below = engine.get("wrong_pypi_below")
    title = engine.get("title", module)
    if have and not (wrong_below and _vtuple(have) < _vtuple(wrong_below)):
        log(f"{title} {have} is already installed.")
        return False
    py = comfy_python()
    if have:
        log(f"Removing the unrelated PyPI package '{dist}' {have} (not the engine this node needs).")
        run([py, "-m", "pip", "uninstall", "-y", dist])
    resolver = RESOLVERS.get(engine.get("resolver", ""))
    if resolver is None:
        raise EngineError(f"Unknown engine resolver '{engine.get('resolver')}' in node-engines.json.")
    try:
        candidates = resolver(engine, env, Path(pack_dir) if pack_dir else None)
    except EngineError as e:
        raise EngineError(f"{title}: {e}" + (f" See {engine['help']}" if engine.get("help") else "")) from e
    pins = torch_pin_args(env)
    last_error = None
    for arg, description in candidates:
        log(f"{title}: {description}")
        try:
            run([py, "-m", "pip", "install", "--disable-pip-version-check", arg, *pins])
            return True
        except Exception as e:  # noqa: BLE001 - try the next mirror
            last_error = e
            log("That download failed; trying the next source…" if len(candidates) > 1 else "")
    raise EngineError(f"Installing {title} failed: {last_error}")


def main() -> int:
    """Setup.bat: installs the engines of every installed custom node pack listed in node-engines.json."""
    import subprocess as sp

    root = get_settings().comfyui_dir / "custom_nodes"
    status = 0
    for key, engine in load().items():
        folders = [key] + [f.lower() for f in engine.get("folders") or []]
        pack = next((p for p in root.iterdir() if p.is_dir() and p.name.lower() in folders), None) if root.is_dir() else None
        if pack is None:
            continue

        def run(args):
            if sp.call(args) != 0:
                raise EngineError(f"{' '.join(str(a) for a in args[:4])} … failed")
        try:
            ensure(engine, pack, run, lambda m: m and print(f"[..] {m}"))
            print(f"[OK] {engine.get('title', key)} ready for {pack.name}")
        except EngineError as e:
            print(f"[WARN] {pack.name}: {e}")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
