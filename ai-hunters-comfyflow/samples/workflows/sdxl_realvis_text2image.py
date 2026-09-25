"""SDXL RealVisXL 5.1 - text to image (768x768, DPM++ 2M SDE Karras, 6 steps)."""
from cb2c_py.lib.workflow import Workflow
from cb2c_py.templates.workflow.text2image import text2image

WORKFLOW_NAME = "SDXL RealVis Text to Image"


def build_workflow() -> Workflow:
    return text2image(
        pos_prompt="lara croft, elder, old, 8k fujifilm, realistic, high quality, detailed, sharp focus, "
        "cinematic lighting, ultra wide angle, depth of field, bokeh",
        neg_prompt="blurry, bad quality",
        seed=123456,
        steps=6,
        width=768,
        height=768,
        ckpt_name="RealVisXL_V5.1.safetensors",
        sampler_name="dpmpp_2m_sde",
        scheduler_name="karras",
        cfg_scale=1.5,
    )
