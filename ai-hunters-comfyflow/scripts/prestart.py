"""Called by Start-all.bat before ComfyUI starts: registers a custom MODELS_DIR with ComfyUI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.comfy import write_extra_model_paths  # noqa: E402

path = write_extra_model_paths()
if path:
    print(f"      Models folder registered in {path}")
