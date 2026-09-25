"""Install ComfyUI + its own venv + PyTorch + custom nodes (called by Setup.bat).

Runs with the backend venv's Python. Everything is idempotent: re-running
Setup.bat skips what is already installed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
COMFY_REPO = "https://github.com/comfyanonymous/ComfyUI.git"
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def say(msg: str) -> None:
    print(f"      {msg}", flush=True)


def resolve(value: str, default: str) -> Path:
    raw = (value or default).strip().strip('"')
    if os.name != "nt":
        raw = raw.replace("\\", "/")
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p


def run(cmd, **kw) -> int:
    say("> " + " ".join(str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd], **kw)


def set_env(key: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def base_python() -> str:
    # Inside the backend venv; create the ComfyUI venv from the base interpreter.
    return getattr(sys, "_base_executable", None) or sys.executable


def main() -> int:
    env = dotenv_values(ENV)
    comfy_dir = resolve(env.get("COMFYUI_DIR", ""), "comfyui/ComfyUI")
    comfy_py = resolve(env.get("COMFYUI_PYTHON", ""), "comfyui/venv/Scripts/python.exe")
    venv_dir = comfy_py.parent.parent

    # 1. ComfyUI source
    if (comfy_dir / "main.py").is_file():
        say(f"ComfyUI already present in {comfy_dir}")
    else:
        comfy_dir.parent.mkdir(parents=True, exist_ok=True)
        if run(["git", "clone", "--depth", "1", COMFY_REPO, comfy_dir]) != 0:
            print("[ERROR] Cloning ComfyUI failed. Check your internet connection and that Git is installed.")
            return 1

    # 2. ComfyUI virtual environment
    if not comfy_py.exists():
        if run([base_python(), "-m", "venv", venv_dir]) != 0 or not comfy_py.exists():
            print(f"[ERROR] Could not create the ComfyUI virtual environment in {venv_dir}")
            return 1
    run([comfy_py, "-m", "pip", "install", "--upgrade", "pip", "--quiet"])

    # 3. PyTorch (CUDA when an NVIDIA GPU is present, otherwise CPU)
    index = (env.get("TORCH_INDEX_URL") or "auto").strip()
    has_gpu = shutil.which("nvidia-smi") is not None
    if index.lower() == "auto":
        index = CUDA_INDEX if has_gpu else CPU_INDEX
    if not has_gpu and not (env.get("COMFYUI_EXTRA_ARGS") or "").strip():
        set_env("COMFYUI_EXTRA_ARGS", "--cpu")
        say("No NVIDIA GPU detected: ComfyUI will start with --cpu (slow, but works).")
    have_torch = subprocess.call([str(comfy_py), "-c", "import torch"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
    if have_torch:
        say("PyTorch already installed")
    else:
        say(f"Installing PyTorch from {index} (this download is large, please wait)")
        if run([comfy_py, "-m", "pip", "install", "torch", "torchvision", "torchaudio", "--index-url", index]) != 0:
            print("[ERROR] PyTorch installation failed.")
            return 1

    # 4. ComfyUI requirements
    if run([comfy_py, "-m", "pip", "install", "-r", comfy_dir / "requirements.txt"]) != 0:
        print("[ERROR] Installing ComfyUI requirements failed.")
        return 1

    # 5. Custom nodes
    nodes_file = ROOT / "config" / "custom-nodes.txt"
    custom_dir = comfy_dir / "custom_nodes"
    custom_dir.mkdir(exist_ok=True)
    failed = []
    if nodes_file.exists():
        for line in nodes_file.read_text(encoding="utf-8").splitlines():
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            name = url.rstrip("/").split("/")[-1].removesuffix(".git")
            dest = custom_dir / name
            if dest.exists():
                say(f"Custom node {name} already installed")
            elif run(["git", "clone", "--depth", "1", url, dest]) != 0:
                failed.append(name)
                continue
            req = dest / "requirements.txt"
            if req.exists() and run([comfy_py, "-m", "pip", "install", "-r", req]) != 0:
                failed.append(f"{name} (requirements)")
    if failed:
        print("[WARN] These custom nodes could not be installed: " + ", ".join(failed))

    print("[OK] ComfyUI is installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
