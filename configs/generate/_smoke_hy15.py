from pathlib import Path
from generate.comfy_config import ComfyRunConfig
from shared.paths import REPO_ROOT as REPO
CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/video_captions.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    output_dir=Path("/tmp/smoke/hy15"),
    workflow_module="generate.workflows.hunyuan_video_1_5_i2v",
    model_tag="hy-1.5-i2v-720p-cfg-distill-8step",
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    max_clips=1,
    model_kwargs={},
)
