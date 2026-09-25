from cb2c_py.lib.workflow import Workflow
from cb2c_py.nodes.generated import (
    CLIPLoader,
    CLIPTextEncode,
    EmptyHunyuanLatentVideo,
    KSampler,
    ModelSamplingSD3,
    UnetLoaderGGUF,
    VAEDecode,
    VAELoader,
    ksampler,
)
from cb2c_py.nodes.generated.clipvisionencode import CLIPVisionEncode
from cb2c_py.nodes.generated.clipvisionloader import CLIPVisionLoader
from cb2c_py.nodes.generated.loadimage import LoadImage
from cb2c_py.nodes.generated.saveanimatedwebp import SaveAnimatedWEBP
from cb2c_py.nodes.generated.vhs_videocombine import VHS_VideoCombine
from cb2c_py.nodes.generated.wanimagetovideo import WanImageToVideo

TEMPLATE = {
    "name": "Wan 2.1 Image to Video (GGUF)",
    "task": "image_to_video",
    "description": "Animate a start image with a text prompt (16 fps) using Wan 2.1 14B 480p GGUF. Needs ComfyUI-GGUF.",
}

FPS = 16


def wan2_1_image2video_gguf(
    positive_prompt: str,
    negative_prompt: str,
    image_path: str,
    seed: int,
    steps: int = 30,
    cfg_scale: float = 6.0,
    width: int = 832,
    height: int = 480,
    seconds: int = 5,
    output_prefix: str = "video/i2v_",
):
    wf = Workflow()

    clip_loader = wf.add_node(
        CLIPLoader(
            clip_name="umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            type="wan",
            device="default",
        )
    )

    clip_vision_loader = wf.add_node(
        CLIPVisionLoader(
            clip_name="clip_vision_h.safetensors",
        )
    )

    image_loader = wf.add_node(
        LoadImage(
            image=image_path,
        )
    )

    clip_vision_encoder = wf.add_node(
        CLIPVisionEncode(
            image=image_loader.outputs.image,
            clip_vision=clip_vision_loader.outputs.clip_vision,
            crop="center",
        )
    )

    vae_loader = wf.add_node(VAELoader(vae_name="wan_2.1_vae.safetensors"))

    positive_text_encoder = wf.add_node(
        CLIPTextEncode(
            text=positive_prompt,
            clip=clip_loader.outputs.clip,
        )
    )

    negative_text_encoder = wf.add_node(
        CLIPTextEncode(
            text=negative_prompt,
            clip=clip_loader.outputs.clip,
        )
    )

    wan_image_to_video = wf.add_node(
        WanImageToVideo(
            width=width,
            height=height,
            length=FPS * seconds + 1,
            batch_size=1,
            clip_vision_output=clip_vision_encoder.outputs.clip_vision_output,
            start_image=image_loader.outputs.image,
            positive=positive_text_encoder.outputs.conditioning,
            negative=negative_text_encoder.outputs.conditioning,
            vae=vae_loader.outputs.vae,
        )
    )

    unet_loader = wf.add_node(
        UnetLoaderGGUF(unet_name="wan2.1-i2v-14b-480p-Q4_K_M.gguf")
    )

    model_sampler = wf.add_node(
        ModelSamplingSD3(shift=8, model=unet_loader.outputs.model)
    )

    k_sampler = wf.add_node(
        KSampler(
            seed=seed,
            steps=steps,
            cfg=cfg_scale,
            sampler_name="uni_pc",
            scheduler="simple",
            denoise=1,
            model=model_sampler.outputs.model,
            positive=wan_image_to_video.outputs.positive,
            negative=wan_image_to_video.outputs.negative,
            latent_image=wan_image_to_video.outputs.latent,
        )
    )

    vae_decoder = wf.add_node(
        VAEDecode(samples=k_sampler.outputs.latent, vae=vae_loader.outputs.vae)
    )

    wf.add_node(
        SaveAnimatedWEBP(
            filename_prefix=output_prefix,
            fps=FPS,
            lossless=False,
            quality=90,
            method="default",
            images=vae_decoder.outputs.image,
        )
    )
    # wf.add_node(
    #     VHS_VideoCombine(
    #         filename_prefix=output_prefix,
    #         format="video/h265-mp4",
    #         images=vae_decoder.outputs.image,
    #     )
    # )

    return wf
