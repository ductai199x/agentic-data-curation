"""Open-Sora 2.0 (HPC-AI Tech) I2V on real YouTube clips.

Driven by `generate.opensora_run` (NOT `generate.comfy_batch_run`) — Open-Sora
has no production ComfyUI integration; we subprocess their native
`scripts/diffusion/inference.py` instead.

Defaults: 768px @ 16:9, 129 frames @ 24 fps (~5.4 s), 50-step rectified flow.

Note: the 768px config requires multi-GPU sequence parallelism in upstream's
default mode. We launch with `--nproc_per_node 1` per shard + `--offload True`
to fit on a single H200; expect significant slowdown vs multi-GPU.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from shared.paths import REPO_ROOT as REPO


@dataclass
class OpenSoraRunConfig:
    """Open-Sora-specific runtime config — parallel to ComfyRunConfig but
    Open-Sora has its own pipeline so we don't reuse ComfyRunConfig's
    workflow_module / comfy_root / cost gates."""

    # Source data
    clips_dir: Path
    captions_path: Path
    frames_dir: Path
    rank_file: Path | None
    max_clips: int

    # Output
    output_dir: Path
    model_tag: str

    # Open-Sora-specific
    opensora_config_path: str = "configs/diffusion/inference/t2i2v_768px.py"
    cond_type: str = "i2v_head"      # or i2v_tail / i2v_loop / t2v
    aspect_ratio: str = "16:9"
    num_frames: int = 129             # must be 4k+1, ≤ 129
    fps_save: float = 24.0
    offload: bool = True

    # Caption handling (matches ComfyRunConfig fields)
    prompt_source: str = "caption"
    prompt_max_chars: int = 512


CONFIG = OpenSoraRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/opensora_2/youtube",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=4024,
    model_tag="opensora-2.0-11b-i2v-head-768px-50step",
)
