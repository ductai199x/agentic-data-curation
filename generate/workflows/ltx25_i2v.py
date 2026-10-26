"""LTX-2.5 two-stage distilled I2V / FLF2V workflow for ComfyUI.

Built from the official graphs (read Oct 26 2026), not validated on a GPU yet:
  * Lightricks ComfyUI-LTXVideo `example_workflows/2.5/LTX-2.5_T2V_I2V_Two_Stage_Distilled.json`
    (the README's "start here"): stage 1 at half resolution, 8 distilled steps; 2x latent upsample;
    3-step refine; CFGGuider(cfg=1); euler_ancestral then euler; first frame via LTXVImgToVideoInplace
    (0.7 stage 1, 1.0 stage 2); decode tiled 512/64/64/8.
  * Comfy-Org workflow_templates `video_ltx2_5_flf2v.json` for the last-frame path: LTXVAddGuide at
    frame_idx 0 and -1 (strength 0.7), LTXVCropGuides before decode. That template is single-stage; the
    stage-2 guides at strength 1.0 here follow the same pattern as ltx_i2v (2.3) and are our extrapolation.
  * Stage-2 sigmas 0.909375/0.725/0.421875/0 per the 2.5 README note (the core I2V template uses 0.85).

Differences from 2.3 (ltx_i2v): 2.5 ships split files, so UNETLoader + two VAELoaders + CLIPLoader("ltxv")
replace CheckpointLoaderSimple / LTXVAudioVAELoader / LTXAVTextEncoderLoader; the distilled transformer
needs no LoRA; no MultimodalGuider, so the ComfyUI-LTXVideo custom nodes are not needed. Guide latents
appended by LTXVAddGuide are cropped after stage 1 (before the upsampler) and again before decode.
The prompt enhancer (TextGenerateLTX2Prompt) is off: prompts are SALMONN captions.

Weight layout under `third_party/ComfyUI/models/` (transformer is gated on HF: accept Lightricks/LTX-2.5):
  * diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors
  * vae/ltx-2.5-video-vae-bf16.safetensors, vae/ltx-2.5-audio-vae-bf16.safetensors
  * text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors   (Comfy-Org/gemma-4)
  * latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors
Needs a ComfyUI recent enough to have the 2.5 model type (the templates above target Oct 2026 builds).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_dims

# Stage 1 at 544x960 (~522k px, stride 32) -> 1088x1920 after the 2x upsampler, same as the LTX 2.3 set.
_STAGE1_PIXEL_BUDGET = 544 * 960
_LTX_STRIDE = 32

DEFAULTS: dict[str, Any] = {
    # Weights
    "unet": "ltx-2.5-22b-distilled-transformer-bf16.safetensors",
    "weight_dtype": "default",
    "video_vae": "ltx-2.5-video-vae-bf16.safetensors",
    "audio_vae": "ltx-2.5-audio-vae-bf16.safetensors",
    "text_encoder": "gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
    "upscaler": "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",

    # Geometry (portrait 9:16; overridden by the source frame's aspect)
    "stage1_width": 544,
    "stage1_height": 960,
    "num_frames": 121,                             # 5 s @ 24 fps, 8N+1 (graph default)
    "frame_rate": 24,

    # Image conditioning
    "preprocess_compression": 18,
    "stage1_strength": 0.7,
    "stage2_strength": 1.0,

    # Sampling (distilled: cfg 1, fixed sigma schedules)
    "stage1_seed": 43,
    "stage2_seed": 42,
    "cfg": 1.0,
    "stage1_sampler": "euler_ancestral",
    "stage2_sampler": "euler",
    "stage1_sigmas": "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0",
    "stage2_sigmas": "0.909375, 0.725, 0.421875, 0.0",

    # Tiled decode
    "decode_tile_size": 512,
    "decode_overlap": 64,
    "decode_temporal_size": 64,
    "decode_temporal_overlap": 8,

    # cfg=1 ignores the negative; kept for parity with the official I2V graph
    "negative_prompt": "pc game, console game, video game, cartoon, childish, ugly",
}


def _resize(src: str, w: int, h: int) -> dict:
    return {"class_type": "ImageScale", "inputs": {"image": [src, 0], "upscale_method": "lanczos", "width": w, "height": h, "crop": "center"}}


def _add_guides(nodes: dict, stage: str, cond: str, latent: list, first_img: str, last_img: str, strength: float) -> str:
    # FLF path: first frame pinned at 0, last frame appended at -1; returns the node holding (pos, neg, latent)
    nodes[f"guide_first_{stage}"] = {"class_type": "LTXVAddGuide", "inputs": {
        "positive": [cond, 0], "negative": [cond, 1], "vae": ["video_vae", 0], "latent": latent,
        "image": [first_img, 0], "frame_idx": 0, "strength": strength}}
    nodes[f"guide_last_{stage}"] = {"class_type": "LTXVAddGuide", "inputs": {
        "positive": [f"guide_first_{stage}", 0], "negative": [f"guide_first_{stage}", 1], "vae": ["video_vae", 0],
        "latent": [f"guide_first_{stage}", 2], "image": [last_img, 0], "frame_idx": -1, "strength": strength}}
    return f"guide_last_{stage}"


def _sample(nodes: dict, stage: str, k: dict, positive: list, negative: list, video_latent: list, audio_latent: list):
    nodes.update({
        f"concat_av_{stage}": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": video_latent, "audio_latent": audio_latent}},
        f"noise_{stage}": {"class_type": "RandomNoise", "inputs": {"noise_seed": k[f"{stage}_seed"]}},
        f"guider_{stage}": {"class_type": "CFGGuider", "inputs": {"model": ["unet", 0], "positive": positive, "negative": negative, "cfg": k["cfg"]}},
        f"sampler_{stage}": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": k[f"{stage}_sampler"]}},
        f"sigmas_{stage}": {"class_type": "ManualSigmas", "inputs": {"sigmas": k[f"{stage}_sigmas"]}},
        f"sample_{stage}": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": [f"noise_{stage}", 0], "guider": [f"guider_{stage}", 0], "sampler": [f"sampler_{stage}", 0],
            "sigmas": [f"sigmas_{stage}", 0], "latent_image": [f"concat_av_{stage}", 0]}},
        f"separate_av_{stage}": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": [f"sample_{stage}", 0]}},
    })


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: Path | None = None,
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}
    if first_frame_path is not None and "stage1_width" not in cfg.model_kwargs:
        k["stage1_width"], k["stage1_height"] = pick_dims(first_frame_path, _STAGE1_PIXEL_BUDGET, _LTX_STRIDE)
    num_frames = int(k["num_frames"])
    s1_w, s1_h = int(k["stage1_width"]), int(k["stage1_height"])
    flf = last_frame_name is not None

    nodes: dict = {
        # ---- loaders (2.5 ships split files) ----
        "unet": {"class_type": "UNETLoader", "inputs": {"unet_name": k["unet"], "weight_dtype": k["weight_dtype"]}},
        "video_vae": {"class_type": "VAELoader", "inputs": {"vae_name": k["video_vae"]}},
        "audio_vae": {"class_type": "VAELoader", "inputs": {"vae_name": k["audio_vae"]}},
        "clip_loader": {"class_type": "CLIPLoader", "inputs": {"clip_name": k["text_encoder"], "type": "ltxv", "device": "default"}},
        "upscaler": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": k["upscaler"]}},

        # ---- prompt ----
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip_loader", 0], "text": prompt_text}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["clip_loader", 0], "text": k["negative_prompt"]}},
        "conditioning": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["positive", 0], "negative": ["negative", 0], "frame_rate": float(k["frame_rate"])}},

        # ---- frames ----
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "resize_first_s1": _resize("load_first", s1_w, s1_h),
        "preprocess_first_s1": {"class_type": "LTXVPreprocess", "inputs": {"image": ["resize_first_s1", 0], "img_compression": k["preprocess_compression"]}},
        "resize_first_s2": _resize("load_first", s1_w * 2, s1_h * 2),

        # ---- stage-1 latents ----
        "empty_video_s1": {"class_type": "EmptyLTXVLatentVideo", "inputs": {"width": s1_w, "height": s1_h, "length": num_frames, "batch_size": 1}},
        "empty_audio": {"class_type": "LTXVEmptyLatentAudio", "inputs": {
            "frames_number": num_frames, "frame_rate": int(k["frame_rate"]), "batch_size": 1, "audio_vae": ["audio_vae", 0]}},
    }
    if flf:
        nodes.update({
            "load_last": {"class_type": "LoadImage", "inputs": {"image": last_frame_name}},
            "resize_last_s1": _resize("load_last", s1_w, s1_h),
            "preprocess_last_s1": {"class_type": "LTXVPreprocess", "inputs": {"image": ["resize_last_s1", 0], "img_compression": k["preprocess_compression"]}},
            "resize_last_s2": _resize("load_last", s1_w * 2, s1_h * 2),
        })

    # ---- stage 1: half resolution, 8 distilled steps ----
    if flf:
        g1 = _add_guides(nodes, "s1", "conditioning", ["empty_video_s1", 0], "preprocess_first_s1", "preprocess_last_s1", k["stage1_strength"])
        _sample(nodes, "stage1", k, [g1, 0], [g1, 1], [g1, 2], ["empty_audio", 0])
        nodes["crop_s1"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": [g1, 0], "negative": [g1, 1], "latent": ["separate_av_stage1", 0]}}
        s1_video = ["crop_s1", 2]
    else:
        nodes["i2v_s1"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {
            "vae": ["video_vae", 0], "image": ["preprocess_first_s1", 0], "latent": ["empty_video_s1", 0],
            "strength": k["stage1_strength"], "bypass": False}}
        _sample(nodes, "stage1", k, ["conditioning", 0], ["conditioning", 1], ["i2v_s1", 0], ["empty_audio", 0])
        s1_video = ["separate_av_stage1", 0]

    # ---- 2x latent upsample, then stage 2: 3-step refine at full resolution ----
    nodes["upsampled"] = {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": s1_video, "upscale_model": ["upscaler", 0], "vae": ["video_vae", 0]}}
    if flf:
        g2 = _add_guides(nodes, "s2", "conditioning", ["upsampled", 0], "resize_first_s2", "resize_last_s2", k["stage2_strength"])
        _sample(nodes, "stage2", k, [g2, 0], [g2, 1], [g2, 2], ["separate_av_stage1", 1])
        nodes["crop_s2"] = {"class_type": "LTXVCropGuides", "inputs": {"positive": [g2, 0], "negative": [g2, 1], "latent": ["separate_av_stage2", 0]}}
        final_video = ["crop_s2", 2]
    else:
        nodes["i2v_s2"] = {"class_type": "LTXVImgToVideoInplace", "inputs": {
            "vae": ["video_vae", 0], "image": ["resize_first_s2", 0], "latent": ["upsampled", 0],
            "strength": k["stage2_strength"], "bypass": False}}
        _sample(nodes, "stage2", k, ["conditioning", 0], ["conditioning", 1], ["i2v_s2", 0], ["separate_av_stage1", 1])
        final_video = ["separate_av_stage2", 0]

    nodes.update({
        "decode": {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": final_video, "vae": ["video_vae", 0], "tile_size": k["decode_tile_size"], "overlap": k["decode_overlap"],
            "temporal_size": k["decode_temporal_size"], "temporal_overlap": k["decode_temporal_overlap"]}},
        "save": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["decode", 0], "frame_rate": float(k["frame_rate"]), "filename_prefix": filename_prefix,
            "format": "video/h264-mp4", "save_output": True, "loop_count": 0, "pingpong": False, "pix_fmt": "yuv420p", "crf": 19}},
    })
    return nodes
