"""Wan 2.1 text to video (14B GGUF Q4_K_M) - 5 s at 16 fps. Needs the ComfyUI-GGUF custom node."""
from cb2c_py.lib.workflow import Workflow
from cb2c_py.templates.workflow.wan2_1_text2video_gguf import wan2_1_text2video_gguf

WORKFLOW_NAME = "Wan 2.1 Text to Video (GGUF)"


def build_workflow() -> Workflow:
    return wan2_1_text2video_gguf(
        positive_prompt="Ultra realistic footage of a calico cat gardening in a sunny backyard, digging gently "
        "in the soil, flowers in bloom, golden hour lighting, handheld look, 4K quality",
        negative_prompt="blurry, low resolution, low quality, pixelated, distorted, cartoon, deformed, glitch",
        seed=12345,
        steps=30,
        cfg_scale=6.0,
        width=416,
        height=234,
        seconds=5,
        output_prefix="video/t2v_",
    )
