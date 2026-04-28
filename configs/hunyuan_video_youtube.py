"""HunyuanVideo 1.5 I2V batch run over YouTube real clips.

Tencent HunyuanVideo 1.5 CFG-distilled at 720p, native ComfyUI nodes.
Same sampling defaults as the Instagram config (steps=8, cfg=1.0, shift=7.0)
all from video_gen.workflows.hunyuan_video_1_5_i2v.DEFAULTS.
"""

from pathlib import Path

from video_gen.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[1]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/salmonn_captions_cleaned.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/hunyuan_video_1_5/youtube",
    workflow_module="video_gen.workflows.hunyuan_video_1_5_i2v",
    model_tag="hunyuan-video-1.5-i2v-720p-cfg-distill-8step",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=3024,
    model_kwargs={},
)
