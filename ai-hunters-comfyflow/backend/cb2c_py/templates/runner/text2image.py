#!/usr/bin/env python3
"""python -m cb2c_py.templates.runner.text2image"""
import random

from cb2c_py.lib.progress_handler import ComfyUIProgressHandler
from cb2c_py.templates.workflow.text2image import text2image


def main():
    print("Building workflow...")
    wf = text2image(
        pos_prompt="lara croft, elder, old, 8k fujifilm, realistic, high quality, detailed, sharp focus, "
        "cinematic lighting, ultra wide angle, depth of field, bokeh",
        neg_prompt="blurry, bad quality",
        seed=random.randint(0, 1000000),
        steps=6,
        width=768,
        height=768,
        ckpt_name="RealVisXL_V5.1.safetensors",
        sampler_name="dpmpp_2m_sde",
        scheduler_name="karras",
        cfg_scale=1.5,
    )
    files = wf.run(progress_callback=ComfyUIProgressHandler(name="Image Generation", workflow=wf))
    for f in files:
        print("Saved", f["path"])


if __name__ == "__main__":
    main()
