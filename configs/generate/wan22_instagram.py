"""Wan 2.2 I2V-A14B batch run over Instagram real clips.

Kijai's ComfyUI-WanVideoWrapper + Lightx2v 4-step distill LoRAs on both
HIGH/LOW experts. 8 sampling steps (4 HIGH + 4 LOW MoE chain), cfg=1.0,
force_offload=True. Aspect is computed per-clip via pick_dims at the 720p
pixel budget (see generate/workflows/wan22.py).
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[1]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/salmonn_captions_cleaned.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    output_dir=REPO / "data/videos/fake/wan_2_2/instagram",
    workflow_module="generate.workflows.wan22",
    model_tag="wan-2.2-i2v-a14b-lightx2v-8step",
    model_kwargs={
        "force_offload": True,
        # Everything else inherits from generate.workflows.wan22.DEFAULTS
    },
)
