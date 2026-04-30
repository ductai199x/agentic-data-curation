"""Pyramid Flow miniFLUX I2V smoke test — 1 clip to /tmp for visual QA."""
from pathlib import Path

from generate.comfy_config import ComfyRunConfig
from shared.paths import REPO_ROOT as REPO

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=Path("/tmp/pyramid_flow_smoke"),
    workflow_module="generate.workflows.pyramid_flow_i2v",
    model_tag="pyramid-flow-miniflux-768p-i2v-smoke",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=1,
    prompt_max_chars=512,
    model_kwargs={"seed": 1234},
)
