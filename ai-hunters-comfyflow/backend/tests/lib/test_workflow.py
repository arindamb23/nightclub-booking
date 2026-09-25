import json
import pytest

from cb2c_py.lib.workflow import Workflow
from cb2c_py.nodes.base_node import GenericNode
from cb2c_py.nodes.generated.imagestitch import ImageStitch
from cb2c_py.nodes.generated.loadimage import LoadImage
from cb2c_py.nodes.generated.checkpointloadersimple import CheckpointLoaderSimple
from cb2c_py.nodes.generated.cliptextencode import CLIPTextEncode


def test_add_node_assigns_string_ids():
    wf = Workflow()
    a = wf.add_node(LoadImage(image="a.png"))
    b = wf.add_node(LoadImage(image="b.png"), node_id=10)
    c = wf.add_node(LoadImage(image="c.png"))
    assert (a.id, b.id, c.id) == ("1", "10", "2")
    assert wf.get_node(10) is b
    with pytest.raises(ValueError):
        wf.add_node(LoadImage(image="d.png"), node_id="1")


def test_links_serialize_with_output_index():
    wf = Workflow()
    ckpt = wf.add_node(CheckpointLoaderSimple(ckpt_name="m.safetensors"))
    enc = wf.add_node(CLIPTextEncode(text="hi", clip=ckpt.outputs.clip))
    prompt = wf.to_prompt()
    assert prompt[enc.id]["inputs"]["clip"] == [ckpt.id, 1]
    assert json.loads(wf.build_workflow_json())["prompt"] == prompt


def test_attributes_set_after_construction_are_serialized():
    """Regression: properties such as image2 used to be silently dropped."""
    wf = Workflow()
    a = wf.add_node(LoadImage(image="a.png"))
    b = wf.add_node(LoadImage(image="b.png"))
    b.upload = True  # runner flag, must not be sent
    stitch = wf.add_node(ImageStitch(image1=a.outputs.image))
    stitch.image2 = b.outputs.image
    stitch.title = "Stitch"
    prompt = wf.to_prompt()
    assert prompt[stitch.id]["inputs"]["image2"] == [b.id, 0]
    assert "upload" not in prompt[b.id]["inputs"]
    assert prompt[stitch.id]["_meta"] == {"title": "Stitch"}


def test_none_inputs_are_omitted():
    wf = Workflow()
    a = wf.add_node(LoadImage(image="a.png"))
    stitch = wf.add_node(ImageStitch(image1=a.outputs.image))
    assert "image2" not in wf.to_prompt()[stitch.id]["inputs"]


def test_link_to_node_not_added_raises():
    wf = Workflow()
    orphan = LoadImage(image="a.png")
    wf.add_node(ImageStitch(image1=orphan.outputs.image))
    with pytest.raises(ValueError, match="never added"):
        wf.to_prompt()


def test_generic_node_outputs():
    wf = Workflow()
    g = wf.add_node(GenericNode("MyCustom", {"strength": 0.5}))
    enc = wf.add_node(GenericNode("Consumer", {"x": g.output(2)}))
    enc.extra = 3
    p = wf.to_prompt()
    assert p[g.id] == {"inputs": {"strength": 0.5}, "class_type": "MyCustom"}
    assert p[enc.id]["inputs"] == {"x": [g.id, 2], "extra": 3}


def test_run_delegates_to_runner(mocker):
    runner = mocker.MagicMock()
    wf = Workflow(runner=runner)
    cb = mocker.MagicMock()
    wf.run(progress_callback=cb, output_dir="out")
    runner.run_workflow.assert_called_once_with(wf, cb, output_dir="out")
