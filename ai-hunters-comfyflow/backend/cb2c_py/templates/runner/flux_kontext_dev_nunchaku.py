#!/usr/bin/env python3
"""python -m cb2c_py.templates.runner.flux_kontext_dev_nunchaku"""
import random
from pathlib import Path

from cb2c_py.lib.progress_handler import ComfyUIProgressHandler
from cb2c_py.templates.workflow.flux_kontext_dev_nunchaku import flux_kontext_dev_nunchaku

INPUT = Path(__file__).resolve().parent / "input"


def main():
    # Blackwell GPU (RTX 50xx): fp4. Other GPUs: "svdq-int4_r32-flux.1-kontext-dev.safetensors"
    model = "svdq-fp4_r32-flux.1-kontext-dev.safetensors"
    wf = flux_kontext_dev_nunchaku(
        model=model,
        positive_prompt="Make the character in Ghibli style",
        seed=random.randint(0, 1000000),
        steps=20,
        cfg=1,
        output_prefix="flux_kontext_output_",
        image_path1=str(INPUT / "girl.png"),
        # image_path2=str(INPUT / "beach.png"),
    )
    files = wf.run(progress_callback=ComfyUIProgressHandler(name="Flux Kontext Dev Nunchaku", workflow=wf))
    for f in files:
        print("Saved", f["path"])


if __name__ == "__main__":
    main()
