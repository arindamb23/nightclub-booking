"""Wan 2.1 image to video (14B 480p GGUF Q4_K_M) from samples/images/girl.png. Needs ComfyUI-GGUF."""
from pathlib import Path

import cb2c_py
from cb2c_py.lib.workflow import Workflow
from cb2c_py.templates.workflow.wan2_1_image2video_gguf import wan2_1_image2video_gguf

WORKFLOW_NAME = "Wan 2.1 Image to Video (GGUF)"
SAMPLE_IMAGE = Path(cb2c_py.__file__).resolve().parents[2] / "samples" / "images" / "girl.png"


def build_workflow() -> Workflow:
    wf = wan2_1_image2video_gguf(
        positive_prompt="A girl kindly smiling to the camera",
        negative_prompt="blurry, low resolution, low quality, pixelated, distorted, cartoon, deformed, glitch",
        image_path=str(SAMPLE_IMAGE),
        seed=12345,
        steps=25,
        cfg_scale=6.0,
        width=512,
        height=512,
        seconds=5,
        output_prefix="video/i2v_",
    )
    # upload the local sample image to ComfyUI before the run
    for node in wf.get_nodes():
        if node._original_name == "LoadImage":
            node.upload = True
    return wf
