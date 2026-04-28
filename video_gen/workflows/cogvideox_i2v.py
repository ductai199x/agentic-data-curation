"""CogVideoX 1.5 5B I2V workflow for Kijai's ComfyUI-CogVideoXWrapper.

Native 1360×768 portrait, 81 frames @ 16 fps. 50 sampling steps with
CogVideoXDDIM is the quality-safe default — a brief experiment on YT data
with 30-step DPM + TeaCache (rel_l1_thresh=0.2) produced visible grainy
artifacts on faces, night scenes, and smooth/dark regions, so we reverted
to the original setup.

Based on example: `cogvideox_1_5_5b_I2V_01.json`

The wrapper auto-downloads the diffusers repo on first load. T5-XXL text
encoder comes from ComfyUI-core's `CLIPLoader` with `type="cogvideox"`.
"""

from __future__ import annotations

from typing import Any

from video_gen.comfy_config import ComfyRunConfig
from video_gen.workflows._aspect import pick_dims

# CogVideoX 1.5 5B native 1360×768 = ~1.04M px, VAE stride 16 (8× spatial
# downsample × 2× patch). Source frames with odd dims (not multiples of 16)
# cause reshape errors deep inside the transformer — resize to stride-16
# before feeding to CogVideoImageEncode.
_PIXEL_BUDGET = 1360 * 768
_STRIDE = 16

DEFAULTS: dict[str, Any] = {
    "model_repo": "kijai/CogVideoX-5b-1.5-I2V",
    "model_precision": "bf16",
    "quantization": "disabled",
    # CogVideoX T5 text encoder — name of the file placed in
    # ComfyUI/models/text_encoders/. ComfyUI's CLIPLoader picks it up.
    "t5_encoder": "t5xxl_fp16.safetensors",
    "t5_encoder_type": "sd3",  # CLIPLoader type — CogVideoX uses sd3-style T5 loader
    # NOTE: no (width, height) at the sampler — CogVideoImageEncode derives
    # latent shape directly from the input image, so output aspect always
    # matches source. Smoke-test confirms: 720×720 source → 720×720 output.
    "num_frames": 81,
    "fps": 16,
    "steps": 50,
    "cfg": 6.0,
    "seed": 42,
    "scheduler": "CogVideoXDDIM",
    "attention_mode": "sdpa",
    "force_offload": True,
    "enable_sequential_cpu_offload": False,
    "enable_vae_tiling_decode": True,
    "negative_prompt": "",
}


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: "Path | None" = None,
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}

    # Resize source to stride-16 dims at CogVideoX's pixel budget. Without
    # this, arbitrary source resolutions (e.g. 608×1080, 1078×606) trip a
    # reshape error inside the transformer ("shape '[...32]' is invalid for
    # input of size N"). Aspect is preserved (same as pick_dims semantics).
    if first_frame_path is not None:
        target_w, target_h = pick_dims(first_frame_path, _PIXEL_BUDGET, _STRIDE)
    else:
        target_w, target_h = 1360, 768  # safe fallback matching native

    nodes: dict = {
        "pipe": {
            "class_type": "DownloadAndLoadCogVideoModel",
            "inputs": {
                "model": k["model_repo"],
                "precision": k["model_precision"],
                "quantization": k["quantization"],
                "enable_sequential_cpu_offload": k["enable_sequential_cpu_offload"],
                "attention_mode": k["attention_mode"],
            },
        },
        # CogVideoX uses a T5 loaded via core CLIPLoader
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": k["t5_encoder"],
                "type": k["t5_encoder_type"],
                "device": "default",
            },
        },
        "load_image": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "resize_image": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["load_image", 0],
                "width": target_w,
                "height": target_h,
                "upscale_method": "lanczos",
                "crop": "disabled",
            },
        },
        "positive": {
            "class_type": "CogVideoTextEncode",
            "inputs": {
                "clip": ["clip", 0],
                "prompt": prompt_text,
                "strength": 1.0,
                "force_offload": k["force_offload"],
            },
        },
        "negative": {
            "class_type": "CogVideoTextEncode",
            "inputs": {
                "clip": ["clip", 0],
                "prompt": k["negative_prompt"],
                "strength": 1.0,
                "force_offload": k["force_offload"],
            },
        },
        "image_embeds": {
            "class_type": "CogVideoImageEncode",
            "inputs": {
                "vae": ["pipe", 1],
                "start_image": ["resize_image", 0],
            },
        },
        "sampler": {
            "class_type": "CogVideoSampler",
            "inputs": {
                "model": ["pipe", 0],
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "image_cond_latents": ["image_embeds", 0],
                "num_frames": k["num_frames"],
                "steps": k["steps"],
                "cfg": k["cfg"],
                "seed": k["seed"],
                "scheduler": k["scheduler"],
                "denoise_strength": 1.0,
            },
        },
        "decode": {
            "class_type": "CogVideoDecode",
            "inputs": {
                "vae": ["pipe", 1],
                "samples": ["sampler", 0],
                "enable_vae_tiling": k["enable_vae_tiling_decode"],
                "tile_sample_min_height": 96,
                "tile_sample_min_width": 96,
                "tile_overlap_factor_height": 0.083,
                "tile_overlap_factor_width": 0.083,
                "auto_tile_size": True,
            },
        },
        "save": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["decode", 0],
                "frame_rate": float(k["fps"]),
                "filename_prefix": filename_prefix,
                "format": "video/h264-mp4",
                "save_output": True,
                "loop_count": 0,
                "pingpong": False,
                "pix_fmt": "yuv420p",
                "crf": 19,
            },
        },
    }
    return nodes
