# AI Hunters ComfyFlow - cb2c_py/lib/model_manager.py
import os
import sys
import json
from pathlib import Path
import requests
from tqdm import tqdm
from typing import Dict, Any
from cb2c_py.lib.workflow_interface import WorkflowInterface

# A mapping from the node class to the widget name that holds the model filename.
# This might need to be expanded for other custom nodes.
NODE_MODEL_WIDGET_MAP = {
    "CheckpointLoaderSimple": "ckpt_name",
    "LoraLoader": "lora_name",
    "VAELoader": "vae_name",
    "ControlNetLoader": "control_net_name",
    "CLIPVisionLoader": "clip_name",
    "UnetLoaderGGUF": "unet_name",
    "CLIPLoader": "clip_name",
    "DualCLIPLoader": ["clip_name1", "clip_name2"],
    "NunchakuFluxDiTLoader": "model_path",
    "UNETLoader": "unet_name",
    "UpscaleModelLoader": "model_name",
    # Add other loader nodes here if needed
}


def _download_file(url: str, dest_path: str):
    """
    Downloads a file from a URL to a destination path with a progress bar.
    """
    dest_filename = os.path.basename(dest_path)
    if os.path.exists(dest_path):
        print(f"{dest_filename} ✔️")
        return

    Path(os.path.dirname(dest_path) or ".").mkdir(parents=True, exist_ok=True)

    try:
        response = requests.get(url, stream=True, allow_redirects=True)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))

        with open(dest_path, "wb") as f, tqdm(
            desc=f"Downloading {dest_filename}",
            total=total_size,
            unit="iB",
            unit_scale=True,
            unit_divisor=1024,
            file=sys.stdout,
        ) as bar:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                bar.update(len(chunk))
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}", file=sys.stderr)
        if os.path.exists(dest_path):
            os.remove(dest_path)  # Clean up partial file
        raise


class ModelManager:
    """
    Manages ComfyUI models, ensuring they are available for a workflow.
    """

    def __init__(self, models_db_path: str, models_base_dir: str):
        self.models_base_dir = models_base_dir
        self.models_db = self._load_models_db(models_db_path)

    def _load_models_db(self, db_path: str) -> Dict[str, Dict[str, str]]:
        """
        Loads the model registry into ``{filename: {url, category, save_dir}}``.
        Supports the v2 list format ``{"models": [{name, url, category, save_dir}]}``
        and the legacy ``{category: {name: url}}`` / ``{category: [url, ...]}`` formats.
        """
        if not os.path.exists(db_path):
            print(f"Models manifest not found at {db_path}", file=sys.stderr)
            return {}

        with open(db_path, "r", encoding="utf-8") as file:
            j = json.load(file)

        db: Dict[str, Dict[str, str]] = {}
        if isinstance(j, dict) and isinstance(j.get("models"), list):
            for m in j["models"]:
                if m.get("name"):
                    db[m["name"]] = {
                        "url": m.get("url", ""),
                        "category": m.get("category", "checkpoints"),
                        "save_dir": m.get("save_dir", ""),
                    }
            return db
        for category, models in j.items():
            if isinstance(models, dict):
                items = models.items()
            elif isinstance(models, list):
                items = ((url.split("?")[0].rstrip("/").split("/")[-1], url) for url in models)
            else:
                continue
            for name, url in items:
                db[name] = {"url": url, "category": category, "save_dir": ""}
        return db

    def ensure_models_for_workflow(self, workflow: WorkflowInterface):
        """
        Parses a workflow, identifies required models, and downloads them if missing.
        """
        print("Checking for required models...")
        for node in workflow.nodes.values():
            node_class = node.original_name
            if node_class in NODE_MODEL_WIDGET_MAP:
                widget_names = NODE_MODEL_WIDGET_MAP[node_class]
                if not isinstance(widget_names, list):
                    widget_names = [widget_names]

                for widget_name in widget_names:
                    model_filename = node.input_values.get(widget_name)

                    if model_filename:
                        self._check_and_download_model(model_filename)

    def _check_and_download_model(self, model_filename: str):
        """
        Checks if a model exists and downloads it if not.
        """
        if model_filename in self.models_db:
            model_info = self.models_db[model_filename]
            base = model_info.get("save_dir") or os.path.join(
                self.models_base_dir, model_info["category"]
            )
            dest_path = os.path.join(base, model_filename)

            if not os.path.exists(dest_path):
                print(f"Model '{model_filename}' not found. Downloading...")
                _download_file(model_info["url"], dest_path)
            else:
                print(f"Model '{model_filename}' found. ✔️")
        else:
            print(
                f"Warning: Model '{model_filename}' not found in model db.",
                file=sys.stderr,
            )
