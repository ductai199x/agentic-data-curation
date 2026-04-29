"""Wan 2.1 FLF2V-14B batch run over YouTube real clips.

Uses the lightx2v I2V-14B 480p cfg-step distill LoRA on the FLF2V base
(same as Instagram config). Aspect preserved per-clip via pick_dims.
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/youtube/validated",
    captions_path=REPO / "data/videos/real/youtube/video_captions.json",
    frames_dir=REPO / "data/videos/real/youtube/frames",
    output_dir=REPO / "data/videos/fake/wan_2_1_flf/youtube",
    workflow_module="generate.workflows.wan21_flf",
    model_tag="wan-2.1-flf2v-14b-720p-lightx2v-8step",
    rank_file=REPO / "data/videos/real/youtube/diversity_rank.csv",
    max_clips=3024,
    model_kwargs={
        "force_offload": True,
        "lora": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "lora_strength": 1.0,
        "steps": 8,
        "cfg": 1.0,
    },
)
