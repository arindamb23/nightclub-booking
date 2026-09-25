"""Group nodes (workflow>NAME / workflow/NAME) and subgraphs are expanded like ComfyUI's UI does."""
import pytest

from cb2c_py.tools.convert_workflow import NodeCatalog, convert


def _group_workflow(type_name="workflow/FLUX"):
    inner = [
        {"index": 0, "type": "CheckpointLoaderSimple", "inputs": [],
         "outputs": [{"name": "MODEL", "type": "MODEL"}, {"name": "CLIP", "type": "CLIP"}, {"name": "VAE", "type": "VAE"}],
         "widgets_values": ["def.safetensors"]},
        {"index": 1, "type": "CLIPTextEncode", "title": "Positive", "inputs": [{"name": "clip", "type": "CLIP", "link": None}],
         "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING"}], "widgets_values": ["definition prompt"]},
        {"index": 2, "type": "KSampler", "inputs": [
            {"name": "model", "type": "MODEL", "link": None}, {"name": "positive", "type": "CONDITIONING", "link": None},
            {"name": "negative", "type": "CONDITIONING", "link": None}, {"name": "latent_image", "type": "LATENT", "link": None}],
         "outputs": [{"name": "LATENT", "type": "LATENT"}],
         "widgets_values": [1, "fixed", 20, 7, "euler", "normal", 1]},
    ]
    return {
        "nodes": [
            {"id": 28, "type": type_name, "mode": 0,
             "inputs": [{"name": "negative", "type": "CONDITIONING", "link": 11}, {"name": "latent_image", "type": "LATENT", "link": 12}],
             "outputs": [{"name": "CLIP", "type": "CLIP", "links": [10]}, {"name": "VAE", "type": "VAE", "links": [14]},
                         {"name": "LATENT", "type": "LATENT", "links": [13]}],
             "widgets_values": ["flux1-schnell.safetensors", "a red fox in snow", 42, "randomize", 4, 1.0, "euler", "simple", 1.0]},
            {"id": 7, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "type": "CLIP", "link": 10}],
             "outputs": [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [11]}], "widgets_values": ["blurry"]},
            {"id": 5, "type": "EmptyLatentImage", "inputs": [], "outputs": [{"name": "LATENT", "type": "LATENT", "links": [12]}],
             "widgets_values": [1024, 1024, 1]},
            {"id": 8, "type": "VAEDecode", "inputs": [{"name": "samples", "type": "LATENT", "link": 13}, {"name": "vae", "type": "VAE", "link": 14}],
             "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [15]}]},
            {"id": 26, "type": "PreviewImage", "title": "FLUX.1 Schnell", "inputs": [{"name": "images", "type": "IMAGE", "link": 15}], "outputs": []},
        ],
        "links": [
            [10, 28, 0, 7, 0, "CLIP"], [11, 7, 0, 28, 0, "CONDITIONING"], [12, 5, 0, 28, 1, "LATENT"],
            [13, 28, 2, 8, 0, "LATENT"], [14, 28, 1, 8, 1, "VAE"], [15, 8, 0, 26, 0, "IMAGE"],
        ],
        "extra": {"groupNodes": {"FLUX": {
            "nodes": inner,
            "links": [[0, 1, 1, 0, 1, "CLIP"], [0, 0, 2, 0, 0, "MODEL"], [1, 0, 2, 1, 1, "CONDITIONING"]],
            "external": [[0, 1, "CLIP"]],
        }}},
    }


@pytest.mark.parametrize("type_name", ["workflow/FLUX", "workflow>FLUX"])
def test_legacy_group_node_is_expanded(type_name):
    res = convert(_group_workflow(type_name), "flux", catalog=NodeCatalog())
    p = res.prompt
    assert all(not n["class_type"].startswith("workflow") for n in p.values())
    assert p["28:0"] == {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "flux1-schnell.safetensors"}}
    assert p["28:1"]["inputs"] == {"text": "a red fox in snow", "clip": ["28:0", 1]}
    ks = p["28:2"]["inputs"]
    assert ks["seed"] == 42 and ks["steps"] == 4 and ks["scheduler"] == "simple"
    assert ks["model"] == ["28:0", 0] and ks["positive"] == ["28:1", 0]
    assert ks["negative"] == ["7", 0] and ks["latent_image"] == ["5", 0]
    assert p["7"]["inputs"]["clip"] == ["28:0", 1]
    assert p["8"]["inputs"] == {"samples": ["28:2", 0], "vae": ["28:0", 2]}
    assert p["26"]["inputs"]["images"] == ["8", 0]
    assert "workflow/FLUX" not in res.script and "CheckpointLoaderSimple(" in res.script


