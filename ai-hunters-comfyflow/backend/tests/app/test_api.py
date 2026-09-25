import json
from pathlib import Path

from tests.app.conftest import wait_for, TMP

SAMPLES = Path(__file__).resolve().parents[3] / "samples"


def test_health_and_system(client):
    assert client.get("/api/health").json()["version"] == "1.0.0"
    s = client.get("/api/system").json()
    assert s["backend_port"] == 3015 and s["frontend_port"] == 5091
    assert s["comfyui"]["reachable"] is True


def test_settings_masks_tokens_and_blocks_ports(client):
    r = client.put("/api/settings", json={"values": {"HF_TOKEN": "hf_secret1234", "MAX_PARALLEL_DOWNLOADS": "3"}})
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["hf_token"].endswith("1234") and "secret" not in s["hf_token"]
    assert s["max_parallel_downloads"] == 3
    # masked value sent back is ignored (keeps the secret)
    client.put("/api/settings", json={"values": {"HF_TOKEN": s["hf_token"]}})
    assert "HF_TOKEN=hf_secret1234" in (TMP / ".env").read_text()
    assert client.put("/api/settings", json={"values": {"BACKEND_PORT": "1"}}).status_code == 400
    client.put("/api/settings", json={"values": {"HF_TOKEN": ""}})


def test_models_crud(client):
    models = client.get("/api/models").json()
    assert len(models["models"]) >= 17 and "checkpoints" in models["categories"]
    r = client.post("/api/models", json={"name": "test_a.safetensors", "url": "https://x.org/a", "category": "loras"})
    assert r.status_code == 200 and r.json()["status"] == "missing"
    assert r.json()["resolved_dir"].endswith("loras")
    r = client.post("/api/models", json={"name": "test_b.safetensors", "url": "https://x.org/b", "category": "loras",
                                          "save_dir": str(TMP / "custom"), "original_name": "test_a.safetensors"})
    assert r.json()["resolved_dir"] == str(TMP / "custom")
    names = [m["name"] for m in client.get("/api/models").json()["models"]]
    assert "test_b.safetensors" in names and "test_a.safetensors" not in names
    assert client.post("/api/models", json={"name": "bad", "url": "ftp://x"}).status_code == 400
    assert client.post("/api/models", json={"name": "bad", "category": "nope"}).status_code == 400
    assert client.delete("/api/models/test_b.safetensors").status_code == 200
    assert client.delete("/api/models/test_b.safetensors").status_code == 404


def test_download_to_category_folder(client, files_dir, files_url):
    (files_dir / "tiny.safetensors").write_bytes(b"0" * 300_000)
    client.post("/api/models", json={"name": "tiny.safetensors", "url": f"{files_url}/tiny.safetensors", "category": "vae"})
    r = client.post("/api/models/download", json={"name": "tiny.safetensors"})
    assert r.status_code == 200
    row = wait_for(lambda: next((m for m in client.get("/api/models").json()["models"]
                                 if m["name"] == "tiny.safetensors" and m["status"] == "ready"), None))
    assert Path(row["path"]) == TMP / "models" / "vae" / "tiny.safetensors"
    assert Path(row["path"]).stat().st_size == 300_000


def test_download_errors(client, files_url):
    client.post("/api/models", json={"name": "nourl.safetensors", "url": "", "category": "vae"})
    assert client.post("/api/models/download", json={"name": "nourl.safetensors"}).status_code == 400
    client.post("/api/models", json={"name": "gone.safetensors", "url": f"{files_url}/missing.bin", "category": "vae"})
    client.post("/api/models/download", json={"name": "gone.safetensors"})
    row = wait_for(lambda: next((m for m in client.get("/api/models").json()["models"]
                                 if m["name"] == "gone.safetensors" and m["status"] == "error"), None))
    assert "404" in row["job"]["error"]


