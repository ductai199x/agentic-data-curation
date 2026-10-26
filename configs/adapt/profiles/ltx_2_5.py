"""LTX-2.5 (Lightricks) — adaptation profile.

22B open-weight audio+video model, HF repo Lightricks/LTX-2.5, ComfyUI templates for I2V and first-last-frame
from day one (comfyui-wiki news page, Aug 11 2026). Files listed there: ltx-2.5-22b-dev-transformer-bf16.safetensors,
ltx-2.5-22b-distilled-transformer-bf16.safetensors, a Gemma-4-12B text encoder with LTX projection, separate video
and audio VAEs, 2x spatial and 2x temporal latent upscalers, a distilled LoRA ("450").

NOT VERIFIED ON GPU: generate.workflows.ltx_i2v is built for LTX 2.3's combined checkpoint + Gemma-3. 2.5 ships split
transformer / VAE / text-encoder files, so it most likely needs its own builder (ltx25_i2v) modeled on the official
2.5 I2V template. Until then a real collect will fail at ComfyUI /prompt validation, which is the intended stop.
"""

NAME = "ltx_2_5"
DISPLAY_NAME = "LTX-2.5 (Lightricks)"
RELEASE_DATE = "2026-08-11"
MODALITY = "video"
WEIGHTS = "open"
LICENSE = "unknown (check the 2.5 model card for commercial-use terms)"

# === Video: generate/ ComfyUI workers ===
VIDEO_BACKEND = "comfy"
COMFY_WORKFLOW = "generate.workflows.ltx_i2v"   # TODO: swap for an ltx25_i2v builder (see docstring)
COMFY_MODEL_KWARGS = {
    "checkpoint": "ltx-2.5-22b-dev-transformer-bf16.safetensors",
}
COMFY_SOURCE = "instagram"
COMFY_PROMPT_SOURCE = "caption"
PAID_PROVIDER = False

# Diffusers alternative (Lightricks/LTX-2.5-Diffusers exists on the Hub): set VIDEO_BACKEND = "diffusers"
HF_REPO = "Lightricks/LTX-2.5-Diffusers"
VIDEO_NUM_FRAMES = 121
VIDEO_FPS = 24
RESOLUTIONS = [(960, 544), (544, 960)]

TARGET_SAMPLES = 300
