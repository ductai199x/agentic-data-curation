"""Veo 3.0 Fast I2V — Google DeepMind.

NOTE: Veo 3.1 Fast FLF (Veo3FirstLastFrameNode) was attempted 2026-04-16 and
rejected by Google Vertex with "Publisher Model veo-3.1-fast-generate-preview
was not found or your project does not have access to it". Likely gated to
allow-listed accounts at Google's end — comfy.org proxy can't override.
Veo 3.1 Standard FLF ($1.60/clip) may be accessible but doubles the per-clip
cost. Staying on Veo 3.0 Fast I2V for now. If Google opens up 3.1 Fast later,
swap to Veo3FirstLastFrameNode with model="veo-3.1-fast-generate" + retest.

Cost: Veo 3.0 Fast no audio = 168.8 credits/run → ~$0.80 per 8s clip.
      Veo 3.0 Standard no audio = 337.6 credits/run → ~$1.60.

Aspect ratio is auto-detected from the source first frame.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from generate.comfy_config import ComfyRunConfig
from generate.workflows._aspect import pick_by_ratio

VEO3_ASPECT_OPTIONS = ["16:9", "9:16"]

DEFAULTS: dict[str, Any] = {
    "model": "veo-3.0-fast-generate-001",   # Fast = $0.80; Standard = $1.60
    "duration_seconds": 8,
    "generate_audio": False,
    "enhance_prompt": False,                # keep our prompt as-is
    "person_generation": "ALLOW",
    "seed": 42,
    "negative_prompt": "",
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
    aspect_ratio = (
        pick_by_ratio(first_frame_path, VEO3_ASPECT_OPTIONS)
        if first_frame_path else "9:16"
    )
    return {
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "gen": {
            "class_type": "Veo3VideoGenerationNode",
            "inputs": {
                "prompt": prompt_text,
                "aspect_ratio": aspect_ratio,
                "model": k["model"],
                "duration_seconds": k["duration_seconds"],
                "generate_audio": k["generate_audio"],
                "enhance_prompt": k["enhance_prompt"],
                "person_generation": k["person_generation"],
                "seed": k["seed"],
                "negative_prompt": k["negative_prompt"],
                "image": ["load_first", 0],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["gen", 0], "filename_prefix": filename_prefix,
                       "format": "mp4", "codec": "h264"},
        },
    }
