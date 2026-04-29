"""Runway Gen-4 Turbo I2V — 1000 char prompt cap, short prompts required.

Cost: 10.55 credits/sec → 52.75 credits / ~$0.25 per 5s clip.

Aspect ratio is auto-detected from the source first frame against Gen-4
Turbo's supported enum (six options spanning 1:1 through 21:9 in both
orientations).
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_by_ratio

# Gen-4 Turbo aspect enum (authoritative via /object_info on 2026-04-16)
GEN4_RATIO_OPTIONS = [
    "1280:720",   # 16:9 landscape
    "720:1280",   # 9:16 portrait
    "1104:832",   # ~4:3 landscape
    "832:1104",   # ~3:4 portrait
    "960:960",    # 1:1 square
    "1584:672",   # 21:9 ultra-wide
]

DEFAULTS: dict[str, Any] = {
    "duration": 5,
    "seed": 42,
}
COST_USD_PER_CLIP = 0.25


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: Path | None = None,
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}
    ratio = (
        pick_by_ratio(first_frame_path, GEN4_RATIO_OPTIONS)
        if first_frame_path else "720:1280"
    )
    return {
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "gen": {
            "class_type": "RunwayImageToVideoNodeGen4",
            "inputs": {
                "prompt": prompt_text,
                "start_frame": ["load_first", 0],
                "duration": k["duration"],
                "ratio": ratio,
                "seed": k["seed"],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["gen", 0], "filename_prefix": filename_prefix,
                       "format": "mp4", "codec": "h264"},
        },
    }
