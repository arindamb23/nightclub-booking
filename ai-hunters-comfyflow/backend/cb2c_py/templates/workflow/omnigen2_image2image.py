"""OmniGen2 image editing: change one image (optionally guided by a second one) with a text instruction.

Originally auto-generated from ComfyUI's ``image_omnigen2_image_edit.json``; rewritten as a
parameterised template (the generated version called the loaders without their model names).
Models: omnigen2_fp16.safetensors (diffusion_models), qwen_2.5_vl_fp16.safetensors (text_encoders),
ae.safetensors (vae).
"""
from typing import Optional

from cb2c_py.lib.workflow import Workflow
from cb2c_py.nodes.generated.basicscheduler import BasicScheduler
from cb2c_py.nodes.generated.cliploader import CLIPLoader
from cb2c_py.nodes.generated.cliptextencode import CLIPTextEncode
from cb2c_py.nodes.generated.dualcfgguider import DualCFGGuider
from cb2c_py.nodes.generated.emptysd3latentimage import EmptySD3LatentImage
from cb2c_py.nodes.generated.getimagesize import GetImageSize
from cb2c_py.nodes.generated.imagescaletototalpixels import ImageScaleToTotalPixels
from cb2c_py.nodes.generated.ksamplerselect import KSamplerSelect
from cb2c_py.nodes.generated.loadimage import LoadImage
from cb2c_py.nodes.generated.randomnoise import RandomNoise
from cb2c_py.nodes.generated.referencelatent import ReferenceLatent
from cb2c_py.nodes.generated.samplercustomadvanced import SamplerCustomAdvanced
from cb2c_py.nodes.generated.saveimage import SaveImage
from cb2c_py.nodes.generated.unetloader import UNETLoader
from cb2c_py.nodes.generated.vaedecode import VAEDecode
from cb2c_py.nodes.generated.vaeencode import VAEEncode
from cb2c_py.nodes.generated.vaeloader import VAELoader

TEMPLATE = {
    "name": "OmniGen2 Image Edit",
    "task": "image_edit",
    "description": "Edit a picture with a text instruction (e.g. 'make it a watercolor painting'). "
    "An optional second image can be used as a reference.",
}


def omnigen2_image2image(
    positive_prompt: str,
    image_path: str,
    seed: int,
    negative_prompt: str = "blurry, low quality, distorted, deformed",
    image_path2: Optional[str] = None,
    steps: int = 20,
    cfg_conds: float = 5.0,
    cfg_image: float = 2.0,
    megapixels: float = 1.0,
    output_prefix: str = "omnigen2_",
) -> Workflow:
    wf = Workflow()

    vae = wf.add_node(VAELoader(vae_name="ae.safetensors"))
    clip = wf.add_node(CLIPLoader(clip_name="qwen_2.5_vl_fp16.safetensors", type="omnigen2", device="default"))
    unet = wf.add_node(UNETLoader(unet_name="omnigen2_fp16.safetensors", weight_dtype="default"))

    image1 = wf.add_node(LoadImage(image=image_path))
    image1.upload = True
    scaled1 = wf.add_node(ImageScaleToTotalPixels(image=image1.outputs.image, upscale_method="area", megapixels=megapixels))
    latent1 = wf.add_node(VAEEncode(pixels=scaled1.outputs.image, vae=vae.outputs.vae))
    size = wf.add_node(GetImageSize(image=scaled1.outputs.image))

    positive = wf.add_node(CLIPTextEncode(text=positive_prompt, clip=clip.outputs.clip))
    negative = wf.add_node(CLIPTextEncode(text=negative_prompt, clip=clip.outputs.clip))

    cond_pos = wf.add_node(ReferenceLatent(conditioning=positive.outputs.conditioning, latent=latent1.outputs.latent))
    cond_neg = wf.add_node(ReferenceLatent(conditioning=negative.outputs.conditioning, latent=latent1.outputs.latent))

    if image_path2:
        image2 = wf.add_node(LoadImage(image=image_path2))
        image2.upload = True
        scaled2 = wf.add_node(ImageScaleToTotalPixels(image=image2.outputs.image, upscale_method="area", megapixels=megapixels))
        latent2 = wf.add_node(VAEEncode(pixels=scaled2.outputs.image, vae=vae.outputs.vae))
        cond_pos = wf.add_node(ReferenceLatent(conditioning=cond_pos.outputs.conditioning, latent=latent2.outputs.latent))
        cond_neg = wf.add_node(ReferenceLatent(conditioning=cond_neg.outputs.conditioning, latent=latent2.outputs.latent))

    guider = wf.add_node(
        DualCFGGuider(
            model=unet.outputs.model,
            cond1=cond_pos.outputs.conditioning,
            cond2=cond_neg.outputs.conditioning,
            negative=negative.outputs.conditioning,
            cfg_conds=cfg_conds,
            cfg_cond2_negative=cfg_image,
        )
    )
    noise = wf.add_node(RandomNoise(noise_seed=seed))
    sampler = wf.add_node(KSamplerSelect(sampler_name="euler"))
    sigmas = wf.add_node(BasicScheduler(model=unet.outputs.model, scheduler="simple", steps=steps, denoise=1.0))
    empty = wf.add_node(EmptySD3LatentImage(batch_size=1))
    empty.width = size.outputs.width
    empty.height = size.outputs.height

    sampled = wf.add_node(
        SamplerCustomAdvanced(
            noise=noise.outputs.noise,
            guider=guider.outputs.guider,
            sampler=sampler.outputs.sampler,
            sigmas=sigmas.outputs.sigmas,
            latent_image=empty.outputs.latent,
        )
    )
    decoded = wf.add_node(VAEDecode(samples=sampled.outputs.output, vae=vae.outputs.vae))
    wf.add_node(SaveImage(images=decoded.outputs.image, filename_prefix=output_prefix))
    return wf

