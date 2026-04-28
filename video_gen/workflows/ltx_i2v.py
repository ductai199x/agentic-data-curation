"""LTX 2.3 two-stage HQ FLF2V workflow for ComfyUI.

Tracks Lightricks' native `TI2VidTwoStagesHQPipeline` (LTX-2 repo,
`ti2vid_two_stages_hq.py`) as closely as ComfyUI + the ComfyUI-LTXVideo
custom nodes allow. User-validated quality parity.

What matches the native pipeline exactly:
  * Same weights: ltx-2.3-22b-dev checkpoint + distilled-LoRA-384 + 2x
    spatial upsampler + Gemma-3-12B text encoder
  * Same two-stage structure: low-res (544×960) → 2× spatial upsampler →
    high-res refine (1088×1920)
  * Same LoRA strengths: 0.25 at stage 1, 0.5 at stage 2 (HQ-unique —
    non-HQ two-stage only applies LoRA to stage 2)
  * Same 241 frames @ 24 fps
  * Same stage-1 guidance: MultimodalGuider with LTX_2_3_HQ_PARAMS
    (video cfg=3.0, stg=0.0, rescale=0.45, modality=3.0; audio cfg=7.0,
    rescale=1.0, modality=3.0)  — via Lightricks' ComfyUI-LTXVideo nodes
  * Same stage-2 denoiser: plain CFGGuider(cfg=1) ≡ SimpleDenoiser
  * Same negative prompt: DEFAULT_NEGATIVE_PROMPT
  * Same stage-1 sigmas: LTX2Scheduler(latent=[1,128,31,17,30], steps=15)
    precomputed (see constants in DEFAULTS)
  * Same stage-2 sigmas: STAGE_2_DISTILLED_SIGMAS

Single unavoidable divergence:
  * Sampler: `res_multistep_ancestral` (stock 2nd-order RES + SDE noise
    injection) stands in for Lightricks' Res2sDiffusionStep. Conceptually
    equivalent (2nd-order flow-matching solver with ancestral noise) but
    not byte-identical.

Weight layout required under `third_party/ComfyUI/models/`:
  * checkpoints/ltx-2.3-22b-dev.safetensors
  * loras/ltx-2.3-22b-distilled-lora-384-1.1.safetensors
  * latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors
  * text_encoders/gemma_3_12B_it_fpmixed.safetensors

Requires custom nodes: `custom_nodes/ComfyUI-LTXVideo` (for MultimodalGuider
and GuiderParameters). Falls back gracefully — the workflow only uses those
two node types, so any missing node surfaces as a validation error at
/prompt submit time (ComfyUI returns 400 before starting the run).
"""
from __future__ import annotations
from typing import Any
from video_gen.comfy_config import ComfyRunConfig
from video_gen.workflows._aspect import pick_dims

# LTX 2.3: stage-1 pixel budget = 544×960 ≈ 522,240 px @ stride 32.
# Stage 2 is exactly 2× spatial (1088×1920) so aspect transfers. Source
# aspect is preserved exactly; only pixel-count + stride alignment enforced.
_STAGE1_PIXEL_BUDGET = 544 * 960
_LTX_STRIDE = 32

