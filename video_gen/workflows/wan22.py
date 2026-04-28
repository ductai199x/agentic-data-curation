"""Wan 2.2 I2V workflow builder for Kijai's ComfyUI-WanVideoWrapper.

Reads all knobs from `cfg.model_kwargs`. Every field is optional — the
defaults below match our committed Instagram run.
"""

from __future__ import annotations

from typing import Any

from video_gen.comfy_config import ComfyRunConfig
from video_gen.workflows._aspect import pick_dims

# Wan 2.2 I2V 720p pixel budget (~921,600 px), stride 16. Source aspect is
# preserved exactly; only pixel-count + stride alignment enforced.
_PIXEL_BUDGET = 720 * 1280
_STRIDE = 16

# Default model_kwargs — override any of these via the config's model_kwargs
DEFAULTS: dict[str, Any] = {
    # model weights (names resolve inside ComfyUI's models/ dirs)
    "high_model": "Wan2_2-I2V-A14B-HIGH_bf16.safetensors",
    "low_model": "Wan2_2-I2V-A14B-LOW_bf16.safetensors",
    "vae_model": "Wan2_1_VAE_bf16.safetensors",  # I2V-A14B trained on 2.1 VAE
    "text_encoder": "umt5-xxl-enc-bf16.safetensors",
    # distillation LoRAs (None to disable)
    "high_lora": "Wan_2_2_I2V_A14B_HIGH_lightx2v_4step_lora_260412_rank_64_fp16.safetensors",
    "low_lora": "Wan_2_2_I2V_A14B_LOW_lightx2v_4step_lora_260412_rank_64_fp16.safetensors",
    "high_lora_strength": 1.0,
    "low_lora_strength": 1.0,
    # sampling
    "width": 720,
    "height": 1280,
    "num_frames": 81,
    "fps": 16,
    "steps": 8,
    "cfg": 1.0,
    "shift": 5.0,
    "seed": 42,
    "scheduler": "unipc",
    # runtime
    "attention_mode": "sdpa",
    "model_precision": "bf16",
    "text_encoder_precision": "bf16",
    "vae_precision": "bf16",
    "quantization": "disabled",
    "force_offload": True,
    "tiled_vae_encode": False,
    "enable_vae_tiling_decode": False,
    # prompts
    "negative_prompt": (
        "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
        "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
        "画得不好的脸部，畸形的，毁容的，形态畸形的肢体"
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
    k = {**DEFAULTS, **cfg.model_kwargs}

    # Source-aware aspect: preserve the source's exact AR at the model's
    # trained pixel budget. Caller can still override via model_kwargs.
    if first_frame_path is not None and "width" not in cfg.model_kwargs:
        k["width"], k["height"] = pick_dims(first_frame_path, _PIXEL_BUDGET, _STRIDE)

    image_embeds_inputs = {
        "vae": ["vae", 0],
        "start_image": ["load_image", 0],
        "width": k["width"],
        "height": k["height"],
        "num_frames": k["num_frames"],
        "noise_aug_strength": 0.0,
        "start_latent_strength": 1.0,
        "end_latent_strength": 1.0,
        "force_offload": k["force_offload"],
        "fun_or_fl2v_model": False,
    }
    if k["tiled_vae_encode"]:
        image_embeds_inputs["tiled_vae"] = True

    nodes: dict = {
        "t5": {
            "class_type": "LoadWanVideoT5TextEncoder",
            "inputs": {
                "model_name": k["text_encoder"],
                "precision": k["text_encoder_precision"],
                "load_device": "offload_device",
                "quantization": "disabled",
            },
        },
        "vae": {
            "class_type": "WanVideoVAELoader",
            "inputs": {"model_name": k["vae_model"], "precision": k["vae_precision"]},
        },
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
        "load_image": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "image_embeds": {"class_type": "WanVideoImageToVideoEncode", "inputs": image_embeds_inputs},
    }

    # HIGH loader + optional LoRA
    high_loader_inputs = {
        "model": k["high_model"],
        "base_precision": k["model_precision"],
        "load_device": "main_device",
        "quantization": k["quantization"],
        "attention_mode": k["attention_mode"],
    }
    if k["high_lora"]:
        nodes["lora_high"] = {
            "class_type": "WanVideoLoraSelect",
            "inputs": {
                "lora": k["high_lora"],
                "strength": k["high_lora_strength"],
                "low_mem_load": False,
            },
        }
        high_loader_inputs["lora"] = ["lora_high", 0]
    nodes["model_high"] = {"class_type": "WanVideoModelLoader", "inputs": high_loader_inputs}

    # LOW loader + optional LoRA
    low_loader_inputs = {
        "model": k["low_model"],
        "base_precision": k["model_precision"],
        "load_device": "main_device",
        "quantization": k["quantization"],
        "attention_mode": k["attention_mode"],
    }
    if k["low_lora"]:
        nodes["lora_low"] = {
            "class_type": "WanVideoLoraSelect",
            "inputs": {
                "lora": k["low_lora"],
                "strength": k["low_lora_strength"],
                "low_mem_load": False,
            },
        }
        low_loader_inputs["lora"] = ["lora_low", 0]
    nodes["model_low"] = {"class_type": "WanVideoModelLoader", "inputs": low_loader_inputs}

    # MoE chain: HIGH does first half of steps, LOW finishes
    steps = k["steps"]
    common_sampler = {
        "text_embeds": ["text_embeds", 0],
        "image_embeds": ["image_embeds", 0],
        "steps": steps,
        "cfg": k["cfg"],
        "shift": k["shift"],
        "seed": k["seed"],
        "force_offload": k["force_offload"],
        "scheduler": k["scheduler"],
        "riflex_freq_index": 0,
        "denoise_strength": 1.0,
    }
    nodes["sampler_high"] = {
        "class_type": "WanVideoSampler",
        "inputs": {
            **common_sampler,
            "model": ["model_high", 0],
            "start_step": 0,
            "end_step": steps // 2,
        },
    }
    nodes["sampler_low"] = {
        "class_type": "WanVideoSampler",
        "inputs": {
            **common_sampler,
            "model": ["model_low", 0],
            "samples": ["sampler_high", 0],
            "start_step": steps // 2,
            "end_step": steps,
        },
    }
    nodes["decode"] = {
        "class_type": "WanVideoDecode",
        "inputs": {
            "vae": ["vae", 0],
            "samples": ["sampler_low", 0],
            "enable_vae_tiling": k["enable_vae_tiling_decode"],
            "tile_x": 272,
            "tile_y": 272,
            "tile_stride_x": 144,
            "tile_stride_y": 128,
        },
    }
    nodes["save"] = {
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
    }
    return nodes
