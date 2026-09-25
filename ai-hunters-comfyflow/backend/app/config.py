"""Settings loaded from the project-root ``.env`` file (the only source of ports)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = Path(os.environ.get("COMFYFLOW_ENV_FILE", PROJECT_ROOT / ".env"))

REQUIRED_KEYS = ("BACKEND_PORT", "FRONTEND_PORT", "COMFYUI_PORT")

# Keys the Settings screen may change (ports are edited in .env only).
EDITABLE_KEYS = (
    "COMFYUI_HOST",
    "COMFYUI_DIR",
    "COMFYUI_PYTHON",
    "COMFYUI_EXTRA_ARGS",
    "MODELS_DIR",
    "MAX_PARALLEL_DOWNLOADS",
    "AUTO_DOWNLOAD_MODELS",
    "HF_TOKEN",
    "CIVITAI_TOKEN",
)
SECRET_KEYS = ("HF_TOKEN", "CIVITAI_TOKEN")


class ConfigError(RuntimeError):
    pass


def _path(value: str, default: str) -> Path:
    raw = (value or default).strip().strip('"')
    if os.name != "nt":
        raw = raw.replace("\\", "/")
    p = Path(raw)
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _int(values: Dict[str, Optional[str]], key: str) -> int:
    raw = (values.get(key) or "").strip()
    if not raw.isdigit():
        raise ConfigError(f"{key} is missing or not a number in {ENV_PATH}. Run Setup.bat to create .env.")
    return int(raw)


@dataclass
class Settings:
    app_env: str
    backend_host: str
    backend_port: int
    frontend_port: int
    comfyui_host: str
    comfyui_port: int
    comfyui_dir: Path
    comfyui_python: Path
    comfyui_extra_args: str
    models_dir: Path
    models_dir_custom: bool
    data_dir: Path
    max_parallel_downloads: int
    auto_download_models: bool
    hf_token: str
    civitai_token: str

    @property
    def comfyui_address(self) -> str:
        return f"{self.comfyui_host}:{self.comfyui_port}"

    @property
    def comfyui_url(self) -> str:
        return f"http://{self.comfyui_address}"

    @property
    def models_db_path(self) -> Path:
        return self.data_dir / "models.json"

    def public(self) -> Dict[str, object]:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Path):
                d[k] = str(v)
        for k in ("hf_token", "civitai_token"):
            d[k] = ("•" * 8 + d[k][-4:]) if d[k] else ""
        d["comfyui_url"] = self.comfyui_url
        return d


_lock = threading.Lock()
_settings: Optional[Settings] = None


def load_settings() -> Settings:
    if not ENV_PATH.exists():
        raise ConfigError(f"{ENV_PATH} not found. Run Setup.bat (it copies .env.example to .env).")
    v = dotenv_values(ENV_PATH)
    for key in REQUIRED_KEYS:
        _int(v, key)
    comfy_dir = _path(v.get("COMFYUI_DIR", ""), "comfyui/ComfyUI")
    models_raw = (v.get("MODELS_DIR") or "").strip()
    return Settings(
        app_env=(v.get("APP_ENV") or "production").strip(),
        backend_host=(v.get("BACKEND_HOST") or "127.0.0.1").strip(),
        backend_port=_int(v, "BACKEND_PORT"),
        frontend_port=_int(v, "FRONTEND_PORT"),
        comfyui_host=(v.get("COMFYUI_HOST") or "127.0.0.1").strip(),
        comfyui_port=_int(v, "COMFYUI_PORT"),
        comfyui_dir=comfy_dir,
        comfyui_python=_path(v.get("COMFYUI_PYTHON", ""), "comfyui/venv/Scripts/python.exe"),
        comfyui_extra_args=(v.get("COMFYUI_EXTRA_ARGS") or "").strip(),
        models_dir=_path(models_raw, str(comfy_dir / "models")),
        models_dir_custom=bool(models_raw),
        data_dir=_path(v.get("DATA_DIR", ""), "data"),
        max_parallel_downloads=max(1, min(8, int((v.get("MAX_PARALLEL_DOWNLOADS") or "2").strip() or 2))),
        auto_download_models=(v.get("AUTO_DOWNLOAD_MODELS") or "true").strip().lower() == "true",
        hf_token=(v.get("HF_TOKEN") or "").strip(),
        civitai_token=(v.get("CIVITAI_TOKEN") or "").strip(),
    )


def get_settings() -> Settings:
    global _settings
    with _lock:
        if _settings is None:
            _settings = load_settings()
        return _settings


def reload_settings() -> Settings:
    global _settings
    with _lock:
        _settings = load_settings()
        return _settings


def update_env(updates: Dict[str, str]) -> Settings:
    """Writes the given keys back into .env, preserving comments and order."""
    bad = [k for k in updates if k not in EDITABLE_KEYS]
    if bad:
        raise ConfigError(f"These settings can only be changed in .env: {', '.join(bad)}")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            lines[i] = f"{key}={remaining.pop(key)}"
    for key, value in remaining.items():
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return reload_settings()