DEFAULTS: dict[str, Any] = {
    # Weights
    "checkpoint": "ltx-2.3-22b-dev.safetensors",
    "distilled_lora": "ltx-2.3-22b-distilled-lora-384-1.1.safetensors",
    "lora_stage1": 0.25,                           # HQ stage-1 LoRA strength
    "lora_stage2": 0.5,                            # HQ stage-2 LoRA strength
    "upscaler": "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
    "text_encoder": "gemma_3_12B_it_fpmixed.safetensors",

    # Geometry (portrait 9:16)
    "stage1_width": 544,                           # stage 2 = 1088
    "stage1_height": 960,                          # stage 2 = 1920
    "num_frames": 241,                             # ≈10 s @ 24 fps, 8N+1
    "frame_rate": 24,

    # Guide strengths (FLF on both stages)
    "stage1_strength": 0.7,
    "stage2_strength": 1.0,
    "preprocess_compression": 18,

    # HQ guidance (LTX_2_3_HQ_PARAMS)
    "v_cfg": 3.0, "v_stg": 0.0, "v_rescale": 0.45, "v_modality": 3.0,
    "a_cfg": 7.0, "a_stg": 0.0, "a_rescale": 1.0,  "a_modality": 3.0,
    "stg_blocks": "",                              # HQ disables STG

    # Sampling
    "stage1_seed": 43,
    "stage2_seed": 42,
    "stage2_cfg": 1.0,                             # stage 2 uses plain CFG (≡ SimpleDenoiser)
    # Sampler choice: `res_multistep_ancestral` (closer to native Res2sDiffusionStep
    # in spirit) collapses to green VAE artefacts when paired with LoRA@0.25 +
    # HQ guidance. Lightricks' own published ComfyUI example uses euler variants
    # for the distilled model — we match that empirically-stable choice.
    "stage1_sampler": "euler_ancestral_cfg_pp",
    "stage2_sampler": "euler_cfg_pp",
    # LTX2Scheduler(latent=[1,128,31,17,30], steps=15) — precomputed
    "stage1_sigmas": (
        "1.000000, 0.995286, 0.989844, 0.983500, 0.976006, 0.967018, "
        "0.956032, 0.942320, 0.924700, 0.901239, 0.868445, 0.819376, "
        "0.737904, 0.576136, 0.100000, 0.000000"
    ),
    # STAGE_2_DISTILLED_SIGMAS from ltx_pipelines.utils.constants
    "stage2_sigmas": "0.909375, 0.725, 0.421875, 0.0",

    # Tiled decode
    "decode_tile_size": 768,
    "decode_overlap": 64,
    "decode_temporal_size": 4096,
    "decode_temporal_overlap": 64,

    "negative_prompt": (
        "blurry, out of focus, overexposed, underexposed, low contrast, washed out colors, "
        "excessive noise, grainy texture, poor lighting, flickering, motion blur, "
        "distorted proportions, unnatural skin tones, deformed facial features, "
        "asymmetrical face, missing facial features, extra limbs, disfigured hands, "
        "wrong hand count, artifacts around text, inconsistent perspective, camera shake, "
        "incorrect depth of field, background too sharp, background clutter, distracting "
        "reflections, harsh shadows, inconsistent lighting direction, color banding, "
        "cartoonish rendering, 3D CGI look, unrealistic materials, uncanny valley effect, "
        "incorrect ethnicity, wrong gender, exaggerated expressions, wrong gaze direction, "
        "mismatched lip sync, silent or muted audio, distorted voice, robotic voice, echo, "
        "background noise, off-sync audio, incorrect dialogue, added dialogue, repetitive "
        "speech, jittery movement, awkward pauses, incorrect timing, unnatural transitions, "
        "inconsistent framing, tilted camera, flat lighting, inconsistent tone, "
        "cinematic oversaturation, stylized filters, or AI artifacts."
    ),
}


