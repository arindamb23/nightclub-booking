"""FLUX.1 Kontext dev (Nunchaku FP4) - edit samples/images/girl.png into Ghibli style.
Needs the ComfyUI-nunchaku custom node (enable it in config/custom-nodes.txt).
Use the int4 model instead of fp4 on GPUs older than RTX 50xx."""
from pathlib import Path

import cb2c_py
from cb2c_py.lib.workflow import Workflow
from cb2c_py.templates.workflow.flux_kontext_dev_nunchaku import flux_kontext_dev_nunchaku

WORKFLOW_NAME = "FLUX Kontext Image Edit (Nunchaku)"
SAMPLE_IMAGE = Path(cb2c_py.__file__).resolve().parents[2] / "samples" / "images" / "girl.png"


def build_workflow() -> Workflow:
    return flux_kontext_dev_nunchaku(
        model="svdq-fp4_r32-flux.1-kontext-dev.safetensors",
        positive_prompt="Make the character in Ghibli style",
        seed=424242,
        steps=20,
        cfg=1.0,
        output_prefix="flux_kontext_",
        image_path1=str(SAMPLE_IMAGE),
    )
