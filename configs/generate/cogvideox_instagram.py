"""CogVideoX 1.5 5B I2V batch run over Instagram real clips.

Kijai's ComfyUI-CogVideoXWrapper pulls the diffusers repo on first load.
Native 1360×768, 81 frames @ 16fps. 50 steps (no distill LoRA exists).
"""

from pathlib import Path

from generate.comfy_config import ComfyRunConfig

REPO = Path(__file__).resolve().parents[2]

CONFIG = ComfyRunConfig(
    clips_dir=REPO / "data/videos/real/instagram/validated",
    captions_path=REPO / "data/videos/real/instagram/video_captions.json",
    frames_dir=REPO / "data/videos/real/instagram/frames",
    output_dir=REPO / "data/videos/fake/cogvideox_1_5/instagram",
    workflow_module="generate.workflows.cogvideox_i2v",
    model_tag="cogvideox-1.5-5b-i2v-50step",
    # Top-1000 diversity-ranked clips for initial apples-to-apples set.
    # Raise max_clips later to back-fill — workers skip clips with existing
    # output mp4s, so re-launching extends without re-generation.
    rank_file=REPO / "data/videos/real/instagram/diversity_rank.csv",
    max_clips=1000,
    # CogVideoX T5 hard-caps positive prompt at 226 tokens (~800 chars).
    # Clamp here so long SALMONN captions don't explode the TextEncode node.
    prompt_max_chars=700,
    model_kwargs={
        "force_offload": True,
    },
)
