"""Wan 2.1 FLF2V-14B batch run over Instagram real clips.

First-last-frame conditioned: reuses both `_first.png` and `_last.png`
frames already extracted for the LTX run.

Uses the lightx2v I2V-14B 480p cfg-step distill LoRA on the FLF2V base —
Wan 2.1 has no FLF-native distill, but the I2V variant loads via partial
key-match because both share the I2V-14B backbone. 8 steps at cfg=1.0
(vs 30 steps + cfg=5 without distill). Measured ~183s/clip on H200 vs
~1050s/clip without LoRA (~5.7× speedup).
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/video_captions.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    output_dir=REPO / "data/videos/fake/wan_2_1_flf/instagram",
    workflow_module="generate.workflows.wan21_flf",
    model_tag="wan-2.1-flf2v-14b-720p-lightx2v-8step",
    # Top-1000 diversity-ranked clips for initial apples-to-apples set.
    # Raise max_clips later to back-fill — workers skip clips with existing
    # output mp4s, so re-launching extends without re-generation.
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    max_clips=1000,
    model_kwargs={
        "force_offload": True,
        "lora": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "lora_strength": 1.0,
        "steps": 8,
        "cfg": 1.0,
    },
)
