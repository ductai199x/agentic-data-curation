"""Kling 2.6 I2V — native audio-visual generation, advanced motion control.
Uses KlingImageToVideoWithAudio node (different from older KlingImage2VideoNode).
Cost: sound off 14.77/sec → 73.85 credits / ~$0.35 per 5s clip.
      sound on  29.54/sec → 147.7 credits / ~$0.70 per 5s clip.

Aspect: inferred server-side from `start_frame`. Verified empirically against
our mixed Instagram set — Kling 2.6 produced 1080×1920 (9:16), 1440×1440 (1:1),
1920×1080 (16:9), 1288×1608 (4:5), all matching source aspect.
"""
from __future__ import annotations
from typing import Any
from video_gen.comfy_config import ComfyRunConfig

DEFAULTS: dict[str, Any] = {
    "model_name": "kling-v2-6",
    "mode": "pro",
    "duration": 5,
    "generate_audio": False,   # sound off = half the cost
    "seed": 42,
}
COST_USD_PER_CLIP_SOUND_OFF = 0.35
COST_USD_PER_CLIP_SOUND_ON = 0.70

def build_workflow(cfg: ComfyRunConfig, first_frame_name: str, prompt_text: str,
                   filename_prefix: str, last_frame_name: str | None = None,
                   first_frame_path=None) -> dict:
    # aspect is inferred from start_frame image by Kling's API — no enum to pick
    k = {**DEFAULTS, **cfg.model_kwargs}
    return {
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "gen": {
            "class_type": "KlingImageToVideoWithAudio",
            "inputs": {
                "model_name": k["model_name"],
                "start_frame": ["load_first", 0],
                "prompt": prompt_text,
                "mode": k["mode"],
                "duration": k["duration"],
                "generate_audio": k["generate_audio"],
            },
        },
        "save": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["gen", 0], "filename_prefix": filename_prefix, "format": "mp4", "codec": "h264"},
        },
    }
