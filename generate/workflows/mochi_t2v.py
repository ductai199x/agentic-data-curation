"""Mochi 1 (Genmo) text-to-video workflow.

Native ComfyUI core nodes — no custom nodes required. Mochi 1 is T2V-only;
we ignore `first_frame_path` / `last_frame_name` (the 3D VAE has no clean
single-frame conditioning hook). Per-job prompt comes from the SALMONN
caption associated with the source clip.

Weights (downloaded to third_party/ComfyUI/models/):
  * diffusion_models/mochi_preview_bf16.safetensors  (~20 GB, native Genmo bf16)
  * vae/mochi_vae.safetensors                         (encoder+decoder fused)
  * text_encoders/t5xxl_fp16.safetensors              (existing — shared with LTX)

VAE specifics: 12 latent channels, 8× spatial, 6× temporal compression.
Frame-count constraint: `(length - 1) % 6 == 0` (e.g. 7, 13, 19, 25, ..., 163).

Default 848×480 (Mochi's only released resolution; 720p HD never shipped).
"""
from __future__ import annotations

from typing import Any

from generate.comfy_config import ComfyRunConfig

# Mochi 1 was only trained at 848×480 (480p preview). Higher res is OOD.
DEFAULTS: dict[str, Any] = {
    "transformer": "mochi_preview_bf16.safetensors",
    "vae_model": "mochi_vae.safetensors",
    "clip_model": "t5xxl_fp16.safetensors",
    "width": 848,
    "height": 480,
    "num_frames": 163,         # 5.4s @ 30fps; constraint (length-1)%6==0
    "fps": 30,
    "steps": 50,
    "cfg": 4.5,
    "sampler": "euler",
    "scheduler": "simple",
    "seed": 42,
    "negative_prompt": "",
    "weight_dtype": "default",
}


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: "Path | None" = None,
) -> dict:
    """Build the Mochi T2V graph. `first_frame_*` args are accepted but unused
    (T2V has no first-frame conditioning) — kept to match the standard
    workflow signature in `comfy_batch_run.build_workflow(...)` calls.
    """
    k = {**DEFAULTS, **cfg.model_kwargs}

    # Frame-count constraint
    if (k["num_frames"] - 1) % 6 != 0:
        raise ValueError(
            f"Mochi requires (num_frames-1) % 6 == 0, got {k['num_frames']}"
        )

    return {
        "unet": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": k["transformer"],
                "weight_dtype": k["weight_dtype"],
            },
        },
        "vae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": k["vae_model"]},
        },
        "clip": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": k["clip_model"], "type": "mochi"},
        },
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["clip", 0], "text": prompt_text},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["clip", 0], "text": k["negative_prompt"]},
        },
        "latent": {
            "class_type": "EmptyMochiLatentVideo",
            "inputs": {
                "width": k["width"],
                "height": k["height"],
                "length": k["num_frames"],
                "batch_size": 1,
            },
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["unet", 0],
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "latent_image": ["latent", 0],
                "seed": k["seed"],
                "steps": k["steps"],
                "cfg": k["cfg"],
                "sampler_name": k["sampler"],
                "scheduler": k["scheduler"],
                "denoise": 1.0,
            },
        },
        "decode": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["sampler", 0], "vae": ["vae", 0]},
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
