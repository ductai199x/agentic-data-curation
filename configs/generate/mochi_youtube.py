"""Mochi 1 (Genmo) T2V on real YouTube clips.

T2V means we ignore the source clip's first frame — only the SALMONN caption
conditions generation. The source clip serves only as a stem identifier and
diversity-rank lookup; the resulting fake clip has no spatial relation to
the real source.

Defaults: 848×480, 121 frames @ 30 fps (~4.03 s), 50 steps euler, cfg=4.5.

Frame-count rationale: Mochi's documented examples use 31 (API default) or
84 (Diffusers). Per Genmo blog, durations up to 5.4s (163 frames) are
supported. 121 frames is a middle ground — closer to the 5s standard of the
other generators in this dataset, ~30% faster than 163 frames, well within
the documented operating range.
"""
from pathlib import Path

from generate.comfy_config import ComfyRunConfig
from shared.paths import REPO_ROOT as REPO

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/mochi_1/youtube",
    workflow_module="generate.workflows.mochi_t2v",
    model_tag="mochi-1-preview-t2v-50step-121f",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=5000,
    prompt_max_chars=512,
    model_kwargs={"num_frames": 121},
)
