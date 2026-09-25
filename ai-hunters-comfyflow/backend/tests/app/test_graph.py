import json

from tests.app.conftest import wait_for, TMP


def _sample_id(client, prefix):
    return next(s["workflow_id"] for s in client.get("/api/samples").json()["samples"] if s["file"].startswith(prefix))


def _node(graph, nid):
    return next(n for n in graph["nodes"] if n["id"] == nid)


def test_graph_roles_fields_and_edges(client):
    wid = _sample_id(client, "sd15")
    g = client.get(f"/api/workflows/{wid}/graph").json()
    roles = {n["id"]: n["role"] for n in g["nodes"]}
    assert roles == {"4": "model", "5": "generate", "6": "prompt", "7": "prompt", "3": "generate", "8": "generate", "9": "output"}
    ks = _node(g, "3")
    fields = {f["name"]: f for f in ks["fields"]}
    assert fields["sampler_name"]["control"] == "select" and "euler" in fields["sampler_name"]["options"]
    assert fields["seed"]["control"] == "seed" and not fields["seed"]["runtime"]
    assert ks["summary"] == "euler · 20 · 8"
    ckpt = {f["name"]: f for f in _node(g, "4")["fields"]}["ckpt_name"]
    assert "v1-5-pruned-emaonly-fp16.safetensors" in ckpt["options"]  # current value always offered
    assert "RealVisXL_V5.1.safetensors" in ckpt["options"]  # plus checkpoints from the model table
    assert ("6", "3", "positive", "CONDITIONING") in [(e["source"], e["target"], e["input"], e["type"]) for e in g["edges"]]
    assert _node(g, "9")["output"] == "image"


def test_save_values_regenerates_script_with_backup(client):
    wid = _sample_id(client, "sd15")
    r = client.put(f"/api/workflows/{wid}/graph", json={
        "values": {"3": {"steps": 7, "sampler_name": "dpmpp_2m"}, "6": {"text": "a lighthouse at night"}},
        "positions": {"3": {"x": 420, "y": 80}}, "outputs": {"9": "image"}, "view": "detailed",
    })
    assert r.status_code == 200, r.text
    g = r.json()
    assert {f["name"]: f["value"] for f in _node(g, "3")["fields"]}["steps"] == 7
    assert _node(g, "3")["position"] == {"x": 420, "y": 80} and g["view"] == "detailed"
    script = client.get(f"/api/workflows/{wid}/script").text
    assert "steps=7" in script and "'a lighthouse at night'" in script and "sampler_name='dpmpp_2m'" in script
    assert len(client.get(f"/api/workflows/{wid}/history").json()["history"]) >= 1
    # validation
    bad = client.put(f"/api/workflows/{wid}/graph", json={"values": {"3": {"steps": "many"}}})
    assert bad.status_code == 400 and "number" in bad.json()["detail"]
    bad = client.put(f"/api/workflows/{wid}/graph", json={"values": {"3": {"sampler_name": "nope"}}})
    assert bad.status_code == 400
    bad = client.put(f"/api/workflows/{wid}/graph", json={"values": {"3": {"model": 1}}})
    assert bad.status_code == 400 and "connected" in bad.json()["detail"]


def test_upload_field_preview_and_runtime_media(client):
    wid = _sample_id(client, "wan21_image2video")
    g = client.get(f"/api/workflows/{wid}/graph").json()
    loader = next(n for n in g["nodes"] if n["class_type"] == "LoadImage")
    img = {f["name"]: f for f in loader["fields"]}["image"]
    assert img["control"] == "upload_image" and img["runtime"] and img["label"] == "Input image"
    assert loader["role"] == "input" and loader["preview"]["kind"] == "image"
    r = client.get(loader["preview"]["url"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    params = client.get(f"/api/workflows/{wid}/parameters").json()
    assert {p["kind"] for p in params["parameters"]} >= {"image", "text"}
    assert params["outputs"][0]["type"] == "video"
    # upload a new default image in the editor (value comes from the upload modal)
    from pathlib import Path
    sample = Path(__file__).resolve().parents[3] / "samples" / "images" / "beach.png"
    up = client.post("/api/uploads", files={"file": ("beach.png", sample.read_bytes(), "image/png")}).json()
    r = client.put(f"/api/workflows/{wid}/graph", json={"values": {loader["id"]: {"image": {"upload": up["filename"]}}}})
    assert r.status_code == 200, r.text
    loader = next(n for n in r.json()["nodes"] if n["class_type"] == "LoadImage")
    assert loader["preview"]["name"] == up["filename"]
    # untick run-time for the image -> it disappears from the run screen
    client.put(f"/api/workflows/{wid}/graph", json={"fields": {loader["id"]: {"image": {"runtime": False}}}})
    kinds = {p["kind"] for p in client.get(f"/api/workflows/{wid}/parameters").json()["parameters"]}
    assert "image" not in kinds


def test_audio_upload_accepted(client):
    r = client.post("/api/uploads", files={"file": ("voice.wav", b"RIFF0000WAVE", "audio/wav")})
    assert r.status_code == 200 and r.json()["filename"].endswith(".wav")


def test_controlmap_patterns_for_unknown_nodes(client):
    from app.services import controlmap
    assert controlmap.field_rule("MyCustomLoader", "image", "IMAGE", {"image_upload": True})["control"] == "upload_image"
    assert controlmap.field_rule("SomeNode", "positive_prompt", "STRING")["control"] == "prompt"
    assert controlmap.field_rule("SomeNode", "positive_prompt", "INT") == {}
    assert controlmap.node_info("MySaveVideoCombine")["role"] == "output"
    assert controlmap.node_info("ImageUpscaleWithModel")["role"] == "generate"
    assert controlmap.node_info("VHS_VideoCombine")["output"] == "video"
    assert controlmap.node_info("SaveAudioFLAC")["output"] == "audio"
    assert controlmap.node_info("UnetLoaderGGUF")["role"] == "model"
