"""Pyramid Flow miniFLUX 768p I2V on real YouTube clips.

Bucket-locked to 1280×768 (16:9). Source first frame is center-crop scaled
to fit. temp=16 → ~5 s @ 24 fps (≈128 frames).

video_guidance bumped from default 5.0 → 7.0. Per the upstream repo: "a
larger value...mitigates the autoregressive generation degradation" — the
mangling visible at end-of-clip with vg=5 cleans up visibly at vg=7
(smoke A/B confirmed).
"""
from pathlib import Path

from generate.comfy_config import ComfyRunConfig
from shared.paths import REPO_ROOT as REPO

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/pyramid_flow/youtube",
    workflow_module="generate.workflows.pyramid_flow_i2v",
    model_tag="pyramid-flow-miniflux-768p-i2v-3stage",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=5000,
    prompt_max_chars=512,
    model_kwargs={"video_guidance": 7.0},
)
