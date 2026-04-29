"""Sora 2 I2V — OpenAI. Supports detailed prompts for control.
Cost: Sora 2 Standard 21.10 credits/sec → 168.8 credits / ~$0.80 per 8s clip.

Sora validates the input image size against the requested `size` enum —
we pick the closest enum entry to the source's aspect ratio, then resize
the first frame to exactly match before passing to the API.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_by_size

# Sora 2 (base) accepts only 720x1280 / 1280x720. The 1024x1792 / 1792x1024
# options shown in /object_info are for `sora-2-pro` only — passing them
# to `sora-2` fails with: "Invalid size for sora-2 model, only 720x1280
# and 1280x720 are supported."
SORA2_SIZE_OPTIONS = [
    "720x1280",    # 9:16 portrait
    "1280x720",    # 16:9 landscape
]

DEFAULTS: dict[str, Any] = {
    "model": "sora-2",
    "duration": 8,   # Sora 2 only supports [4, 8, 12]
    "seed": 42,
}
COST_USD_PER_CLIP = 0.80


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: Path | None = None,
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}
    size = (
        pick_by_size(first_frame_path, SORA2_SIZE_OPTIONS)
        if first_frame_path else "720x1280"
    )
    w, h = (int(x) for x in size.split("x"))
    return {
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        # Sora requires input image to exactly match requested size
        "resize": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["load_first", 0],
                "upscale_method": "lanczos",
                "width": w,
                "height": h,
                "crop": "center",
            },
        },
        "gen": {
            "class_type": "OpenAIVideoSora2",
            "inputs": {
                "model": k["model"],
                "prompt": prompt_text,
                "size": size,
                "duration": k["duration"],
                "image": ["resize", 0],
                "seed": k["seed"],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["gen", 0], "filename_prefix": filename_prefix,
                       "format": "mp4", "codec": "h264"},
        },
    }
