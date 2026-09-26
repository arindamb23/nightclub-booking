import json
from pathlib import Path

from tests.app.conftest import wait_for, TMP

SAMPLES = Path(__file__).resolve().parents[3] / "samples"


def test_health_and_system(client):
    assert client.get("/api/health").json()["version"] == "1.0.11"
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


def _wait_run(client, run_id, timeout=20):
    return wait_for(lambda: (lambda r: r if r["status"] in ("succeeded", "failed", "cancelled") else None)(
        client.get(f"/api/runs/{run_id}").json()), timeout=timeout)


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

    # a model without a usable URL: the run is refused with the list the UI shows in a modal
    client.post("/api/models", json={"name": row["name"], "url": "", "category": "checkpoints", "original_name": row["name"]})
    r = client.post("/api/runs", json={"workflow_id": wid})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "models_missing" and detail["models"][0]["name"] == row["name"]

    # bad input is rejected, nothing is saved
    bad = client.post(f"/api/workflows/{wid}/models/resolve", json={"items": [{"name": row["name"], "value": "not a url"}]})
    assert bad.status_code == 400 and "neither a URL nor a file path" in bad.json()["detail"]

    # the user enters the URL; the next run downloads the model first, then runs by itself
    (files_dir / "sd15.bin").write_bytes(b"1" * 1024)
    res = client.post(f"/api/workflows/{wid}/models/resolve",
                      json={"items": [{"name": row["name"], "value": f"{files_url}/sd15.bin"}]}).json()
    assert res["models"][0]["url"] == f"{files_url}/sd15.bin" and res["models"][0]["status"] == "missing"

    # control map: prompts are run-time by default, seed/size are editable only
    data = client.get(f"/api/workflows/{wid}/parameters").json()
    kinds = {(p["node_id"], p["input"]): p["kind"] for p in data["parameters"]}
    assert kinds == {("6", "text"): "text", ("7", "text"): "text"}
    assert [p["label"] for p in data["parameters"]] == ["Positive Prompt", "Negative Prompt"]
    assert data["outputs"] == [{"node_id": "9", "title": "SaveImage", "type": "image"}]
    # the user ticks seed, steps and batch size as run-time in the editor
    client.put(f"/api/workflows/{wid}/graph", json={"fields": {"3": {"seed": {"runtime": True}, "steps": {"runtime": True, "label": "Quality steps"}},
                                                                 "5": {"batch_size": {"runtime": True}}}})
    kinds = {(p["node_id"], p["input"]): p["kind"] for p in client.get(f"/api/workflows/{wid}/parameters").json()["parameters"]}
    assert kinds[("3", "seed")] == "seed" and kinds[("3", "steps")] == "number" and kinds[("5", "batch_size")] == "number"

    overrides = {"6": {"text": "a red fox"}, "3": {"seed": {"random_seed": True}, "steps": 5}, "5": {"batch_size": 2}}
    run = client.post("/api/runs", json={"workflow_id": wid, "overrides": overrides}).json()
    assert run["status"] == "preparing"
    done = _wait_run(client, run["id"])
    assert done["status"] == "succeeded", done
    assert done["progress"]["models"]["ready"] == 1
    assert client.get(f"/api/workflows/{wid}/models").json()["ready"] == 1
    assert len(done["outputs"]) == 2 and all(o["kind"] == "image" for o in done["outputs"])
    f = done["outputs"][0]["filename"]
    r = client.get(f"/api/runs/{run['id']}/files/{f}?download=1")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert client.get(f"/api/runs/{run['id']}/zip").headers["content-type"] == "application/zip"
    assert client.get(f"/api/runs/{run['id']}/files/..%2F..%2F.env").status_code == 404
    assert client.get(f"/api/workflows/{wid}").json()["last_run_status"] == "succeeded"
    assert any(r["id"] == run["id"] for r in client.get(f"/api/runs?workflow_id={wid}").json()["runs"])

    # live node view: every node has a state and timings, the graph matches the workflow
    states = done["progress"]["nodes"]
    assert set(states) == {"3", "4", "5", "6", "7", "8", "9"}
    assert all(e["state"] == "done" and e["ended"] >= e["started"] for e in states.values())
    assert sorted(e["order"] for e in states.values()) == list(range(1, 8))
    assert done["progress"]["phase"] == ""
    g = client.get(f"/api/runs/{run['id']}/graph").json()
    assert {n["id"] for n in g["nodes"]} == set(states) and len(g["edges"]) >= 6
    # the sampler sent live preview frames (binary WebSocket messages)
    p = client.get(f"/api/runs/{run['id']}/preview")
    assert p.status_code == 200 and p.headers["content-type"] == "image/png" and p.content[:4] == b"\x89PNG"
    assert client.get("/api/runs/nope_1/graph").status_code == 404


