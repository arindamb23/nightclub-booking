"""Model registry: data/models.json holds name, download URL, category and save location."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings, PROJECT_ROOT, replace_with_retry

DEFAULTS_PATH = Path(__file__).resolve().parents[1] / "defaults" / "models.json"

CATEGORIES = [
    "checkpoints", "diffusion_models", "unet", "vae", "text_encoders", "clip", "clip_vision",
    "loras", "controlnet", "upscale_models", "embeddings", "style_models", "hypernetworks",
    "gligen", "photomaker", "model_patches", "audio_encoders", "vae_approx", "configs", "other",
]


class RegistryError(ValueError):
    pass


_SAFE_CATEGORY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def valid_category(category: str) -> bool:
    """The built-in categories, or any folder name ComfyUI reports (custom nodes add folders like LLM or sams)."""
    if category in CATEGORIES:
        return True
    if not _SAFE_CATEGORY.match(category or "") or category in ("..", "."):
        return False
    from app.services import modelfolders

    known = set(modelfolders.learned_folders()) | set((modelfolders._folders_cache.get("data") or {}).keys())
    return category in known or (get_settings().models_dir / category).is_dir()


def all_categories() -> List[str]:
    """Built-in categories plus the folders ComfyUI reported (custom nodes add their own)."""
    from app.services import modelfolders

    extra = set(modelfolders.learned_folders()) | set((modelfolders._folders_cache.get("data") or {}).keys())
    return CATEGORIES[:-1] + sorted(c for c in extra if c not in CATEGORIES and c not in modelfolders.SKIP_FOLDERS) + ["other"]


def is_local_source(url: str) -> bool:
    """True when the "URL" is a file on this computer (C:\\..., \\\\server\\..., /path or file://)."""
    u = (url or "").strip()
    return bool(re.match(r"^[A-Za-z]:[\\/]", u)) or u.startswith(("\\\\", "/", "file://"))


def local_source_path(url: str) -> Path:
    u = url.strip().strip('"')
    if u.lower().startswith("file:///"):
        u = u[8:] if re.match(r"^[A-Za-z]:", u[8:]) else u[7:]
    elif u.lower().startswith("file://"):
        u = u[7:]
    return Path(u if os.name == "nt" else u.replace("\\", "/"))


def _normalize_name(name: str) -> str:
    return name.strip().replace("\\", "/").lstrip("/")


class ModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: List[Dict[str, Any]] = []
        self._loaded_from: Optional[Path] = None

    # ------------------------------------------------------------ storage
    @property
    def path(self) -> Path:
        return get_settings().models_db_path

    def load(self) -> None:
        with self._lock:
            path = self.path
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(DEFAULTS_PATH, path)
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            self._models = self._migrate(data)
            self._loaded_from = path
            if not (isinstance(data, dict) and data.get("version") == 2):
                self._save()

    @staticmethod
    def _migrate(data: Any) -> List[Dict[str, Any]]:
        models: List[Dict[str, Any]] = []
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            raw = data["models"]
        elif isinstance(data, dict):  # legacy {category: {name: url}}
            raw = []
            for category, items in data.items():
                if isinstance(items, dict):
                    raw += [{"name": n, "url": u, "category": category} for n, u in items.items()]
                elif isinstance(items, list):
                    raw += [{"name": u.split("?")[0].rstrip("/").split("/")[-1], "url": u, "category": category} for u in items]
        else:
            raw = []
        seen = set()
        for m in raw:
            name = _normalize_name(str(m.get("name", "")))
            if not name or name in seen:
                continue
            seen.add(name)
            models.append({
                "name": name,
                "url": str(m.get("url", "") or "").strip(),
                "category": m.get("category") or "checkpoints",
                "save_dir": str(m.get("save_dir", "") or "").strip(),
            })
        return models

    def _save(self) -> None:
        path = self.path
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 2, "models": self._models}, indent=2), encoding="utf-8")
        replace_with_retry(tmp, path)

    def _ensure(self) -> None:
        if self._loaded_from != self.path:
            self.load()

    # ------------------------------------------------------------ queries
    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure()
            return [dict(m) for m in self._models]

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        name = _normalize_name(name)
        with self._lock:
            self._ensure()
            for m in self._models:
                if m["name"] == name:
                    return dict(m)
            # match by basename (workflows may reference "subdir/file")
            base = name.split("/")[-1]
            for m in self._models:
                if m["name"].split("/")[-1] == base:
                    return dict(m)
        return None

    def resolve_dir(self, entry: Dict[str, Any]) -> Path:
        save_dir = (entry.get("save_dir") or "").strip()
        if save_dir:
            p = Path(save_dir if os.name == "nt" else save_dir.replace("\\", "/"))
            return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()
        return get_settings().models_dir / (entry.get("category") or "checkpoints")

    def resolve_path(self, entry: Dict[str, Any], requested_name: Optional[str] = None) -> Path:
        name = _normalize_name(requested_name or entry["name"])
        return self.resolve_dir(entry).joinpath(*name.split("/"))

    def file_status(self, entry: Dict[str, Any], requested_name: Optional[str] = None) -> Dict[str, Any]:
        path = self.resolve_path(entry, requested_name)
        exists = path.is_file() and path.stat().st_size > 0
        part = path.with_name(path.name + ".part")
        partial = part.stat().st_size if not exists and part.is_file() else 0
        return {"path": str(path), "exists": exists, "size": path.stat().st_size if exists else 0, "partial": partial}

    # ------------------------------------------------------------ mutations
    def upsert(self, entry: Dict[str, Any], original_name: Optional[str] = None) -> Dict[str, Any]:
        name = _normalize_name(str(entry.get("name", "")))
        if not name:
            raise RegistryError("Model name is required.")
        url = str(entry.get("url", "") or "").strip().strip('"')
        if url and is_local_source(url):
            if not local_source_path(url).is_file():
                raise RegistryError(f"Local model file not found: {url}")
        elif url and not url.lower().startswith(("http://", "https://")):
            raise RegistryError("Enter a download URL (http:// or https://) or the full path of a model file on this computer.")
        category = entry.get("category") or "checkpoints"
        if not valid_category(category):
            raise RegistryError(f"Unknown category '{category}'.")
        new = {"name": name, "url": url, "category": category, "save_dir": str(entry.get("save_dir", "") or "").strip()}
        with self._lock:
            self._ensure()
            key = _normalize_name(original_name) if original_name else name
            idx = next((i for i, m in enumerate(self._models) if m["name"] == key), None)
            clash = next((i for i, m in enumerate(self._models) if m["name"] == name), None)
            if clash is not None and clash != idx:
                raise RegistryError(f"A model named '{name}' already exists.")
            if idx is None:
                self._models.append(new)
            else:
                self._models[idx] = new
            self._save()
        return dict(new)

    def ensure_entry(self, name: str, category: str, url: str = "") -> Dict[str, Any]:
        """Creates an entry for a detected model if unknown; fills a missing URL."""
        with self._lock:
            existing = self.get(name)
            if existing is None:
                cat = category if valid_category(category) else "checkpoints"
                return self.upsert({"name": name, "url": url, "category": cat})
            if url and not existing.get("url"):
                existing["url"] = url
                return self.upsert(existing, original_name=existing["name"])
            return existing

    def delete(self, name: str) -> None:
        name = _normalize_name(name)
        with self._lock:
            self._ensure()
            before = len(self._models)
            self._models = [m for m in self._models if m["name"] != name]
            if len(self._models) == before:
                raise RegistryError(f"Model '{name}' not found.")
            self._save()


registry = ModelRegistry()
