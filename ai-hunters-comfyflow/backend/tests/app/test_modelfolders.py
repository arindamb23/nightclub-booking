"""Models land in the folder ComfyUI actually reads for each input (asked from ComfyUI, not guessed)."""
import json

import pytest

from app.config import get_settings
from app.services import modelfolders, workflows
from app.services.registry import registry

FOLDERS = {
    "checkpoints": {"sd15.safetensors"},
    "diffusion_models": {"flux1-schnell.sft", "z_image_turbo_bf16.safetensors"},
    "vae": {"ae.safetensors", "ae.sft", "wan_2.1_vae.safetensors"},
    "upscale_models": {"4x.pth"},
    "loras": set(),
}
OPTIONS = {
    ("HyVideoModelLoader", "model"): sorted(FOLDERS["diffusion_models"]),
    ("HyVideoVAELoader", "model_name"): sorted(FOLDERS["vae"]),
}


@pytest.fixture
def comfy_folders(monkeypatch):
    monkeypatch.setattr(modelfolders, "folder_lists", lambda force=False: FOLDERS)
    monkeypatch.setattr(modelfolders, "combo_options", lambda ct, inp: OPTIONS.get((ct, inp)))
    p = modelfolders._learned_path()
    if p.exists():
        p.unlink()


def test_folder_comes_from_comfyui_option_lists(comfy_folders):
    assert modelfolders.folder_for("HyVideoModelLoader", "model") == ("diffusion_models", "comfyui")
    assert modelfolders.folder_for("HyVideoVAELoader", "model_name") == ("vae", "comfyui")
    # remembered for when ComfyUI is not running
    assert json.loads(modelfolders._learned_path().read_text())["HyVideoVAELoader.model_name"] == "vae"


def test_offline_guesses_use_the_node_name():
    h = workflows._heuristic_category
    assert h("HyVideoVAELoader", "model_name") == "vae"
    assert h("HyVideoModelLoader", "model") == "diffusion_models"
    assert h("UpscaleModelLoader", "model_name") == "upscale_models"
    assert h("HyVideoLoraSelect", "lora") == "loras"
    assert h("CheckpointLoaderSimple", "ckpt_name") == "checkpoints"
    assert h("WanVideoVAELoader", "model_name") == "vae"


def test_misplaced_downloads_are_moved_when_detected(client, comfy_folders):
    models = get_settings().models_dir
    # what v1.0.10 did: VAE in upscale_models, the video model in checkpoints
    for name, cat in (("hunyuan_video_vae_bf16.safetensors", "upscale_models"),
                      ("hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors", "checkpoints")):
        registry.upsert({"name": name, "url": "https://x.org/" + name, "category": cat})
        (models / cat).mkdir(parents=True, exist_ok=True)
        (models / cat / name).write_bytes(b"x" * 64)
    prompt = {
        "1": {"class_type": "HyVideoModelLoader", "inputs": {"model": "hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors"}},
        "7": {"class_type": "HyVideoVAELoader", "inputs": {"model_name": "hunyuan_video_vae_bf16.safetensors"}},
    }
    rows = {r["name"]: r for r in workflows.detect_models_in_prompt(prompt)}
    assert rows["hunyuan_video_vae_bf16.safetensors"]["category"] == "vae"
    assert rows["hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors"]["category"] == "diffusion_models"
    assert all(r["status"] == "ready" for r in rows.values())
    assert (models / "vae" / "hunyuan_video_vae_bf16.safetensors").is_file()
    assert not (models / "upscale_models" / "hunyuan_video_vae_bf16.safetensors").exists()
    assert (models / "diffusion_models" / "hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors").is_file()


def test_comfyui_validation_error_is_understood():
    details = [
        "Node HyVideoModelLoader (ID 1) input 'model': model: 'hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors' "
        "not in ['flux1-schnell.sft', 'z_image_turbo_bf16.safetensors']",
        "Node HyVideoVAELoader (ID 7) input 'model_name': model_name: 'hunyuan_video_vae_bf16.safetensors' "
        "not in ['ae.safetensors', 'ae.sft', 'wan_2.1_vae.safetensors']",
    ]
    items = modelfolders.parse_value_not_in_list(details)
    assert [(i["class_type"], i["input"]) for i in items] == [("HyVideoModelLoader", "model"), ("HyVideoVAELoader", "model_name")]
    assert modelfolders.match_folder(items[0]["options"], FOLDERS) == "diffusion_models"
    assert modelfolders.match_folder(items[1]["options"], FOLDERS) == "vae"
    assert modelfolders.match_folder([], FOLDERS) is None


def test_run_moves_model_and_retries_after_value_not_in_list(client, comfy_folders, monkeypatch, tmp_path):
    from cb2c_py.lib.workflow_runner import ComfyUIError, WorkflowRunner
    from tests.app.test_api import _wait_run

    name = "late_vae.safetensors"
    registry.upsert({"name": name, "url": "https://x.org/v", "category": "upscale_models"})
    d = get_settings().models_dir / "upscale_models"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(b"x" * 64)
    real = WorkflowRunner.run_workflow
    calls = {"n": 0}

    def flaky(self, wf, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ComfyUIError("Prompt outputs failed validation", [
                f"Node SomeVAELoader (ID 2) input 'vae_file': vae_file: '{name}' not in ['ae.safetensors', 'ae.sft', 'wan_2.1_vae.safetensors']"])
        return real(self, wf, *a, **kw)
    monkeypatch.setattr(WorkflowRunner, "run_workflow", flaky)
    # stop the pre-run check from fixing it first, so the retry path is what is tested
    monkeypatch.setattr(modelfolders, "ensure_placement", lambda prompt, rows: [])
    prompt = {"2": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64, "batch_size": 1}},
              "9": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": "x"}}}
    p = tmp_path / "vae_api.json"
    p.write_text(json.dumps(prompt), encoding="utf-8")
    with open(p, "rb") as f:
        wf = client.post("/api/workflows/upload", files={"file": ("vae_api.json", f, "application/json")}).json()
    run = client.post("/api/runs", json={"workflow_id": wf["id"]}).json()
    done = _wait_run(client, run["id"])
    assert done["status"] == "succeeded", done
    assert calls["n"] == 2 and done["model_moves"][0]["to"] == "vae"
    assert (get_settings().models_dir / "vae" / name).is_file()
