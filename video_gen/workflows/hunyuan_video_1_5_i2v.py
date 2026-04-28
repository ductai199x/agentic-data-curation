"""HunyuanVideo 1.5 I2V (CFG-distilled, 720p) workflow.

Uses native ComfyUI nodes (PRs merged Dec 2025). Kijai's wrapper doesn't
support HY 1.5 — this path uses core `HunyuanVideo15ImageToVideo`,
`DualCLIPLoader(type=hunyuan_video_15)`, `UNETLoader`, `VAELoader`,
`CLIPVisionLoader`, `KSampler`, `ModelSamplingSD3` (shift).

Weights live at Comfy-Org/HunyuanVideo_1.5_repackaged (fp8 for H200):
  * diffusion_models/hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled.safetensors
  * vae/hunyuanvideo15_vae_fp16.safetensors  (new 32-ch VAE, NOT HY-1.0-compat)
  * text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors
  * text_encoders/byt5_small_glyphxl_fp16.safetensors
  * clip_vision/sigclip_vision_patch14_384.safetensors

CFG-distilled sweet spot: cfg=1.0, shift=7.0, ~8 steps at 720p portrait.
Community reports this beats HY 1.0 + 20-step plain on both motion and
prompt adherence (Qwen2.5-VL text encoder is much better than LLaVA-Llama).
Native 720p I2V: 1280×720, 121 frames @ 24 fps. Length must satisfy
(length-1) % 4 == 0.

Aspect preserved per-clip: pick_dims at the 720p pixel budget (921,600 px)
with stride 16.
"""
from __future__ import annotations

from typing import Any

from video_gen.comfy_config import ComfyRunConfig
from video_gen.workflows._aspect import pick_dims

# HY 1.5 720p I2V: ~1280×720 = 921,600 px budget, stride 16 (VAE 16× spatial).
_PIXEL_BUDGET = 1280 * 720
_STRIDE = 16

DEFAULTS: dict[str, Any] = {
    # Model files
    "transformer": "hunyuanvideo1.5_720p_i2v_cfg_distilled_fp8_scaled.safetensors",
    "vae_model": "hunyuanvideo15_vae_fp16.safetensors",
    "clip_qwen": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
    "clip_byt5": "byt5_small_glyphxl_fp16.safetensors",
    "clip_vision_model": "sigclip_vision_patch14_384.safetensors",
    # Sampling — CFG-distilled defaults per Tencent's official table
    "width": 1280,
    "height": 720,
    "num_frames": 121,      # 5.0s @ 24fps, (121-1)%4 == 0
    "fps": 24,
    "steps": 8,
    "cfg": 1.0,             # CFG-distilled — run at 1.0
    "shift": 7.0,           # Tencent's 720p default
    "seed": 42,
    "sampler": "euler",
    "scheduler": "simple",
    "weight_dtype": "default",  # UNETLoader loads fp8 checkpoint as-is
    "negative_prompt": "",
    # EasyCache / torch.compile are optional stacked optimizations — off by
    # default since the CFG-distilled 8-step path is already fast enough.
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

    # Source-aware aspect: preserve source AR at trained pixel budget.
    if first_frame_path is not None and "width" not in cfg.model_kwargs:
        k["width"], k["height"] = pick_dims(first_frame_path, _PIXEL_BUDGET, _STRIDE)

    nodes: dict = {
        "unet": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": k["transformer"],
                "weight_dtype": k["weight_dtype"],
            },
        },
        "clip": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": k["clip_qwen"],
                "clip_name2": k["clip_byt5"],
                "type": "hunyuan_video_15",
            },
        },
        "vae": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": k["vae_model"]},
        },
        "clip_vision": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": k["clip_vision_model"]},
        },
        "load_image": {
            "class_type": "LoadImage",
            "inputs": {"image": first_frame_name},
        },
        "clip_vision_enc": {
            "class_type": "CLIPVisionEncode",
            "inputs": {
                "clip_vision": ["clip_vision", 0],
                "image": ["load_image", 0],
                "crop": "none",
            },
        },
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["clip", 0], "text": prompt_text},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["clip", 0], "text": k["negative_prompt"]},
        },
        "i2v": {
            "class_type": "HunyuanVideo15ImageToVideo",
            "inputs": {
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "vae": ["vae", 0],
                "width": k["width"],
                "height": k["height"],
                "length": k["num_frames"],
                "batch_size": 1,
                "start_image": ["load_image", 0],
                "clip_vision_output": ["clip_vision_enc", 0],
            },
        },
        # ModelSamplingSD3 applies the flow-matching shift to the model
        "model_shift": {
            "class_type": "ModelSamplingSD3",
            "inputs": {
                "model": ["unet", 0],
                "shift": k["shift"],
            },
        },
        "sampler": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["model_shift", 0],
                "positive": ["i2v", 0],
                "negative": ["i2v", 1],
                "latent_image": ["i2v", 2],
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
    return nodes
