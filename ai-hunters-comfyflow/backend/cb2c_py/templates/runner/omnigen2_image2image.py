#!/usr/bin/env python3
"""python -m cb2c_py.templates.runner.omnigen2_image2image"""
import random
from pathlib import Path

from cb2c_py.lib.progress_handler import ComfyUIProgressHandler
from cb2c_py.templates.workflow.omnigen2_image2image import omnigen2_image2image

INPUT = Path(__file__).resolve().parent / "input"


def main():
    wf = omnigen2_image2image(
        positive_prompt="Put the girl on the beach from the second picture, golden hour light",
        image_path=str(INPUT / "girl.png"),
        image_path2=str(INPUT / "beach.png"),
        seed=random.randint(0, 1000000),
    )
    files = wf.run(progress_callback=ComfyUIProgressHandler(name="OmniGen2 Image Edit", workflow=wf))
    for f in files:
        print("Saved", f["path"])


if __name__ == "__main__":
    main()
