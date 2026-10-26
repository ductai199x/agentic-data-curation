"""Qwen-Image-2.1-Turbo — adaptation profile.

Alibaba Qwen team, 8-step distilled turbo of Qwen-Image-2.1 (7B visual generator).
Facts below are from a third-party write-up (orcarouter.ai, Oct 2026), not yet checked against the model card:
repo Qwen/Qwen-Image-2.1-Turbo appeared on Hugging Face Oct 9, 2026; bf16 weights; same pipeline class as the
base model (QwenImage21Pipeline); 8 steps with the schedule stored in the checkpoint; CFG 1.
"""

NAME = "qwen_image_2_1_turbo"
DISPLAY_NAME = "Qwen-Image-2.1-Turbo (Alibaba Qwen)"
RELEASE_DATE = "2026-10-09"
MODALITY = "image"
WEIGHTS = "open"
LICENSE = "Qwen Research License (non-commercial research; commercial use needs a separate agreement)"

# === Open weights: generation ===
HF_REPO = "Qwen/Qwen-Image-2.1-Turbo"
HF_REVISION = None
TORCH_DTYPE = "bfloat16"
GENERATION_KWARGS = {"num_inference_steps": 8, "guidance_scale": 1.0}
RESOLUTIONS = [   # the seven presets reported for the model
    (2048, 2048), (2400, 1792), (1792, 2400), (2528, 1696), (1696, 2528), (2752, 1536), (1536, 2752),
]

# === Structural (same meaning as configs/*.py) ===
EXPECTED_FORMATS = ["PNG"]
MIN_PIXELS = 200_000
MAX_PIXELS = 7_000_000
KNOWN_ASPECT_RATIOS = [(1, 1), (4, 3), (3, 4), (3, 2), (2, 3), (16, 9), (9, 16)]

TARGET_SAMPLES = 500
PROMPT_MIX = {"photo": 0.8, "art": 0.2}
