from cb2c_py.lib.workflow import Workflow
from cb2c_py.nodes.generated import (
    CLIPTextEncode,
    ConditioningZeroOut,
    DualCLIPLoader,
    EmptySD3LatentImage,
    FluxGuidance,
    FluxKontextImageScale,
    ImageStitch,
    KSampler,
    LoadImageOutput,
    NunchakuFluxDiTLoader,
    NunchakuWheelInstaller,
    PreviewAny,
    PreviewImage,
    ReferenceLatent,
    SaveImage,
    VAEDecode,
    VAEEncode,
    VAELoader,
)
from cb2c_py.nodes.generated.loadimage import LoadImage


TEMPLATE = {
    "name": "FLUX Kontext Image Edit (Nunchaku)",
    "task": "image_edit",
    "description": "Edit one or two images with a text instruction using FLUX.1 Kontext (Nunchaku). "
    "Model: int4 for most NVIDIA GPUs, fp4 (svdq-fp4_r32-...) for RTX 50xx. Needs the ComfyUI-nunchaku custom node.",
    "labels": {"image_path1": "Input image", "model": "Kontext model"},
}

def flux_kontext_dev_nunchaku(
    positive_prompt: str,
    image_path1: str,
    seed: int = 0,
    model: str = "svdq-int4_r32-flux.1-kontext-dev.safetensors",
    steps: int = 20,
    cfg: float = 1.0,
    output_prefix: str = "flux_kontext_",
    image_path2: str | None = None,
):
    wf = Workflow()

    vae_loader = wf.add_node(VAELoader(vae_name="ae.safetensors"))

    dual_clip_loader = wf.add_node(
        DualCLIPLoader(
            clip_name1="clip_l.safetensors",
            clip_name2="t5xxl_fp8_e4m3fn_scaled.safetensors",
            type="flux",
        )
    )
    dual_clip_loader.device = "default"

    # wf.add_node(EmptySD3LatentImage(width=1024, height=1024, batch_size=1))

    flux_dit_loader = wf.add_node(
        NunchakuFluxDiTLoader(
            model_path=model,
            cache_threshold=0,
            attention="nunchaku-fp16",
            cpu_offload="auto",
            device_id=0,
            data_type="bfloat16",
        )
    )
    flux_dit_loader.i2f_mode = "enabled"

    loadimageoutput1 = wf.add_node(LoadImage(image=image_path1))
    loadimageoutput1.upload = True

    image_stitcher = wf.add_node(
        ImageStitch(
            image1=loadimageoutput1.outputs.image,
            direction="right",
            match_image_size=True,
            spacing_width=0,
            spacing_color="white",
        )
    )
    if image_path2:
        loadimageoutput2 = wf.add_node(LoadImage(image=image_path2))
        loadimageoutput2.upload = True

        image_stitcher.image2 = loadimageoutput2.outputs.image

    # wf.add_node(PreviewAny(source=nunchaku_wheel_installer.outputs.status))

    positive_prompt_encoder = wf.add_node(
        CLIPTextEncode(
            clip=dual_clip_loader.outputs.clip,
            text=positive_prompt,
        )
    )

    zeroed_conditioning = wf.add_node(
        ConditioningZeroOut(conditioning=positive_prompt_encoder.outputs.conditioning)
    )

    image_scaler = wf.add_node(
        FluxKontextImageScale(image=image_stitcher.outputs.image)
    )

    vae_encoder = wf.add_node(
        VAEEncode(vae=vae_loader.outputs.vae, pixels=image_scaler.outputs.image)
    )

    wf.add_node(PreviewImage(images=image_scaler.outputs.image))

    reference_latent_conditioning = wf.add_node(
        ReferenceLatent(
            conditioning=positive_prompt_encoder.outputs.conditioning,
        )
    )
    reference_latent_conditioning.latent = vae_encoder.outputs.latent

    flux_guidance = wf.add_node(
        FluxGuidance(
            conditioning=reference_latent_conditioning.outputs.conditioning,
            guidance=2.5,
        )
    )

    k_sampler = wf.add_node(
        KSampler(
            model=flux_dit_loader.outputs.model,
            positive=flux_guidance.outputs.conditioning,
            negative=zeroed_conditioning.outputs.conditioning,
            latent_image=vae_encoder.outputs.latent,
            seed=seed,
            steps=steps,
            cfg=cfg,
            sampler_name="euler",
            scheduler="normal",
            denoise=1.0,
        )
    )

    vae_decoder = wf.add_node(
        VAEDecode(samples=k_sampler.outputs.latent, vae=vae_loader.outputs.vae)
    )

    wf.add_node(
        SaveImage(images=vae_decoder.outputs.image, filename_prefix=output_prefix)
    )

    return wf
