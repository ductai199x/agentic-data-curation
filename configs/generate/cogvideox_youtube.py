"""CogVideoX 1.5 5B I2V batch run over YouTube real clips.

50 steps, no distill (same as Instagram). T5 prompt cap at 700 chars
(CogVideoX's T5 tops out at ~226 tokens).
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[1]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/salmonn_captions_cleaned.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/cogvideox_1_5/youtube",
    workflow_module="generate.workflows.cogvideox_i2v",
    model_tag="cogvideox-1.5-5b-i2v-50step",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=3024,
    prompt_max_chars=700,
    model_kwargs={
        "force_offload": True,
    },
)