def test_failed_download_asks_again_and_local_path_works(client, files_url, tmp_path):
    prompt = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "broken_url_model.safetensors"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0], "filename_prefix": "x"}},
    }
    p = tmp_path / "broken.json"
    p.write_text(json.dumps(prompt))
    wid = client.post("/api/workflows/import-path", json={"path": str(p)}).json()["id"]
    client.post(f"/api/workflows/{wid}/models/resolve",
                json={"items": [{"name": "broken_url_model.safetensors", "value": f"{files_url}/nope.bin"}]})
    run = client.post("/api/runs", json={"workflow_id": wid}).json()
    done = _wait_run(client, run["id"])
    assert done["status"] == "failed" and done["error_code"] == "models_missing"
    assert done["failed_models"][0]["name"] == "broken_url_model.safetensors" and "404" in done["failed_models"][0]["error"]
    # next attempt: the modal lists the model again
    again = client.post("/api/runs", json={"workflow_id": wid})
    assert again.status_code == 409 and again.json()["detail"]["models"][0]["status"] == "error"

    # the user points at a file already on disk (a folder works too): it is linked/copied into models\checkpoints
    local_dir = tmp_path / "my_models"
    local_dir.mkdir()
    (local_dir / "broken_url_model.safetensors").write_bytes(b"7" * 5000)
    res = client.post(f"/api/workflows/{wid}/models/resolve",
                      json={"items": [{"name": "broken_url_model.safetensors", "value": str(local_dir)}]})
    assert res.status_code == 200, res.text
    run = client.post("/api/runs", json={"workflow_id": wid}).json()
    assert _wait_run(client, run["id"])["status"] == "succeeded"
    target = TMP / "models" / "checkpoints" / "broken_url_model.safetensors"
    assert target.stat().st_size == 5000


def test_sample_library_and_python_import(client, tmp_path):
    samples = client.get("/api/samples").json()["samples"]
    files = [s["file"] for s in samples]
    assert files[0] == "sd15_text2image.json" and "wan21_image2video_gguf.py" in files and len(files) == 5
    assert all(s["workflow_id"] for s in samples)  # added to the Workflows list on first start
    names = [w["name"] for w in client.get("/api/workflows").json()["workflows"]]
    assert "Wan 2.1 Text to Video (GGUF)" in names
    again = client.post("/api/samples/open", json={"file": "sdxl_realvis_text2image.py"}).json()
    assert again["id"] == next(s["workflow_id"] for s in samples if s["file"] == "sdxl_realvis_text2image.py")
    assert again["format"] == "python" and again["node_count"] == 7

    wan = next(s for s in samples if s["file"] == "wan21_image2video_gguf.py")
    models = client.get(f"/api/workflows/{wan['workflow_id']}/models").json()["models"]
    cats = {m["name"]: m["category"] for m in models}
    assert cats["wan2.1-i2v-14b-480p-Q4_K_M.gguf"] == "unet" and cats["clip_vision_h.safetensors"] == "clip_vision"

    # an old-style script (function name other than build_workflow) opens too
    legacy = tmp_path / "legacy.py"
    legacy.write_text(
        "from cb2c_py.lib.workflow import Workflow\n"
        "from cb2c_py.nodes.generated.emptylatentimage import EmptyLatentImage\n"
        "def my_flow():\n    wf = Workflow()\n    wf.add_node(EmptyLatentImage(width=64, height=64))\n    return wf\n"
    )
    wf = client.post("/api/workflows/import-path", json={"path": str(legacy)}).json()
    assert wf["format"] == "python" and wf["node_count"] == 1
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n")
    r = client.post("/api/workflows/import-path", json={"path": str(bad)})
    assert r.status_code == 400 and "build_workflow" in r.json()["detail"]


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
    done = _wait_run(client, run["id"])
    assert done["outputs"][0]["kind"] == "video"

    bad = {"1": {"class_type": "FailNode", "inputs": {"value": 1}}}
    p2 = tmp_path / "bad.json"
    p2.write_text(json.dumps(bad))
    wf2 = client.post("/api/workflows/import-path", json={"path": str(p2)}).json()
    assert any("GenericNode" in w for w in wf2["warnings"])
    run = client.post("/api/runs", json={"workflow_id": wf2["id"]}).json()
    done = _wait_run(client, run["id"])
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


def test_run_watcher_reports_queue_and_gpu(monkeypatch):
    import threading
    from app.services import comfy as comfy_service
    from app.services.runs import RunManager

    monkeypatch.setattr(comfy_service, "stats", lambda: {"gpu": "RTX", "vram_total": 12, "vram_free": 2, "ram_total": 32, "ram_free": 8})
    monkeypatch.setattr(comfy_service, "queue", lambda: {"running": [(5, "old-job")], "pending": [(6, "x"), (7, "mine")]})
    published = []
    monkeypatch.setattr(RunManager, "_publish", staticmethod(lambda r: published.append(dict(r["progress"]))))
    monkeypatch.setattr("app.services.runs.time.sleep", lambda s: None)
    run = {"id": "r1", "comfy_prompt_id": "mine", "progress": {"node": None, "phase": ""}}
    finished = threading.Event()
    calls = {"n": 0}
    real_wait = finished.wait

    def wait(t):  # two watcher rounds, then stop
        calls["n"] += 1
        return calls["n"] > 2 or real_wait(0)
    finished.wait = wait
    RunManager()._watch(run, finished)
    prog = run["progress"]
    assert prog["queue_ahead"] == 2 and "another workflow is still running" in prog["phase"]
    assert prog["resources"]["vram_free"] == 2 and published
