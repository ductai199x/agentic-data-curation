"""Luma Ray 2 I2V workflow builder — uses the bundled ComfyUI-API-Nodes.

This routes outbound to Luma's API and bills the caller's comfy.org credit
balance. The local GPU is idle during the call — no compute here.

Cost: 1.93 credits/second → ~9.65 credits / ~$0.046 per 5-second clip.
"""

from __future__ import annotations

from typing import Any

from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_by_ratio


# Luma Ray 2 I2V aspect enum (authoritative via node schema):
# 16:9, 9:16, 1:1, 4:3, 3:4, 21:9, 9:21.
LUMA_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"]


DEFAULTS: dict[str, Any] = {
    "model": "ray-2",
    "resolution": "720p",     # options per Luma API-Node enum
    "duration": "5s",         # options per Luma API-Node enum
    # "aspect_ratio" is chosen per-clip from LUMA_RATIOS via the first_frame
    # unless the caller overrides it in model_kwargs. (Luma's API does infer
    # from first_image in practice, but passing the correct value is safer.)
    "loop": False,
    "seed": 42,
}


# ComfyUI Luma pricing (from docs.comfy.org/tutorials/partner-nodes/pricing)
# 1.93 credits/second of video. 211 credits = 1 USD.
COST_USD_PER_CLIP = 0.046   # 5s @ 720p


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: "Path | None" = None,  # noqa: F821
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}
    aspect_ratio = (
        pick_by_ratio(first_frame_path, LUMA_RATIOS)
        if first_frame_path is not None and "aspect_ratio" not in cfg.model_kwargs
        else k.get("aspect_ratio", "9:16")
    )

    nodes: dict = {
        "load_first": {
            "class_type": "LoadImage",
            "inputs": {"image": first_frame_name},
        },
        "gen": {
            "class_type": "LumaImageToVideoNode",
            "inputs": {
                "prompt": prompt_text,
                "model": k["model"],
                "resolution": k["resolution"],
                "duration": k["duration"],
                "aspect_ratio": aspect_ratio,
                "loop": k["loop"],
                "seed": k["seed"],
                "first_image": ["load_first", 0],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["gen", 0],
                "filename_prefix": filename_prefix,
                "format": "mp4",
                "codec": "h264",
            },
        },
    }

    # Optional end-image for FLF mode (Luma supports it natively)
    if last_frame_name:
        nodes["load_last"] = {
            "class_type": "LoadImage",
            "inputs": {"image": last_frame_name},
        }
        nodes["gen"]["inputs"]["last_image"] = ["load_last", 0]

    return nodes
