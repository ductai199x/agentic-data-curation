"""LTX 2.3 22B distilled FLF2V batch run over Instagram real clips — via ComfyUI.

Unifies the LTX pipeline onto the same ComfyUI-driven path as every other
generator. Uses the combined 46 GB Lightricks checkpoint directly with
ComfyUI's native LTX nodes (no custom Lightricks repo / venv needed).
"""

from pathlib import Path

from video_gen.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[1]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/salmonn_captions_cleaned.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    # Keep the same output_dir as the native-runner path (ltx_video_2.3) so
    # the ComfyUI-driven workers see the 4,095 already-generated good clips
    # and only backfill the 627 that regen_stretched deleted.
    output_dir=REPO / "data/videos/fake/ltx_video_2.3/instagram",
    workflow_module="video_gen.workflows.ltx_i2v",
    model_tag="ltx-2.3-22b-dev-lora-flf2v-1088x1920-10s",
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    model_kwargs={
        # All two-stage defaults (pixel-budget-preserving aspect @ 24 fps,
        # 241 frames, seed 42/43, dev ckpt + distilled LoRA 0.5) live in
        # video_gen.workflows.ltx_i2v.DEFAULTS.
    },
)
