"""Python engines of custom node packs that are not plain pip packages (config/node-engines.json).

Example: ComfyUI-nunchaku needs the ``nunchaku`` engine – a compiled CUDA wheel per Python / PyTorch / platform,
published through nunchaku.tech (the same list the pack's own "Nunchaku Installer" node uses). ``pip install
nunchaku`` would install an unrelated PyPI package, so that is removed first when present.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Callable, Dict, List, Optional

import requests

from app.config import PROJECT_ROOT, get_settings

ENGINES_FILE = PROJECT_ROOT / "config" / "node-engines.json"
ENV_SCRIPT = r"""
import importlib.metadata as md, json, platform, sys
def ver(n):
    try: return md.version(n)
    except md.PackageNotFoundError: return None
osn = platform.system().lower()
print(json.dumps({
  "python_version": f"cp{sys.version_info.major}{sys.version_info.minor}",
  "platform_tag": "linux_x86_64" if osn == "linux" else "win_amd64" if osn == "windows" else "unsupported",
  "torch": ver("torch"), "modules": {n: ver(n) for n in sys.argv[1:]},
}))
"""


class EngineError(ValueError):
    pass


def load() -> Dict[str, Dict[str, Any]]:
    try:
        return {k.lower(): v for k, v in json.loads(ENGINES_FILE.read_text(encoding="utf-8")).get("engines", {}).items()}
    except (OSError, ValueError):
        return {}


def for_folder(folder: str) -> Optional[Dict[str, Any]]:
    return load().get(folder.lower())


def for_module(module: str) -> Optional[Dict[str, Any]]:
    return next((e for e in load().values() if e.get("module") == module), None)


def comfy_python() -> str:
    s = get_settings()
    return str(s.comfyui_python) if s.comfyui_python.exists() else "python"


def environment(modules: List[str]) -> Dict[str, Any]:
    """Python tag, platform tag, torch and module versions of ComfyUI's own Python."""
    try:
        out = subprocess.run([comfy_python(), "-c", ENV_SCRIPT, *modules], capture_output=True, text=True, timeout=120)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
        raise EngineError(f"Could not inspect ComfyUI's Python ({comfy_python()}): {e}") from e


def _vtuple(v: str) -> tuple:
    out = []
    for part in str(v).replace("torch", "").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out)


def nunchaku_wheel(config: Dict[str, Any], env: Dict[str, Any], source: str = "github") -> Dict[str, str]:
    """Same choice as ComfyUI-nunchaku's installer: newest version, matching Python, exact or closest lower torch."""
    versions = config.get("versions") or []
    if not versions:
        raise EngineError("The Nunchaku versions list is empty.")
    if env["python_version"] not in (config.get("supported_python") or []):
        raise EngineError(f"No Nunchaku wheel for Python {env['python_version']} (supported: "
                          f"{', '.join(config.get('supported_python') or [])}).")
    if not env.get("torch"):
        raise EngineError("PyTorch is not installed in ComfyUI's Python.")
    torch_mm = "torch" + ".".join(env["torch"].split("+")[0].split(".")[:2])
    supported = config.get("supported_torch") or []
    if torch_mm in supported:
        chosen = torch_mm
    else:
        lower = sorted((t for t in supported if _vtuple(t) <= _vtuple(torch_mm)), key=_vtuple, reverse=True)
        if not lower:
            raise EngineError(f"No Nunchaku wheel for PyTorch {env['torch']} (supported: {', '.join(supported)}).")
        chosen = lower[0]
    version = versions[0]
    template, url_t = config.get("filename_template"), (config.get("url_templates") or {}).get(source)
    if not template or not url_t:
        raise EngineError("The Nunchaku versions list has no download template.")
    filename = template.format(version=version, torch_version=chosen, python_version=env["python_version"], platform=env["platform_tag"])
    tag = "v" + version.replace(".dev", "dev") if "dev" in version else "v" + version
    return {"url": url_t.format(version_tag=tag, filename=filename), "name": filename, "version": version,
            "torch": chosen, "exact_torch": str(chosen == torch_mm)}


def _versions_config(engine: Dict[str, Any], pack_dir) -> Dict[str, Any]:
    try:
        r = requests.get(engine["versions_url"], timeout=20, headers={"User-Agent": "AI-Hunters-ComfyFlow"})
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        local = pack_dir / "nunchaku_versions.json" if pack_dir else None  # written by the pack's own installer node
        if local and local.is_file():
            return json.loads(local.read_text(encoding="utf-8"))
        raise EngineError(f"Could not download the version list from {engine['versions_url']} (internet / firewall?).")


def ensure(engine: Dict[str, Any], pack_dir, run: Callable[[List[str]], None], log: Callable[[str], None]) -> bool:
    """Installs the engine into ComfyUI's Python when missing (or when the unrelated PyPI package is there)."""
    module = engine["module"]
    env = environment([module])
    have = (env.get("modules") or {}).get(module)
    wrong_below = engine.get("wrong_pypi_below")
    if have and not (wrong_below and _vtuple(have) < _vtuple(wrong_below)):
        log(f"{engine.get('title', module)} {have} is already installed.")
        return False
    py = comfy_python()
    if have:
        log(f"Removing the unrelated PyPI package '{module}' {have} (not the engine this node needs).")
        run([py, "-m", "pip", "uninstall", "-y", module])
    if engine.get("resolver") != "nunchaku_cdn":
        raise EngineError(f"Unknown engine resolver '{engine.get('resolver')}'.")
    config = _versions_config(engine, pack_dir)
    last_error = None
    for source in engine.get("sources") or ["github"]:
        try:
            wheel = nunchaku_wheel(config, env, source)
        except EngineError as e:
            raise EngineError(f"{e} See {engine.get('help', '')}") from e
        log(f"{engine.get('title', module)}: {wheel['name']} ({source})"
            + ("" if wheel["exact_torch"] == "True" else f" — built for {wheel['torch']}, closest to your PyTorch {env['torch']}"))
        try:
            run([py, "-m", "pip", "install", "--disable-pip-version-check", wheel["url"]])
            return True
        except Exception as e:  # noqa: BLE001 - try the next mirror
            last_error = e
            log(f"Download from {source} failed, trying the next mirror…")
    raise EngineError(f"Installing {module} failed: {last_error}")


def main() -> int:
    """Setup.bat: installs the engines of every installed custom node pack listed in node-engines.json."""
    import subprocess as sp

    root = get_settings().comfyui_dir / "custom_nodes"
    status = 0
    for folder, engine in load().items():
        pack = next((p for p in root.iterdir() if p.is_dir() and p.name.lower() == folder), None) if root.is_dir() else None
        if pack is None:
            continue

        def run(args):
            if sp.call(args) != 0:
                raise EngineError(f"{' '.join(args[:4])} … failed")
        try:
            ensure(engine, pack, run, lambda m: print(f"[..] {m}"))
            print(f"[OK] {engine.get('title', folder)} ready for {pack.name}")
        except EngineError as e:
            print(f"[WARN] {pack.name}: {e}")
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
