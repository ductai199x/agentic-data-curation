"""Kling 2 I2V — supports detailed prompts (2500 char cap).
Cost: 295.4 credits/run → ~$1.40 per 5s clip.
"""
from __future__ import annotations
from typing import Any
from video_gen.comfy_config import ComfyRunConfig
from video_gen.workflows._aspect import pick_by_ratio

# Kling I2V aspect enum (authoritative via node schema): 16:9, 9:16, 1:1.
KLING_RATIOS = ["16:9", "9:16", "1:1"]

DEFAULTS: dict[str, Any] = {
    "model_name": "kling-v2-master",
    "cfg_scale": 0.8,
    "mode": "std",
    # "aspect_ratio" is chosen per-clip from KLING_RATIOS via the first_frame
    # unless the caller overrides it in model_kwargs.
    "duration": 5,
    "negative_prompt": "",
    "seed": 42,
}
COST_USD_PER_CLIP = 1.40

def build_workflow(cfg: ComfyRunConfig, first_frame_name: str, prompt_text: str,
                   filename_prefix: str, last_frame_name: str | None = None,
                   first_frame_path: "Path | None" = None,  # noqa: F821
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}
    aspect_ratio = (
        pick_by_ratio(first_frame_path, KLING_RATIOS)
        if first_frame_path is not None and "aspect_ratio" not in cfg.model_kwargs
        else k.get("aspect_ratio", "9:16")
    )
    return {
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "gen": {
            "class_type": "KlingImage2VideoNode",
            "inputs": {
                "start_frame": ["load_first", 0],
                "prompt": prompt_text,
                "negative_prompt": k["negative_prompt"],
                "model_name": k["model_name"],
                "cfg_scale": k["cfg_scale"],
                "mode": k["mode"],
                "aspect_ratio": aspect_ratio,
                "duration": k["duration"],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["gen", 0], "filename_prefix": filename_prefix, "format": "mp4", "codec": "h264"},
        },
    }
