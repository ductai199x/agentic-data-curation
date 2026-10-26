"""LTX-2.5 (Lightricks) — adaptation profile.

22B open-weight audio+video model (HF Lightricks/LTX-2.5, gated: accept the licence on the model page first).
Video collection runs generate.workflows.ltx25_i2v, built from Lightricks' official two-stage distilled 2.5
graph and the Comfy-Org 2.5 first-last-frame template (see that module's docstring for the weight layout).
The graph validates against current ComfyUI node schemas but has not been run on a GPU yet.
"""

NAME = "ltx_2_5"
DISPLAY_NAME = "LTX-2.5 (Lightricks)"
RELEASE_DATE = "2026-08-11"
MODALITY = "video"
WEIGHTS = "open"
LICENSE = "unknown (check the 2.5 model card for commercial-use terms)"

# === Video: generate/ ComfyUI workers ===
VIDEO_BACKEND = "comfy"
COMFY_WORKFLOW = "generate.workflows.ltx25_i2v"
COMFY_MODEL_KWARGS = {}          # defaults in generate.workflows.ltx25_i2v.DEFAULTS (distilled, 121 frames @ 24 fps)
COMFY_SOURCE = "instagram"
COMFY_PROMPT_SOURCE = "caption"
PAID_PROVIDER = False

# Diffusers alternative (Lightricks/LTX-2.5-Diffusers exists on the Hub): set VIDEO_BACKEND = "diffusers"
HF_REPO = "Lightricks/LTX-2.5-Diffusers"
VIDEO_NUM_FRAMES = 121
VIDEO_FPS = 24
RESOLUTIONS = [(1088, 1920), (1920, 1088)]

TARGET_SAMPLES = 300
