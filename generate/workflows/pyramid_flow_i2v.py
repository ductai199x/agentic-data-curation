"""Pyramid Flow miniFLUX 768p I2V workflow.

Uses kijai's `ComfyUI-PyramidFlowWrapper` custom nodes (cloned to
third_party/ComfyUI/custom_nodes/). Project is effectively frozen
(last commit Nov 2024) — pin the wrapper commit if reproducibility
matters.

Weights:
  * diffusion_models/pyramidflow/pyramid_flow_miniflux_768_bf16.safetensors  (~4 GB)
  * vae/pyramidflow/pyramid_flow_vae_bf16.safetensors                         (~671 MB)
  * text_encoders/t5xxl_fp16.safetensors  (shared)
  * text_encoders/clip_l.safetensors      (shared, FLUX stack)

Resolution is bucket-locked to 1280×768 (16:9) at 768p — no arbitrary
aspect ratios. We center-crop the source first frame via ImageScale.

Sampler:
  * 3 pyramid stages, image-stage steps `[20, 20, 20]`, video-stage steps
    `[10, 10, 10]`. temp=16 → 5s, temp=31 → 10s (per the wrapper tooltip).
"""
from __future__ import annotations

from typing import Any

from generate.comfy_config import ComfyRunConfig

DEFAULTS: dict[str, Any] = {
    # Files
    "transformer": "pyramidflow/pyramid_flow_miniflux_768_bf16.safetensors",
    "vae_model": "pyramidflow/pyramid_flow_vae_bf16.safetensors",
    "clip_l": "clip_l.safetensors",
    "t5xxl": "t5xxl_fp16.safetensors",
    # Geometry (bucket-locked)
    "width": 1280,
    "height": 768,
    # Sampler
    "image_steps": "20, 20, 20",
    "video_steps": "10, 10, 10",
    "temp": 16,            # 5s; 31 = 10s
    "guidance": 7.0,       # first-frame guidance (ignored when input_latent given for I2V)
    "video_guidance": 5.0,
    "seed": 42,
    "fps": 24,
    "transformer_precision": "bf16",
    "vae_precision": "bf16",
    "enable_sequential_cpu_offload": False,
    # Text encode
    "negative_prompt": (
        "cartoon style, worst quality, low quality, blurry, absolute black, "
        "absolute white, low res, extra limbs, extra digits, misplaced objects, "
        "mutated anatomy, monochrome, horror"
    ),
    "force_offload_text": True,
    # VAE encode (image → latent)
    "vae_encode_tiling": False,
    "vae_encode_overlap": 0.25,
    # VAE decode (latent → frames)
    "vae_decode_tile_min_size": 256,
    "vae_decode_overlap": 0.25,
    "vae_decode_window_size": 2,
    "vae_decode_tiling": True,
    "keep_model_loaded": False,
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

    return {
        "model": {
            "class_type": "PyramidFlowTransformerLoader",
            "inputs": {
                "model": k["transformer"],
                "precision": k["transformer_precision"],
                "enable_sequential_cpu_offload": k["enable_sequential_cpu_offload"],
            },
        },
        "vae": {
            "class_type": "PyramidFlowVAELoader",
            "inputs": {
                "vae": k["vae_model"],
                "precision": k["vae_precision"],
            },
        },
        "clip": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": k["clip_l"],
                "clip_name2": k["t5xxl"],
                "type": "flux",
            },
        },
        "load_image": {
            "class_type": "LoadImage",
            "inputs": {"image": first_frame_name},
        },
        "image_scale": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["load_image", 0],
                "upscale_method": "lanczos",
                "width": k["width"],
                "height": k["height"],
                "crop": "center",
            },
        },
        "vae_encode": {
            "class_type": "PyramidFlowVAEEncode",
            "inputs": {
                "vae": ["vae", 0],
                "image": ["image_scale", 0],
                "enable_tiling": k["vae_encode_tiling"],
                "overlap_factor": k["vae_encode_overlap"],
            },
        },
        "text_encode": {
            "class_type": "PyramidFlowTextEncode",
            "inputs": {
                "clip": ["clip", 0],
                "positive_prompt": prompt_text,
                "negative_prompt": k["negative_prompt"],
                "force_offload": k["force_offload_text"],
            },
        },
        "sampler": {
            "class_type": "PyramidFlowSampler",
            "inputs": {
                "model": ["model", 0],
                "prompt_embeds": ["text_encode", 0],
                "width": k["width"],
                "height": k["height"],
                "first_frame_steps": k["image_steps"],
                "video_steps": k["video_steps"],
                "temp": k["temp"],
                "guidance_scale": k["guidance"],
                "video_guidance_scale": k["video_guidance"],
                "seed": k["seed"],
                "keep_model_loaded": k["keep_model_loaded"],
                "input_latent": ["vae_encode", 0],
            },
        },
        "decode": {
            "class_type": "PyramidFlowVAEDecode",
            "inputs": {
                "vae": ["vae", 0],
                "samples": ["sampler", 0],
                "tile_sample_min_size": k["vae_decode_tile_min_size"],
                "overlap_factor": k["vae_decode_overlap"],
                "window_size": k["vae_decode_window_size"],
                "enable_tiling": k["vae_decode_tiling"],
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
