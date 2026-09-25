#!/usr/bin/env python3
"""python -m cb2c_py.templates.runner.wan2_1_image2video_gguf"""
from pathlib import Path

from cb2c_py.lib.progress_handler import ComfyUIProgressHandler
from cb2c_py.templates.workflow.wan2_1_image2video_gguf import wan2_1_image2video_gguf

INPUT = Path(__file__).resolve().parent / "input"


def main():
    wf = wan2_1_image2video_gguf(
        positive_prompt="A girl kindly smiling to the camera",
        negative_prompt="blurry, low resolution, low quality, pixelated, overexposed, underexposed, distorted, "
        "cartoon, anime, sketch, painting, CGI, deformed, unrealistic, duplicated limbs, extra hands, glitch",
        seed=12345,
        steps=25,
        cfg_scale=6.0,
        width=512,
        height=512,
        seconds=5,
        image_path=str(INPUT / "girl.png"),
        output_prefix="video/i2v_",
    )
    for node in wf.get_nodes():  # upload the local input image to ComfyUI
        if node._original_name == "LoadImage":
            node.upload = True
    files = wf.run(progress_callback=ComfyUIProgressHandler(name="Video Generation", workflow=wf))
    for f in files:
        print("Saved", f["path"])


if __name__ == "__main__":
    main()
