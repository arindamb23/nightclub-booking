import json
from pathlib import Path

import pytest

from cb2c_py.tools.convert_workflow import convert, NodeCatalog, detect_format

SAMPLE = Path(__file__).resolve().parents[3] / "samples" / "workflows" / "sd15_text2image.json"


def _run(script):
    ns = {}
    exec(compile(script, "wf", "exec"), ns)
    return ns["build_workflow"]().to_prompt()


def test_ui_sample_round_trip():
    r = convert(json.loads(SAMPLE.read_text()), "sd15", "sd15.json", NodeCatalog())
    assert r.format == "ui" and r.node_count == 7 and not r.warnings
    assert r.prompt["3"]["inputs"]["steps"] == 20  # control_after_generate skipped
    assert r.prompt["8"]["inputs"]["vae"] == ["4", 2]  # Reroute resolved
    assert r.notes and r.model_hints[0]["directory"] == "checkpoints"
    assert _run(r.script) == r.prompt


def _ui(nodes, links):
    return {"nodes": nodes, "links": links}


def test_bypass_primitive_and_muted_nodes():
    ui = _ui([
        {"id": 1, "type": "LoadImage", "widgets_values": ["a.png", "image"], "outputs": [{"links": [1]}]},
        {"id": 2, "type": "ImageInvert", "mode": 4, "inputs": [{"name": "image", "type": "IMAGE", "link": 1}]},
        {"id": 3, "type": "PrimitiveNode", "widgets_values": ["prefix_from_primitive"]},
        {"id": 4, "type": "SaveImage", "inputs": [{"name": "images", "type": "IMAGE", "link": 2},
                                                  {"name": "filename_prefix", "type": "STRING", "widget": {"name": "filename_prefix"}, "link": 3}],
         "widgets_values": ["ignored"]},
        {"id": 5, "type": "SaveImage", "mode": 2, "widgets_values": ["muted"]},
    ], [[1, 1, 0, 2, 0, "IMAGE"], [2, 2, 0, 4, 0, "IMAGE"], [3, 3, 0, 4, 1, "STRING"]])
    r = convert(ui, "t", catalog=NodeCatalog())
    assert set(r.prompt) == {"1", "4"}
    assert r.prompt["4"]["inputs"] == {"filename_prefix": "prefix_from_primitive", "images": ["1", 0]}
    assert r.prompt["1"]["inputs"] == {"image": "a.png"}
    assert _run(r.script) == r.prompt


def test_object_info_catalog_orders_widgets():
    info = {"MySampler": {"input": {"required": {"model": ["MODEL"], "seed": ["INT", {"control_after_generate": True}],
                                                 "mode": [["a", "b"]], "count": ["INT", {"forceInput": True}]}},
                          "output": ["LATENT"], "output_name": ["LATENT"]}}
    ui = _ui([{"id": 7, "type": "MySampler", "widgets_values": [5, "fixed", "b"],
               "inputs": [{"name": "model", "type": "MODEL", "link": None}]}], [])
    r = convert(ui, "t", catalog=NodeCatalog(info))
    assert r.prompt["7"]["inputs"] == {"seed": 5, "mode": "b"}
    assert "GenericNode('MySampler'" in r.script
    assert _run(r.script) == r.prompt


def test_detect_format_errors():
    with pytest.raises(ValueError):
        detect_format({"foo": 1})
    assert detect_format({"prompt": {"1": {"class_type": "X", "inputs": {}}}})[0] == "api"
