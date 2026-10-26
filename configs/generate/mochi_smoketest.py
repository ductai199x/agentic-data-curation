"""Mochi 1 T2V smoke test — 3 clips to /tmp for visual QA.

Mirrors mochi_youtube.py but with max_clips=3, output to /tmp/mochi_smoke,
and a fixed seed so reruns are reproducible.
"""
from pathlib import Path

from generate.comfy_config import ComfyRunConfig
from shared.paths import REPO_ROOT as REPO

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=Path("/tmp/mochi_smoke"),
    workflow_module="generate.workflows.mochi_t2v",
    model_tag="mochi-1-preview-t2v-50step-smoke",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=3,
    prompt_max_chars=512,
    model_kwargs={"seed": 1234},
)
