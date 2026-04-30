"""Open-Sora 2.0 I2V smoke test — 1 clip to /tmp for visual QA."""
from pathlib import Path

from configs.generate.opensora_youtube import OpenSoraRunConfig
from shared.paths import REPO_ROOT as REPO

CONFIG = OpenSoraRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=Path("/tmp/opensora_smoke"),
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=1,
    model_tag="opensora-2.0-11b-i2v-head-768px-50step-smoke",
)
