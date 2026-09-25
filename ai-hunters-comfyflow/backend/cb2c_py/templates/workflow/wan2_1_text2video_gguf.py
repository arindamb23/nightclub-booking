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
)
from cb2c_py.nodes.generated.saveanimatedwebp import SaveAnimatedWEBP
from cb2c_py.nodes.generated.vhs_videocombine import VHS_VideoCombine

TEMPLATE = {
    "name": "Wan 2.1 Text to Video (GGUF)",
    "task": "text_to_video",
    "description": "Generate a short video (16 fps) from a text prompt with Wan 2.1 14B GGUF. Needs ComfyUI-GGUF.",
}

FPS = 16


def wan2_1_text2video_gguf(
    positive_prompt: str,
    negative_prompt: str,
    seed: int,
    steps: int = 30,
    cfg_scale: float = 6.0,
    width: int = 832,
    height: int = 480,
    seconds: int = 5,
    output_prefix: str = "video/t2v_",
):
    """
    This function was auto-generated from a ComfyUI workflow (wan2.1_T2V.json).
    """
    wf = Workflow()

    clip_loader = wf.add_node(
        CLIPLoader(
            clip_name="umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            type="wan",
            device="default",
        )
    )

    vae_loader = wf.add_node(VAELoader(vae_name="wan_2.1_vae.safetensors"))

    empty_latent_video = wf.add_node(
        EmptyHunyuanLatentVideo(
            width=width, height=height, length=FPS * seconds + 1, batch_size=1
        )
    )

    unet_loader = wf.add_node(UnetLoaderGGUF(unet_name="wan2.1-t2v-14b-Q4_K_M.gguf"))

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
            positive=positive_text_encoder.outputs.conditioning,
            negative=negative_text_encoder.outputs.conditioning,
            latent_image=empty_latent_video.outputs.latent,
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
