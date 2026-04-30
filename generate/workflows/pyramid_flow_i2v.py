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
    `[10, 10, 10]`. temp_length=16 (≈64 video frames after 4× temporal
    upsampling, so ~2.7s @ 24fps). Bumping temp_length=41 gives ~10s but
    quality drops at the long-horizon end; community consensus is 16-25.
"""
from __future__ import annotations

from typing import Any

from generate.comfy_config import ComfyRunConfig

DEFAULTS: dict[str, Any] = {
    "transformer": "pyramidflow/pyramid_flow_miniflux_768_bf16.safetensors",
    "vae_model": "pyramidflow/pyramid_flow_vae_bf16.safetensors",
    "clip_l": "clip_l.safetensors",
    "t5xxl": "t5xxl_fp16.safetensors",
    "width": 1280,
    "height": 768,
    "image_steps": "20, 20, 20",
    "video_steps": "10, 10, 10",
    "temp_length": 25,        # ≈ 5s @ 24fps (after 4× temporal stride)
    "video_guidance": 5.0,
    "guidance": 7.0,
    "seed": 42,
    "fps": 24,
    "transformer_dtype": "bf16",
    "vae_dtype": "bf16",
    "fp8_transformer": False,
    "negative_prompt": (
        "cartoon style, worst quality, low quality, blurry, absolute black, "
        "absolute white, low res, extra limbs, extra digits, misplaced objects, "
        "mutated anatomy, monochrome, horror"
    ),
    "use_cfg": True,
    "vae_decode_tile_size": 256,
    "vae_decode_tile_overlap": 0.25,
    "vae_encode_tile": False,
    "vae_encode_overlap": 0.25,
    "use_fp16_attn": False,
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
        "transformer": {
            "class_type": "PyramidFlowTransformerLoader",
            "inputs": {
                "model": k["transformer"],
                "base_dtype": k["transformer_dtype"],
                "fp8": k["fp8_transformer"],
            },
        },
        "vae": {
            "class_type": "PyramidFlowVAELoader",
            "inputs": {
                "model": k["vae_model"],
                "base_dtype": k["vae_dtype"],
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
                "tile_sample_min_size": k["vae_encode_tile"],
                "window_size": k["vae_encode_overlap"],
            },
        },
        "text_encode": {
            "class_type": "PyramidFlowTextEncode",
            "inputs": {
                "clip": ["clip", 0],
                "prompt": prompt_text,
                "negative_prompt": k["negative_prompt"],
                "use_cfg": k["use_cfg"],
            },
        },
        "sampler": {
            "class_type": "PyramidFlowSampler",
            "inputs": {
                "transformer": ["transformer", 0],
                "samples": ["vae_encode", 0],
                "embeds": ["text_encode", 0],
                "width": k["width"],
                "height": k["height"],
                "first_frame_steps": k["image_steps"],
                "video_steps": k["video_steps"],
                "temp": k["temp_length"],
                "video_guidance_scale": k["video_guidance"],
                "guidance_scale": k["guidance"],
                "seed": k["seed"],
                "keep_model_loaded": False,
            },
        },
        "decode": {
            "class_type": "PyramidFlowVAEDecode",
            "inputs": {
                "vae": ["vae", 0],
                "samples": ["sampler", 0],
                "tile_sample_min_size": k["vae_decode_tile_size"],
                "window_size": k["vae_decode_tile_overlap"],
                "tile_sample": True,
                "vae_decode_to_pt": True,
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
