from tests.app.conftest import wait_for, TMP

I2V = "builtin:wan2_1_image2video_gguf:wan2_1_image2video_gguf"
T2V = "builtin:wan2_1_text2video_gguf:wan2_1_text2video_gguf"


def _wait_run(client, run_id, timeout=20):
    return wait_for(lambda: (lambda r: r if r["status"] in ("succeeded", "failed", "cancelled") else None)(
        client.get(f"/api/runs/{run_id}").json()), timeout=timeout)


def test_builtin_templates_cover_all_tasks(client):
    data = client.get("/api/templates").json()
    by_id = {t["id"]: t for t in data["templates"]}
    assert set(data["tasks"]) == {"text_to_image", "text_to_video", "image_to_video", "image_edit"}
    assert by_id[I2V]["task"] == "image_to_video" and by_id[T2V]["task"] == "text_to_video"
    assert by_id["builtin:text2image:text2image"]["task"] == "text_to_image"
    assert by_id["builtin:omnigen2_image2image:omnigen2_image2image"]["task"] == "image_edit"
    kinds = {p["name"]: p["kind"] for p in by_id[I2V]["params"]}
    assert kinds["image_path"] == "image" and kinds["positive_prompt"] == "prompt" and kinds["seed"] == "seed"
    assert "girl.png" in client.get("/api/templates/sample-images").json()["images"]


def test_image_to_video_asks_for_models_then_generates(client, tmp_path):
    values = {"positive_prompt": "she waves", "negative_prompt": "", "image_path": {"sample": "girl.png"},
              "seed": 7, "seconds": 2, "width": 256, "height": 256}
    rows = client.post(f"/api/templates/{I2V}/models", json={"values": values}).json()["models"]
    names = {r["name"]: r["category"] for r in rows}
    assert names == {"umt5_xxl_fp8_e4m3fn_scaled.safetensors": "text_encoders", "clip_vision_h.safetensors": "clip_vision",
                     "wan_2.1_vae.safetensors": "vae", "wan2.1-i2v-14b-480p-Q4_K_M.gguf": "unet"}
    # make every model "unknown" so the run has to ask for them
    for r in rows:
        client.post("/api/models", json={"name": r["registry_name"], "url": "", "category": r["category"],
                                          "original_name": r["registry_name"]})
    r = client.post(f"/api/templates/{I2V}/generate", json={"values": values})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "models_missing"
    assert len(r.json()["detail"]["models"]) == 4
    # the user gives local files; next run links them into the models folders and runs
    items = []
    for m in r.json()["detail"]["models"]:
        f = tmp_path / m["name"]
        f.write_bytes(b"m" * 100)
        items.append({"name": m["name"], "value": str(f)})
    res = client.post(f"/api/templates/{I2V}/models/resolve", json={"items": items, "values": values})
    assert res.status_code == 200, res.text
    run = client.post(f"/api/templates/{I2V}/generate", json={"values": values}).json()
    assert run["status"] == "preparing" and run["template_id"] == I2V
    done = _wait_run(client, run["id"])
    assert done["status"] == "succeeded", done
    assert done["outputs"][0]["kind"] == "video"
    assert (TMP / "models" / "unet" / "wan2.1-i2v-14b-480p-Q4_K_M.gguf").exists()
    import tools.fake_comfyui as fake
    assert (fake.state["dir"] / "input" / "girl.png").exists()  # sample image uploaded to ComfyUI
    assert any(x["id"] == run["id"] for x in client.get(f"/api/runs?template_id={I2V}").json()["runs"])


def test_generate_validates_inputs(client):
    r = client.post(f"/api/templates/{I2V}/generate", json={"values": {"positive_prompt": "x"}})
    assert r.status_code == 400 and "input image" in r.json()["detail"].lower()
    r = client.post(f"/api/templates/{T2V}/generate", json={"values": {"positive_prompt": "", "seed": 1}})
    assert r.status_code == 400 and "Prompt" in r.json()["detail"]


def test_user_template_upload_and_run(client):
    code = (
        "from cb2c_py.lib.workflow import Workflow\n"
        "from cb2c_py.nodes.generated.emptylatentimage import EmptyLatentImage\n"
        "from cb2c_py.nodes.generated.saveimage import SaveImage\n"
        "from cb2c_py.nodes.base_node import GenericNode\n"
        "TEMPLATE = {'name': 'My Test Template', 'task': 'text_to_image'}\n"
        "def my_template(prompt: str, seed: int = 0, width: int = 64) -> Workflow:\n"
        "    wf = Workflow()\n"
        "    lat = wf.add_node(EmptyLatentImage(width=width, height=64))\n"
        "    wf.add_node(SaveImage(images=lat.outputs.latent, filename_prefix='mine'))\n"
        "    return wf\n"
    )
    up = client.post("/api/templates/upload", files={"file": ("My Template.py", code.encode(), "text/x-python")})
    assert up.status_code == 200, up.text
    t = up.json()["templates"][0]
    assert t["id"] == "user:my_template:my_template" and t["name"] == "My Test Template"
    run = client.post(f"/api/templates/{t['id']}/generate", json={"values": {"prompt": "hi"}}).json()
    done = _wait_run(client, run["id"])
    assert done["status"] == "succeeded"
    # template runs have a node view too (built from the template's prompt)
    g = client.get(f"/api/runs/{run['id']}/graph").json()
    assert sorted(n["class_type"] for n in g["nodes"]) == ["EmptyLatentImage", "SaveImage"]
    assert g["edges"][0]["type"] == "LATENT" or g["edges"][0]["source"] in {n["id"] for n in g["nodes"]}
    assert set(done["progress"]["nodes"]) == {n["id"] for n in g["nodes"]}
    bad = client.post("/api/templates/upload", files={"file": ("x.py", b"x = 1\n", "text/x-python")})
    assert bad.status_code == 400 and "No template function" in bad.json()["detail"]
    assert client.delete(f"/api/templates/{t['id']}").status_code == 200
    assert client.delete("/api/templates/builtin:text2image:text2image").status_code == 400
