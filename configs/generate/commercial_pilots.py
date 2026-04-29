"""Commercial provider pilot configs — all providers, Instagram top-K diverse clips.

Import individual configs from here, or use the convenience `ALL_PILOTS` list.
Each pilot targets the top-N clips from the diversity ranking with appropriate
prompt_source + prompt_max_chars per provider's documented requirements.

Prompt strategy (from official provider docs):
  - Full SALMONN caption ("caption"): Veo 3, Sora 2, Kling 2
  - Short Qwen-rewritten ("short_caption"): Luma, Runway, Hailuo
"""

from pathlib import Path
from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[1]

_COMMON = dict(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/salmonn_captions_cleaned.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    paid_provider=True,
    # Multiple providers run in parallel sharing the same ComfyUI input/ dir.
    # Don't delete frames after use or other workers can't find them.
    delete_input_frame_after_use=False,
)

# ── Luma Ray 2 ──────────────────────────────────────────────────────────────
# CALIBRATED: 213.56 credits = $1.01/clip (pricing table is wrong for Luma)
LUMA_PILOT = ComfyRunConfig(
    **_COMMON,
    output_dir=REPO / "data/videos/fake/luma_ray2/instagram",
    workflow_module="generate.workflows.luma_ray2_i2v",
    model_tag="luma-ray-2-i2v-720p-5s",
    max_clips=47,                       # 22 done + 25 new, top-47 covers all 22 done (max rank 27)
    prompt_source="short_caption",
    prompt_max_chars=200,
    cost_per_clip_usd=1.01,             # calibrated 2026-04-16
    max_cost_usd=28.00,                 # 25 new × 1.01 + ~10% buffer
)

# ── Runway Gen-4 Turbo ──────────────────────────────────────────────────────
# CALIBRATED: 75.44 credits = $0.36/clip
RUNWAY_PILOT = ComfyRunConfig(
    **_COMMON,
    output_dir=REPO / "data/videos/fake/runway_gen4/instagram",
    workflow_module="generate.workflows.runway_gen4_i2v",
    model_tag="runway-gen4-turbo-i2v-720p-5s",
    max_clips=65,                       # 15 done + 50 new
    prompt_source="short_caption",      # hard 1000 char cap
    prompt_max_chars=500,
    cost_per_clip_usd=0.36,             # calibrated 2026-04-16
    max_cost_usd=22.00,                 # 50 new × 0.36 + ~20% buffer
)

# ── Google Veo 3.0 Fast I2V ──────────────────────────────────────────────────
# CALIBRATED 2026-04-16: 168.80 credits = $0.80/clip ✓ matches table.
# Veo 3.1 Fast FLF attempted but our comfy.org account lacks Google Vertex
# access to the 3.1-fast-preview model — see workflow docstring for details.
VEO3_PILOT = ComfyRunConfig(
    **_COMMON,
    output_dir=REPO / "data/videos/fake/veo3/instagram",
    workflow_module="generate.workflows.veo3_i2v",
    model_tag="veo3-0-fast-i2v-8s",
    max_clips=150,                      # far beyond 33 so filter attrition doesn't prematurely end
    prompt_source="caption",            # Veo: "the more detail, the more control"
    prompt_max_chars=1500,
    cost_per_clip_usd=0.80,             # Fast model, recalibrated 2026-04-16 ✓
    max_cost_usd=120.00,                # startup-refuse gate only; real cap = balance check
)

# ── OpenAI Sora 2 Standard ──────────────────────────────────────────────────
# CALIBRATED: 168.80 credits = $0.80/clip ✓ matches table
SORA2_PILOT = ComfyRunConfig(
    **_COMMON,
    output_dir=REPO / "data/videos/fake/sora2/instagram",
    workflow_module="generate.workflows.sora2_i2v",
    model_tag="sora-2-std-i2v-720x1280-8s",
    max_clips=150,                      # far beyond 39 so moderation attrition doesn't prematurely end
    prompt_source="caption",            # detail = more control per OpenAI docs
    prompt_max_chars=1500,
    cost_per_clip_usd=0.80,             # calibrated 2026-04-16 ✓
    max_cost_usd=120.00,                # startup-refuse gate only; real cap = balance check
)

# ── Kling 2.6 Pro (sound off) ────────────────────────────────────────────────
# CALIBRATED: 73.85 credits = $0.35/clip ✓ matches table
KLING2_PILOT = ComfyRunConfig(
    **_COMMON,
    output_dir=REPO / "data/videos/fake/kling26/instagram",
    workflow_module="generate.workflows.kling26_i2v",
    model_tag="kling-v2-6-pro-i2v-5s",
    max_clips=70,                       # 20 done + 50 new
    prompt_source="caption",            # 2500 char cap, handles detail
    prompt_max_chars=2500,
    cost_per_clip_usd=0.35,             # calibrated 2026-04-16 ✓
    max_cost_usd=22.00,                 # 50 new × 0.35 + ~25% buffer
)

# ── MiniMax Hailuo 02 ───────────────────────────────────────────────────────
# CALIBRATED: 59.08 credits = $0.28/clip ✓ matches table
HAILUO_PILOT = ComfyRunConfig(
    **_COMMON,
    output_dir=REPO / "data/videos/fake/hailuo02/instagram",
    workflow_module="generate.workflows.hailuo02_i2v",
    model_tag="hailuo-02-i2v-768p-6s",
    max_clips=70,                       # 20 done + 50 new
    prompt_source="short_caption",      # structured, moderate
    prompt_max_chars=500,
    cost_per_clip_usd=0.28,
    max_cost_usd=18.00,                 # 50 new × 0.28 + ~25% buffer
)

# ── Convenience: all pilots ─────────────────────────────────────────────────
ALL_PILOTS = {
    "luma": LUMA_PILOT,
    "runway": RUNWAY_PILOT,
    "veo3": VEO3_PILOT,
    "sora2": SORA2_PILOT,
    "kling2": KLING2_PILOT,
    "hailuo": HAILUO_PILOT,
}
