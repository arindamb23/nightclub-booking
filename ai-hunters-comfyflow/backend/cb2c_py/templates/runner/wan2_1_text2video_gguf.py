#!/usr/bin/env python3
"""python -m cb2c_py.templates.runner.wan2_1_text2video_gguf"""
from cb2c_py.lib.progress_handler import ComfyUIProgressHandler
from cb2c_py.templates.workflow.wan2_1_text2video_gguf import wan2_1_text2video_gguf

RATIO = 16 / 9


def main():
    width = int(832 / 2)
    height = int(width / RATIO)
    wf = wan2_1_text2video_gguf(
        positive_prompt="Ultra realistic footage of a calico cat gardening in a sunny backyard. The cat is digging "
        "gently in the soil with its paws, surrounded by green plants, flowers in bloom and gardening tools. "
        "Natural camera shake, cinematic depth of field, golden hour lighting, handheld look. 4K quality",
        negative_prompt="blurry, low resolution, low quality, pixelated, overexposed, underexposed, distorted, "
        "cartoon, anime, sketch, painting, CGI, deformed, unrealistic, duplicated limbs, extra hands, glitch",
        seed=12345,
        steps=30,
        cfg_scale=6.0,
        width=width,
        height=height,
        seconds=5,
        output_prefix="video/t2v_",
    )
    files = wf.run(progress_callback=ComfyUIProgressHandler(name="Video Generation", workflow=wf))
    for f in files:
        print("Saved", f["path"])


if __name__ == "__main__":
    main()
