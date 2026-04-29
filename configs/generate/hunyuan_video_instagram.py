"""HunyuanVideo 1.5 I2V batch run over Instagram real clips.

Tencent HunyuanVideo 1.5 (Nov 2025) — CFG-distilled at 720p. Runs via
native ComfyUI nodes (Kijai's wrapper was never updated for 1.5).

CFG-distilled 720p I2V at 8 steps is the community-reported production
sweet spot — beats HY 1.0 @ 20 steps on motion and prompt adherence.
Qwen2.5-VL text encoder fixes HY 1.0's prompt-following weakness.
Aspect is computed per-clip via pick_dims at the 720p pixel budget.
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/video_captions.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    # New output dir so prior HY 1.0 outputs stay separate.
    output_dir=REPO / "data/videos/fake/hunyuan_video_1_5/instagram",
    workflow_module="generate.workflows.hunyuan_video_1_5_i2v",
    model_tag="hunyuan-video-1.5-i2v-720p-cfg-distill-8step",
    # Top-1000 diversity-ranked clips for initial apples-to-apples set.
    # Raise max_clips later to back-fill — workers skip clips with existing
    # output mp4s, so re-launching extends without re-generation.
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    max_clips=1000,
    # All sampling defaults (steps=8, cfg=1.0, shift=7.0, 1280×720, 121f @ 24fps)
    # live in generate.workflows.hunyuan_video_1_5_i2v.DEFAULTS.
    model_kwargs={},
)
