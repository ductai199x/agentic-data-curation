"""MiniMax Hailuo 02 I2V — structured moderate prompts (2000 char cap).
Cost: 59.08 credits/run → ~$0.28 per 6s 768p clip.

Aspect: inferred server-side from `first_frame_image`. Verified empirically
against our mixed Instagram set — Hailuo produced 768×1364 (9:16),
768×768 (1:1), 768×960 (4:5), 1364×768 (16:9), all matching source aspect.
"""
from __future__ import annotations
from typing import Any
from generate.comfy_config import ComfyRunConfig

DEFAULTS: dict[str, Any] = {
    "duration": 6,
    "resolution": "768P",
    "prompt_optimizer": False,   # keep our prompt, don't let hailuo rewrite
    "seed": 42,
}
COST_USD_PER_CLIP = 0.28

def build_workflow(cfg: ComfyRunConfig, first_frame_name: str, prompt_text: str,
                   filename_prefix: str, last_frame_name: str | None = None,
                   first_frame_path=None) -> dict:
    # aspect/size are inferred from first_frame_image by Hailuo's API
    k = {**DEFAULTS, **cfg.model_kwargs}
    return {
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "gen": {
            "class_type": "MinimaxHailuoVideoNode",
            "inputs": {
                "prompt_text": prompt_text,
                "first_frame_image": ["load_first", 0],
                "duration": k["duration"],
                "resolution": k["resolution"],
                "prompt_optimizer": k["prompt_optimizer"],
                "seed": k["seed"],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["gen", 0], "filename_prefix": filename_prefix, "format": "mp4", "codec": "h264"},
        },
    }
