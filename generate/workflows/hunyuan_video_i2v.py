"""HunyuanVideo I2V workflow builder for Kijai's ComfyUI-HunyuanVideoWrapper.

Uses the "fixed" I2V checkpoint. Native 720p, 129 frames @ 24 fps.

Reference example: `hyvideo_i2v_example_fixed_model_02.json`
The text encoder (llava-llama-3 8B) is auto-downloaded the first time the
`DownloadAndLoadHyVideoTextEncoder` node runs.
"""

from __future__ import annotations

from typing import Any

from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_dims

# Hunyuan I2V 720p pixel budget (~921,600 px), stride 16.
_PIXEL_BUDGET = 720 * 1280
_STRIDE = 16

DEFAULTS: dict[str, Any] = {
    "transformer": "hunyuan_video_I2V_720_fixed_fp8_e4m3fn.safetensors",
    "vae_model": "hunyuan_video_vae_bf16.safetensors",
    "llava_repo": "Kijai/llava-llama-3-8b-text-encoder-tokenizer",
    "clip_model_repo": "openai/clip-vit-large-patch14",
    "fastvideo_lora": None,
    "fastvideo_lora_strength": 1.0,
    "width": 720,
    "height": 1280,
    "num_frames": 129,            # 4n+1, 129 = 5.375s @ 24fps
    "fps": 24,
    "steps": 30,
    "embedded_cfg": 6.0,
    "shift": 9.0,
    "seed": 42,
    "scheduler": "FlowMatchDiscreteScheduler",
    "attention_mode": "sdpa",
    "model_precision": "bf16",
    "text_encoder_precision": "bf16",
    "vae_precision": "bf16",
    "quantization": "disabled",
    "force_offload": True,
    "enable_vae_tiling_decode": True,
    "negative_prompt": "",
    "prompt_template": "I2V_video",
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

    # Source-aware aspect — preserve source AR at trained pixel budget.
    if first_frame_path is not None and "width" not in cfg.model_kwargs:
        k["width"], k["height"] = pick_dims(first_frame_path, _PIXEL_BUDGET, _STRIDE)

    nodes: dict = {
        "text_encoders": {
            "class_type": "DownloadAndLoadHyVideoTextEncoder",
            "inputs": {
                "llm_model": k["llava_repo"],
                "clip_model": k["clip_model_repo"],
                "precision": k["text_encoder_precision"],
                "load_device": "offload_device",
                "quantization": "disabled",
            },
        },
        "vae": {
            "class_type": "HyVideoVAELoader",
            "inputs": {"model_name": k["vae_model"], "precision": k["vae_precision"]},
        },
        "load_image": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        # Resize source image to match sampler (width, height). HyVideoEncode
        # otherwise passes raw pixels through and produces a mismatched-shape
        # latent when the source AR differs from the default.
        "resize_image": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["load_image", 0],
                "width": k["width"],
                "height": k["height"],
                "upscale_method": "lanczos",
                "crop": "disabled",
            },
        },
        # Text + image → hyvid_embeds
        "hyvid_embeds": {
            "class_type": "HyVideoI2VEncode",
            "inputs": {
                "text_encoders": ["text_encoders", 0],
                "prompt": prompt_text,
                "image": ["resize_image", 0],
                "force_offload": k["force_offload"],
                "prompt_template": k["prompt_template"],
            },
        },
        # Image → latent conditioning
        "image_latents": {
            "class_type": "HyVideoEncode",
            "inputs": {
                "vae": ["vae", 0],
                "image": ["resize_image", 0],
                "enable_vae_tiling": True,
                "temporal_tiling_sample_size": 64,
                "spatial_tile_sample_min_size": 256,
                "auto_tile_size": True,
            },
        },
        "model": {
            "class_type": "HyVideoModelLoader",
            "inputs": {
                "model": k["transformer"],
                "base_precision": k["model_precision"],
                "quantization": k["quantization"],
                "load_device": "main_device",
                "attention_mode": k["attention_mode"],
            },
        },
        "sampler": {
            "class_type": "HyVideoSampler",
            "inputs": {
                "model": ["model", 0],
                "hyvid_embeds": ["hyvid_embeds", 0],
                "image_cond_latents": ["image_latents", 0],
                "width": k["width"],
                "height": k["height"],
                "num_frames": k["num_frames"],
                "steps": k["steps"],
                "embedded_guidance_scale": k["embedded_cfg"],
                "flow_shift": k["shift"],
                "seed": k["seed"],
                "force_offload": k["force_offload"],
                "scheduler": k["scheduler"],
                "denoise_strength": 1.0,
            },
        },
        "decode": {
            "class_type": "HyVideoDecode",
            "inputs": {
                "vae": ["vae", 0],
                "samples": ["sampler", 0],
                "enable_vae_tiling": k["enable_vae_tiling_decode"],
                "temporal_tiling_sample_size": 64,
                "spatial_tile_sample_min_size": 256,
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

    if k["fastvideo_lora"]:
        nodes["lora"] = {
            "class_type": "HyVideoLoraSelect",
            "inputs": {
                "lora": k["fastvideo_lora"],
                "strength": k["fastvideo_lora_strength"],
            },
        }
        nodes["model"]["inputs"]["lora"] = ["lora", 0]

    return nodes
