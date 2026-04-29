"""CogVideoX smoke test — single-clip run with new TeaCache + DPM + sageattn config.

Output goes to a sidecar dir so it doesn't collide with the real YT run.
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/cogvideox_1_5/smoketest",
    workflow_module="generate.workflows.cogvideox_i2v",
    model_tag="cogvideox-1.5-5b-i2v-30step-teacache-dpm-sageattn",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=1,
    prompt_max_chars=700,
    model_kwargs={
        "force_offload": True,
    },
)