def test_group_without_definition_is_reported():
    wf = _group_workflow()
    wf["extra"] = {}
    res = convert(wf, "flux", catalog=NodeCatalog())
    assert any("no definition" in w for w in res.warnings)
    assert all(not n["class_type"].startswith("workflow") for n in res.prompt.values())


def test_subgraph_is_expanded_with_promoted_widget():
    sg_id = "a1b2c3d4-0000-4000-8000-000000000001"
    wf = {
        "nodes": [
            {"id": 3, "type": "EmptyLatentImage", "inputs": [], "outputs": [{"name": "LATENT", "type": "LATENT", "links": [1]}],
             "widgets_values": [512, 512, 1]},
            {"id": 40, "type": sg_id, "inputs": [
                {"name": "latent", "type": "LATENT", "link": 1},
                {"name": "text", "type": "STRING", "link": None, "widget": {"name": "text"}}],
             "outputs": [{"name": "IMAGE", "type": "IMAGE", "links": [2]}], "widgets_values": ["a castle at dawn"]},
            {"id": 9, "type": "SaveImage", "inputs": [{"name": "images", "type": "IMAGE", "link": 2}], "outputs": [],
             "widgets_values": ["ComfyUI"]},
        ],
        "links": [[1, 3, 0, 40, 0, "LATENT"], [2, 40, 0, 9, 0, "IMAGE"]],
        "definitions": {"subgraphs": [{
            "id": sg_id, "name": "Generate",
            "inputs": [{"name": "latent", "type": "LATENT"}, {"name": "text", "type": "STRING"}],
            "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple", "inputs": [], "outputs": [], "widgets_values": ["sd15.safetensors"]},
                {"id": 2, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "type": "CLIP", "link": None},
                                                                {"name": "text", "type": "STRING", "link": None, "widget": {"name": "text"}}],
                 "outputs": [], "widgets_values": ["inner default"]},
                {"id": 4, "type": "KSampler", "inputs": [
                    {"name": "model", "type": "MODEL", "link": None}, {"name": "positive", "type": "CONDITIONING", "link": None},
                    {"name": "negative", "type": "CONDITIONING", "link": None}, {"name": "latent_image", "type": "LATENT", "link": None}],
                 "outputs": [], "widgets_values": [7, "fixed", 20, 8, "euler", "normal", 1]},
                {"id": 5, "type": "VAEDecode", "inputs": [{"name": "samples", "type": "LATENT", "link": None},
                                                           {"name": "vae", "type": "VAE", "link": None}], "outputs": []},
            ],
            "links": [
                {"id": 10, "origin_id": 1, "origin_slot": 1, "target_id": 2, "target_slot": 0, "type": "CLIP"},
                {"id": 11, "origin_id": -10, "origin_slot": 1, "target_id": 2, "target_slot": 1, "type": "STRING"},
                {"id": 12, "origin_id": 1, "origin_slot": 0, "target_id": 4, "target_slot": 0, "type": "MODEL"},
                {"id": 13, "origin_id": 2, "origin_slot": 0, "target_id": 4, "target_slot": 1, "type": "CONDITIONING"},
                {"id": 14, "origin_id": 2, "origin_slot": 0, "target_id": 4, "target_slot": 2, "type": "CONDITIONING"},
                {"id": 15, "origin_id": -10, "origin_slot": 0, "target_id": 4, "target_slot": 3, "type": "LATENT"},
                {"id": 16, "origin_id": 4, "origin_slot": 0, "target_id": 5, "target_slot": 0, "type": "LATENT"},
                {"id": 17, "origin_id": 1, "origin_slot": 2, "target_id": 5, "target_slot": 1, "type": "VAE"},
                {"id": 18, "origin_id": 5, "origin_slot": 0, "target_id": -20, "target_slot": 0, "type": "IMAGE"},
            ],
        }]},
    }
    res = convert(wf, "sub", catalog=NodeCatalog())
    p = res.prompt
    assert sg_id not in {n["class_type"] for n in p.values()}
    assert p["40:2"]["inputs"]["text"] == "a castle at dawn"
    assert p["40:4"]["inputs"]["latent_image"] == ["3", 0] and p["40:4"]["inputs"]["model"] == ["40:1", 0]
    assert p["9"]["inputs"]["images"] == ["40:5", 0]
    assert not any("subgraph" in w for w in res.warnings)
