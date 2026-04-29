"""LTX 2.3 22B distilled FLF2V batch run over YouTube real clips.

Same HQ two-stage + distilled-LoRA setup as the Instagram config.
Per-clip aspect via pick_dims at stage-1 pixel budget (fps-clamped
round-snap — see feedback_pick_dims_round_not_floor.md).
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/ltx_video_2.3/youtube",
    workflow_module="generate.workflows.ltx_i2v",
    model_tag="ltx-2.3-22b-dev-lora-flf2v-yt",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=3024,
    model_kwargs={},
)
