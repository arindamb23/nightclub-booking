#!/usr/bin/env python3

# comfyui/back2code/workflow-example.py

"""
This script demonstrates how to build a simple text-to-image workflow
programmatically using the ComfyBack2Code framework.
"""

from typing import Literal
from cb2c_py.lib.workflow import Workflow
from cb2c_py.nodes.generated import (
    CheckpointLoaderSimple,
    CLIPTextEncode,
    CheckpointLoaderSimpleCkpt_name,
    KSampler,
    EmptyLatentImage,
    VAEDecode,
    SaveImage,
    KSamplerSampler_name,
    KSamplerScheduler,
)


def text2image(
    pos_prompt: str,
    neg_prompt: str,
    seed: int,
    steps: int = 20,
    cfg_scale: float = 8.0,
    width: int = 512,
    height: int = 512,
    ckpt_name: CheckpointLoaderSimpleCkpt_name = "v1-5-pruned-emaonly.safetensors",
    sampler_name: KSamplerSampler_name = "euler",
    scheduler_name: KSamplerScheduler = "normal",
):
    """
    Creates a standard text-to-image workflow object.
    """
    wf = Workflow()

    # 1. Load the model checkpoint
    chkpt_loader_node = wf.add_node(CheckpointLoaderSimple(ckpt_name))

    # 2. Create an empty latent image
    empty_latent_node = wf.add_node(
        EmptyLatentImage(width=width, height=height, batch_size=1)
    )

    # 3. Encode the positive prompt, connecting it to the checkpoint loader's CLIP output
    positive_prompt_node = wf.add_node(
        CLIPTextEncode(
            text=pos_prompt,
            clip=chkpt_loader_node.outputs.clip,
        )
    )

    # 4. Encode the negative prompt, also connecting it to the checkpoint loader's CLIP output
    negative_prompt_node = wf.add_node(
        CLIPTextEncode(
            text=neg_prompt,
            clip=chkpt_loader_node.outputs.clip,
        )
    )

    # 5. The KSampler node, which takes outputs from all previous nodes
    sampler_node = wf.add_node(
        KSampler(
            seed=seed,
            steps=steps,
            cfg=cfg_scale,
            sampler_name=sampler_name,
            scheduler=scheduler_name,
            denoise=1.0,
            model=chkpt_loader_node.outputs.model,
            positive=positive_prompt_node.outputs.conditioning,
            negative=negative_prompt_node.outputs.conditioning,
            latent_image=empty_latent_node.outputs.latent,
        )
    )

    # 6. Decode the latent image back into pixels
    vae_decode_node = wf.add_node(
        VAEDecode(
            samples=sampler_node.outputs.latent,
            vae=chkpt_loader_node.outputs.vae,
        )
    )

    # 7. Save the final image
    wf.add_node(
        SaveImage(
            filename_prefix="ComfyBack2Code_example",
            images=vae_decode_node.outputs.image,
        )
    )

    # The connections are now defined directly when creating the nodes.
    # The wf.connect calls are no longer needed.

    return wf
