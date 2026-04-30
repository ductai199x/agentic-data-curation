"""Wan 2.2 I2V-A14B batch run over YouTube real clips.

Same Kijai/lightx2v setup as configs/wan22_instagram.py but pointed at
the YT validated set (nested by category). Top-1008 diversity-ranked
clips (~48 per category, round-robin) selected via
data/videos/real/youtube/diversity_rank.csv.
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/wan_2_2/youtube",
    workflow_module="generate.workflows.wan22",
    model_tag="wan-2.2-i2v-a14b-lightx2v-8step",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=4024,
    model_kwargs={
        "force_offload": True,
    },
)
