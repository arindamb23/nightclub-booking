"""Models a node downloads itself by Hugging Face repo id (HunyuanVideo's llava text encoder, CLIP-L)."""
import json

from app.config import get_settings
from app.services import downloader as dl_module, workflows
from tests.app.conftest import wait_for

PROMPT = {
    "1": {"class_type": "HyVideoModelLoader", "inputs": {"model": "hunyuan_video_720_cfgdistill_fp8_e4m3fn.safetensors"}},
    "16": {"class_type": "DownloadAndLoadHyVideoTextEncoder",
           "inputs": {"llm_model": "Kijai/llava-test-encoder", "clip_model": "openai/clip-test", "precision": "fp16"}},
    "20": {"class_type": "SomeOtherNode", "inputs": {"repo_id": "someone/their-model"}},
    "30": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat/dog photo"}},
}


def _fake_hf(files_dir, repo, files):
    tree = files_dir / "api" / "models" / repo / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    (tree / "main").write_text(json.dumps([{"type": "directory", "path": "sub"}] + [
        {"type": "file", "path": p, "size": len(data)} for p, data in files.items()]), encoding="utf-8")
    for p, data in files.items():
        f = files_dir / repo / "resolve" / "main" / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)


def test_repo_models_are_listed_and_downloaded_where_the_node_looks(client, files_dir, files_url, monkeypatch):
    monkeypatch.setattr(dl_module, "HF_BASE", files_url)
    _fake_hf(files_dir, "Kijai/llava-test-encoder", {"config.json": b"{}", "model-00001.safetensors": b"w" * 4096,
                                                      "sub/tokenizer.json": b"t" * 100})
    rows = {r["name"]: r for r in workflows.detect_models_in_prompt(PROMPT)}
    llm, clip, other = rows["Kijai/llava-test-encoder"], rows["openai/clip-test"], rows["someone/their-model"]
    assert "a cat/dog photo" not in rows  # prompt text is not a repository
    comfy_models = get_settings().comfyui_dir / "models"
    assert llm["kind"] == "repo" and llm["category"] == "LLM" and llm["status"] == "missing"
    assert llm["path"] == str(comfy_models / "LLM" / "llava-test-encoder")
    assert clip["category"] == "clip" and clip["path"] == str(comfy_models / "clip" / "clip-test")
    assert other["status"] == "node"  # unknown folder: left to the node, does not block the run
    # the table's Download button: the whole repository, into the folder the node checks
    job = client.post("/api/models/download", json={"name": llm["registry_name"], "requested_name": llm["name"]}).json()
    assert job["status"] in ("queued", "downloading", "done")
    done = wait_for(lambda: (lambda j: j if j and j["status"] in ("done", "error") else None)(dl_module.downloader.job(llm["registry_name"])))
    assert done["status"] == "done", done
    target = comfy_models / "LLM" / "llava-test-encoder"
    assert (target / "model-00001.safetensors").stat().st_size == 4096 and (target / "sub" / "tokenizer.json").is_file()
    assert not (comfy_models / "LLM" / "llava-test-encoder.partial").exists()
    rows = {r["name"]: r for r in workflows.detect_models_in_prompt(PROMPT)}
    assert rows["Kijai/llava-test-encoder"]["status"] == "ready" and rows["Kijai/llava-test-encoder"]["size"] > 4096


def test_missing_repository_is_a_clear_error(client, files_url, monkeypatch):
    monkeypatch.setattr(dl_module, "HF_BASE", files_url)
    rows = {r["name"]: r for r in workflows.detect_models_in_prompt(PROMPT)}
    key = rows["openai/clip-test"]["registry_name"]
    dl_module.downloader.start(key)
    done = wait_for(lambda: (lambda j: j if j and j["status"] in ("done", "error") else None)(dl_module.downloader.job(key)))
    assert done["status"] == "error" and "not found" in done["error"]