def _import_sample(client, name="Sample SD15"):
    with open(SAMPLES / "workflows" / "sd15_text2image.json", "rb") as f:
        r = client.post("/api/workflows/upload", files={"file": ("sd15_text2image.json", f, "application/json")}, data={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def test_workflow_wizard_flow(client, files_dir, files_url):
    wf = _import_sample(client)
    wid = wf["id"]
    assert wf["format"] == "ui" and wf["node_count"] == 7
    script = client.get(f"/api/workflows/{wid}/script").text
    assert "def build_workflow()" in script and "CheckpointLoaderSimple(" in script

    models = client.get(f"/api/workflows/{wid}/models").json()
    assert models["total"] == 1
    row = models["models"][0]
    assert row["name"] == "v1-5-pruned-emaonly-fp16.safetensors" and row["category"] == "checkpoints"
    assert row["url"].startswith("https://huggingface.co")  # taken from the workflow's own model list
    assert row["status"] == "missing"

    # running is refused until models are ready
    r = client.post("/api/runs", json={"workflow_id": wid})
    assert r.status_code == 409 and "not downloaded" in r.json()["detail"]

    # point the registry at the local test server, then download
    (files_dir / "sd15.bin").write_bytes(b"1" * 1024)
    client.post("/api/models", json={"name": row["name"], "url": f"{files_url}/sd15.bin", "category": "checkpoints",
                                      "original_name": row["name"]})
    started = client.post(f"/api/workflows/{wid}/models/download-missing").json()["started"]
    assert len(started) == 1
    wait_for(lambda: client.get(f"/api/workflows/{wid}/models").json()["ready"] == 1)
    assert client.get(f"/api/workflows/{wid}").json()["models_ready"] == 1

    params = client.get(f"/api/workflows/{wid}/parameters").json()["parameters"]
    kinds = {(p["node_id"], p["input"]): p["kind"] for p in params}
    assert kinds[("6", "text")] == "text" and kinds[("3", "seed")] == "seed" and kinds[("5", "width")] == "number"

    overrides = {"6": {"text": "a red fox"}, "3": {"seed": {"random_seed": True}, "steps": 5}, "5": {"batch_size": 2}}
    run = client.post("/api/runs", json={"workflow_id": wid, "overrides": overrides}).json()
    done = wait_for(lambda: (lambda r: r if r["status"] in ("succeeded", "failed") else None)(
        client.get(f"/api/runs/{run['id']}").json()))
    assert done["status"] == "succeeded", done
    assert len(done["outputs"]) == 2 and all(o["kind"] == "image" for o in done["outputs"])
    f = done["outputs"][0]["filename"]
    r = client.get(f"/api/runs/{run['id']}/files/{f}?download=1")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/runs/{run['id']}/zip").headers["content-type"] == "application/zip"
    assert client.get(f"/api/runs/{run['id']}/files/..%2F..%2F.env").status_code == 404
    assert client.get(f"/api/workflows/{wid}").json()["last_run_status"] == "succeeded"
    assert any(r["id"] == run["id"] for r in client.get(f"/api/runs?workflow_id={wid}").json()["runs"])


def test_api_format_video_and_errors(client, tmp_path):
    prompt = {
        "1": {"class_type": "EmptyLatentImage", "inputs": {"width": 64, "height": 64, "batch_size": 1}},
        "2": {"class_type": "SaveAnimatedWEBP", "inputs": {"images": ["1", 0], "filename_prefix": "vid", "fps": 8,
                                                            "lossless": False, "quality": 80, "method": "default"}},
    }
    p = tmp_path / "video_api.json"
    p.write_text(json.dumps(prompt))
    wf = client.post("/api/workflows/import-path", json={"path": str(p)}).json()
    assert wf["format"] == "api"
    run = client.post("/api/runs", json={"workflow_id": wf["id"]}).json()
    done = wait_for(lambda: (lambda r: r if r["status"] in ("succeeded", "failed") else None)(
        client.get(f"/api/runs/{run['id']}").json()))
    assert done["outputs"][0]["kind"] == "video"

    bad = {"1": {"class_type": "FailNode", "inputs": {"value": 1}}}
    p2 = tmp_path / "bad.json"
    p2.write_text(json.dumps(bad))
    wf2 = client.post("/api/workflows/import-path", json={"path": str(p2)}).json()
    assert any("GenericNode" in w for w in wf2["warnings"])
    run = client.post("/api/runs", json={"workflow_id": wf2["id"]}).json()
    done = wait_for(lambda: (lambda r: r if r["status"] in ("succeeded", "failed") else None)(
        client.get(f"/api/runs/{run['id']}").json()))
    assert done["status"] == "failed" and "simulated validation error" in done["error_details"][0]


def test_import_errors(client, tmp_path):
    r = client.post("/api/workflows/upload", files={"file": ("x.json", b"not json", "application/json")})
    assert r.status_code == 400 and "not valid JSON" in r.json()["detail"]
    r = client.post("/api/workflows/upload", files={"file": ("x.json", b'{"a": 1}', "application/json")})
    assert r.status_code == 400 and "not a ComfyUI workflow" in r.json()["detail"]
    assert client.post("/api/workflows/import-path", json={"path": str(tmp_path / "nope.json")}).status_code == 400
    assert client.get("/api/workflows/does_not_exist").status_code == 404


def test_uploads_and_delete(client):
    png = (SAMPLES / "images" / "girl.png").read_bytes()
    up = client.post("/api/uploads", files={"file": ("my girl.png", png, "image/png")}).json()
    assert up["filename"].startswith("my_girl_") and client.get(f"/api/uploads/{up['filename']}").status_code == 200
    assert client.post("/api/uploads", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    wf = _import_sample(client, "To Delete")
    assert client.delete(f"/api/workflows/{wf['id']}").status_code == 200
    assert client.get(f"/api/workflows/{wf['id']}").status_code == 404


def test_dashboard(client):
    d = client.get("/api/dashboard").json()
    assert d["workflows"] >= 1 and d["models_total"] >= 17 and d["comfyui"]["reachable"]
