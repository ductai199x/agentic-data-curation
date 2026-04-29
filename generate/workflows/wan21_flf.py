"""Wan 2.1 FLF2V-14B workflow builder for Kijai's ComfyUI-WanVideoWrapper.

First-last-frame conditioned. Native 720p (720×1280), 81 frames, 16 fps.
No official 4-step distill LoRA for FLF2V exists yet — runs ~30 steps.
"""

from __future__ import annotations

from typing import Any

from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_dims

# Wan 2.1 FLF2V-14B 720P: ~921,600 pixel budget (= 720 × 1280), stride 16.
# Source aspect is preserved exactly; only pixel-count + stride alignment
# are enforced. Non-9:16 sources no longer get stretched.
_PIXEL_BUDGET = 720 * 1280
_STRIDE = 16

DEFAULTS: dict[str, Any] = {
    "model": "Wan2_1-FLF2V-14B-720P_fp8_e4m3fn.safetensors",
    "vae_model": "Wan2_1_VAE_bf16.safetensors",
    "text_encoder": "umt5-xxl-enc-bf16.safetensors",
    "clip_vision_model": "clip_vision_h.safetensors",  # IP-Adapter's CLIP vision H
    # Optional cfg-step distill LoRA. Wan 2.1 I2V lightx2v loads on the FLF2V
    # base with partial-key match; architecturally compatible since FLF2V shares
    # the I2V-14B backbone. With the LoRA at strength 1.0 we run at cfg=1.0 and
    # 4-8 steps — ~4-6× faster. Set to None to disable.
    "lora": None,
    "lora_strength": 1.0,
    # Per-clip (width, height) are overridden by pick_dims() based on the
    # source frame's aspect; these defaults are only a fallback.
    "width": 720,
    "height": 1280,
    "num_frames": 81,
    "fps": 16,
    "steps": 30,
    "cfg": 5.0,
    "shift": 5.0,
    "seed": 42,
    "scheduler": "unipc",
    "attention_mode": "sdpa",
    "model_precision": "bf16",               # compute dtype (fp8 weight loads under this)
    "text_encoder_precision": "bf16",
    "vae_precision": "bf16",
    "quantization": "fp8_e4m3fn",            # actual weight precision
    "force_offload": True,
    "tiled_vae_encode": False,
    "enable_vae_tiling_decode": False,
    "negative_prompt": (
        "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
        "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部"
    ),
}


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: "Path | None" = None,
) -> dict:
    if last_frame_name is None:
        raise ValueError("Wan 2.1 FLF2V requires both first and last frames")

    k = {**DEFAULTS, **cfg.model_kwargs}

    # Source-aware aspect: preserve the source's exact AR at the model's
    # trained pixel budget. Caller can still override via model_kwargs.
    if first_frame_path is not None and "width" not in cfg.model_kwargs:
        k["width"], k["height"] = pick_dims(first_frame_path, _PIXEL_BUDGET, _STRIDE)

    nodes: dict = {
        # ---- encoders ----
        "t5": {
            "class_type": "LoadWanVideoT5TextEncoder",
            "inputs": {
                "model_name": k["text_encoder"],
                "precision": k["text_encoder_precision"],
                "load_device": "offload_device",
                "quantization": "disabled",
            },
        },
        "clip_vision": {
            "class_type": "CLIPVisionLoader",
            "inputs": {"clip_name": k["clip_vision_model"]},
        },
        "vae": {
            "class_type": "WanVideoVAELoader",
            "inputs": {"model_name": k["vae_model"], "precision": k["vae_precision"]},
        },
        # ---- inputs ----
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "load_last": {"class_type": "LoadImage", "inputs": {"image": last_frame_name}},
        "text_embeds": {
            "class_type": "WanVideoTextEncode",
            "inputs": {
                "t5": ["t5", 0],
                "positive_prompt": prompt_text,
                "negative_prompt": k["negative_prompt"],
                "force_offload": k["force_offload"],
                "use_disk_cache": False,
            },
        },
        # ---- FLF clip-vision embed over both frames ----
        "clip_embeds": {
            "class_type": "WanVideoClipVisionEncode",
            "inputs": {
                "clip_vision": ["clip_vision", 0],
                "image_1": ["load_first", 0],
                "image_2": ["load_last", 0],
                "strength_1": 1.0,
                "strength_2": 1.0,
                "crop": "center",
                "combine_embeds": "average",
                "force_offload": k["force_offload"],
            },
        },
        "image_embeds": {
            "class_type": "WanVideoImageToVideoEncode",
            "inputs": {
                "vae": ["vae", 0],
                "clip_embeds": ["clip_embeds", 0],
                "start_image": ["load_first", 0],
                "end_image": ["load_last", 0],
                "width": k["width"],
                "height": k["height"],
                "num_frames": k["num_frames"],
                "noise_aug_strength": 0.0,
                "start_latent_strength": 1.0,
                "end_latent_strength": 1.0,
                "force_offload": k["force_offload"],
                "fun_or_fl2v_model": True,
            },
        },
        "model": {
            "class_type": "WanVideoModelLoader",
            "inputs": {
                "model": k["model"],
                "base_precision": k["model_precision"],
                "load_device": "main_device",
                "quantization": k["quantization"],
                "attention_mode": k["attention_mode"],
            },
        },
        "sampler": {
            "class_type": "WanVideoSampler",
            "inputs": {
                "model": ["model", 0],
                "text_embeds": ["text_embeds", 0],
                "image_embeds": ["image_embeds", 0],
                "steps": k["steps"],
                "cfg": k["cfg"],
                "shift": k["shift"],
                "seed": k["seed"],
                "force_offload": k["force_offload"],
                "scheduler": k["scheduler"],
                "riflex_freq_index": 0,
                "denoise_strength": 1.0,
            },
        },
        "decode": {
            "class_type": "WanVideoDecode",
            "inputs": {
                "vae": ["vae", 0],
                "samples": ["sampler", 0],
                "enable_vae_tiling": k["enable_vae_tiling_decode"],
                "tile_x": 272,
                "tile_y": 272,
                "tile_stride_x": 144,
                "tile_stride_y": 128,
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

    # Optional cfg-step distill LoRA (e.g. lightx2v I2V-14B 480p applied to
    # FLF2V base). Loads via WanVideoLoraSelect, attaches to the model loader.
    if k.get("lora"):
        nodes["lora_select"] = {
            "class_type": "WanVideoLoraSelect",
            "inputs": {
                "lora": k["lora"],
                "strength": k["lora_strength"],
                "low_mem_load": False,
            },
        }
        nodes["model"]["inputs"]["lora"] = ["lora_select", 0]

    return nodes