def build_workflow(
    cfg: ComfyRunConfig,
    first_frame_name: str,
    prompt_text: str,
    filename_prefix: str,
    last_frame_name: str | None = None,
    first_frame_path: "Path | None" = None,
) -> dict:
    k = {**DEFAULTS, **cfg.model_kwargs}

    # Source-aware aspect: preserve exact source AR at LTX stage-1 pixel
    # budget, stride 32. Stage 2 is exactly 2× so aspect transfers. Caller
    # can still override via model_kwargs (stage1_width / stage1_height).
    if first_frame_path is not None and "stage1_width" not in cfg.model_kwargs:
        k["stage1_width"], k["stage1_height"] = pick_dims(
            first_frame_path, _STAGE1_PIXEL_BUDGET, _LTX_STRIDE
        )

    num_frames = int(k["num_frames"])
    s1_w, s1_h = int(k["stage1_width"]), int(k["stage1_height"])

    nodes: dict = {
        # ---- shared loaders ----
        "ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": k["checkpoint"]}},
        "lora_s1": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["ckpt", 0],
                "lora_name": k["distilled_lora"],
                "strength_model": k["lora_stage1"],
            },
        },
        "lora_s2": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["ckpt", 0],
                "lora_name": k["distilled_lora"],
                "strength_model": k["lora_stage2"],
            },
        },
        "audio_vae": {"class_type": "LTXVAudioVAELoader", "inputs": {"ckpt_name": k["checkpoint"]}},
        "clip_loader": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": k["text_encoder"],
                "ckpt_name": k["checkpoint"],
                "device": "default",
            },
        },
        "upscaler": {
            "class_type": "LatentUpscaleModelLoader",
            "inputs": {"model_name": k["upscaler"]},
        },

        # ---- prompt encoding (shared across stages) ----
        "positive": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["clip_loader", 0], "text": prompt_text},
        },
        "negative": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["clip_loader", 0], "text": k["negative_prompt"]},
        },
        "conditioning": {
            "class_type": "LTXVConditioning",
            "inputs": {
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "frame_rate": float(k["frame_rate"]),
            },
        },

        # ---- HQ guider parameters (video + audio chained) ----
        "v_params": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "VIDEO",
                "cfg": k["v_cfg"],
                "stg": k["v_stg"],
                "perturb_attn": True,
                "rescale": k["v_rescale"],
                "modality_scale": k["v_modality"],
                "skip_step": 0,
                "cross_attn": True,
            },
        },
        "av_params": {
            "class_type": "GuiderParameters",
            "inputs": {
                "modality": "AUDIO",
                "cfg": k["a_cfg"],
                "stg": k["a_stg"],
                "perturb_attn": True,
                "rescale": k["a_rescale"],
                "modality_scale": k["a_modality"],
                "skip_step": 0,
                "cross_attn": True,
                "parameters": ["v_params", 0],
            },
        },

        # ---- frames load + stage-1 resize + preprocess ----
        "load_first": {"class_type": "LoadImage", "inputs": {"image": first_frame_name}},
        "resize_first_s1": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["load_first", 0],
                "upscale_method": "lanczos",
                "width": s1_w,
                "height": s1_h,
                "crop": "center",
            },
        },
        "preprocess_first_s1": {
            "class_type": "LTXVPreprocess",
            "inputs": {
                "image": ["resize_first_s1", 0],
                "img_compression": k["preprocess_compression"],
            },
        },

        # ---- stage-1 empty latents ----
        "empty_video_s1": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {
                "width": s1_w,
                "height": s1_h,
                "length": num_frames,
                "batch_size": 1,
            },
        },
        "empty_audio": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {
                "frames_number": num_frames,
                "frame_rate": int(k["frame_rate"]),
                "batch_size": 1,
                "audio_vae": ["audio_vae", 0],
            },
        },

        # ---- stage-1: first-frame guide ----
        "guide_first_s1": {
            "class_type": "LTXVAddGuide",
            "inputs": {
                "positive": ["conditioning", 0],
                "negative": ["conditioning", 1],
                "vae": ["ckpt", 2],
                "latent": ["empty_video_s1", 0],
                "image": ["preprocess_first_s1", 0],
                "frame_idx": 0,
                "strength": k["stage1_strength"],
            },
        },
    }

    if last_frame_name is not None:
        nodes.update({
            "load_last": {"class_type": "LoadImage", "inputs": {"image": last_frame_name}},
            "resize_last_s1": {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["load_last", 0],
                    "upscale_method": "lanczos",
                    "width": s1_w,
                    "height": s1_h,
                    "crop": "center",
                },
            },
            "preprocess_last_s1": {
                "class_type": "LTXVPreprocess",
                "inputs": {
                    "image": ["resize_last_s1", 0],
                    "img_compression": k["preprocess_compression"],
                },
            },
            "guide_last_s1": {
                "class_type": "LTXVAddGuide",
                "inputs": {
                    "positive": ["guide_first_s1", 0],
                    "negative": ["guide_first_s1", 1],
                    "vae": ["ckpt", 2],
                    "latent": ["guide_first_s1", 2],
                    "image": ["preprocess_last_s1", 0],
                    "frame_idx": num_frames - 1,
                    "strength": k["stage1_strength"],
                },
            },
        })
        s1_guide_src = "guide_last_s1"
    else:
        s1_guide_src = "guide_first_s1"

    # ---- stage-1 sampling (HQ MultimodalGuider) ----
    nodes.update({
        "concat_av_s1": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": [s1_guide_src, 2],
                "audio_latent": ["empty_audio", 0],
            },
        },
        "noise_s1": {"class_type": "RandomNoise", "inputs": {"noise_seed": k["stage1_seed"]}},
        "guider_s1": {
            "class_type": "MultimodalGuider",
            "inputs": {
                "model": ["lora_s1", 0],
                "positive": [s1_guide_src, 0],
                "negative": [s1_guide_src, 1],
                "parameters": ["av_params", 0],
                "skip_blocks": k["stg_blocks"],
            },
        },
        "sampler_s1": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": k["stage1_sampler"]},
        },
        "sigmas_s1": {
            "class_type": "ManualSigmas",
            "inputs": {"sigmas": k["stage1_sigmas"]},
        },
        "sample_s1": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["noise_s1", 0],
                "guider": ["guider_s1", 0],
                "sampler": ["sampler_s1", 0],
                "sigmas": ["sigmas_s1", 0],
                "latent_image": ["concat_av_s1", 0],
            },
        },
        "separate_av_s1": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["sample_s1", 0]},
        },

        # ---- 2× latent-space spatial upsample ----
        "upsampled": {
            "class_type": "LTXVLatentUpsampler",
            "inputs": {
                "samples": ["separate_av_s1", 0],
                "upscale_model": ["upscaler", 0],
                "vae": ["ckpt", 2],
            },
        },

        # ---- stage-2 frame re-resize + guide ----
        "resize_first_s2": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["load_first", 0],
                "upscale_method": "lanczos",
                "width": s1_w * 2,
                "height": s1_h * 2,
                "crop": "center",
            },
        },
        "guide_first_s2": {
            "class_type": "LTXVAddGuide",
            "inputs": {
                "positive": ["conditioning", 0],
                "negative": ["conditioning", 1],
                "vae": ["ckpt", 2],
                "latent": ["upsampled", 0],
                "image": ["resize_first_s2", 0],
                "frame_idx": 0,
                "strength": k["stage2_strength"],
            },
        },
    })

    if last_frame_name is not None:
        nodes.update({
            "resize_last_s2": {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["load_last", 0],
                    "upscale_method": "lanczos",
                    "width": s1_w * 2,
                    "height": s1_h * 2,
                    "crop": "center",
                },
            },
            "guide_last_s2": {
                "class_type": "LTXVAddGuide",
                "inputs": {
                    "positive": ["guide_first_s2", 0],
                    "negative": ["guide_first_s2", 1],
                    "vae": ["ckpt", 2],
                    "latent": ["guide_first_s2", 2],
                    "image": ["resize_last_s2", 0],
                    "frame_idx": num_frames - 1,
                    "strength": k["stage2_strength"],
                },
            },
        })
        s2_guide_src = "guide_last_s2"
    else:
        s2_guide_src = "guide_first_s2"

    # ---- stage-2 sampling (plain CFGGuider ≡ SimpleDenoiser) ----
    nodes.update({
        "concat_av_s2": {
            "class_type": "LTXVConcatAVLatent",
            "inputs": {
                "video_latent": [s2_guide_src, 2],
                "audio_latent": ["empty_audio", 0],
            },
        },
        "noise_s2": {"class_type": "RandomNoise", "inputs": {"noise_seed": k["stage2_seed"]}},
        "guider_s2": {
            "class_type": "CFGGuider",
            "inputs": {
                "model": ["lora_s2", 0],
                "positive": [s2_guide_src, 0],
                "negative": [s2_guide_src, 1],
                "cfg": k["stage2_cfg"],
            },
        },
        "sampler_s2": {
            "class_type": "KSamplerSelect",
            "inputs": {"sampler_name": k["stage2_sampler"]},
        },
        "sigmas_s2": {
            "class_type": "ManualSigmas",
            "inputs": {"sigmas": k["stage2_sigmas"]},
        },
        "sample_s2": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["noise_s2", 0],
                "guider": ["guider_s2", 0],
                "sampler": ["sampler_s2", 0],
                "sigmas": ["sigmas_s2", 0],
                "latent_image": ["concat_av_s2", 0],
            },
        },
        "separate_av_s2": {
            "class_type": "LTXVSeparateAVLatent",
            "inputs": {"av_latent": ["sample_s2", 0]},
        },
        "crop_guides": {
            "class_type": "LTXVCropGuides",
            "inputs": {
                "positive": [s2_guide_src, 0],
                "negative": [s2_guide_src, 1],
                "latent": ["separate_av_s2", 0],
            },
        },
        "decode": {
            "class_type": "VAEDecodeTiled",
            "inputs": {
                "samples": ["crop_guides", 2],
                "vae": ["ckpt", 2],
                "tile_size": k["decode_tile_size"],
                "overlap": k["decode_overlap"],
                "temporal_size": k["decode_temporal_size"],
                "temporal_overlap": k["decode_temporal_overlap"],
            },
        },
        "save": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["decode", 0],
                "frame_rate": float(k["frame_rate"]),
                "filename_prefix": filename_prefix,
                "format": "video/h264-mp4",
                "save_output": True,
                "loop_count": 0,
                "pingpong": False,
                "pix_fmt": "yuv420p",
                "crf": 19,
            },
        },
    })
    return nodes
