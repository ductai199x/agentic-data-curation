from pathlib import Path
from video_gen.comfy_config import ComfyRunConfig
REPO = Path("/home/tai/1-workdir/09-agent-data-curation")
CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/salmonn_captions_cleaned.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    output_dir=Path("/tmp/smoke/hy15"),
    workflow_module="video_gen.workflows.hunyuan_video_1_5_i2v",
    model_tag="hy-1.5-i2v-720p-cfg-distill-8step",
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    max_clips=1,
    model_kwargs={},
)
