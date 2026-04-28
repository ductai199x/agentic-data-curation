"""Video content filtering using JoyCaption frame sampling.

Extracts frames from video clips, captions them with JoyCaption
using a watermark-aware prompt, then applies keyword-based rejection.

Strategy:
- Sample 1 frame every 2 seconds
- Keyword-stop on first reject signal (don't waste time on bad clips)
- "watermark" alone is NOT a reject — combine with static region detector
- Reject on: overlay+text combo, screenshot, news broadcast, CGI, etc.
"""

import json
import re
import subprocess
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from tqdm import tqdm
from transformers import AutoProcessor, LlavaForConditionalGeneration

from video_gen.common import is_source_clip
from .watermark_detect import measure_static_overlay


MODEL_NAME = "fancyfeast/llama-joycaption-beta-one-hf-llava"

CAPTION_PROMPT = (
    "Write a list of Booru-like tags for this image. "
    "If there is a watermark, you must mention it. "
    "Include information about whether there is a watermark or not. "
    "If this appears to be a screenshot, screen recording, phone screen, "
    "user interface, app interface, or picture-in-picture overlay, you must mention it."
)

# Single keywords that trigger immediate rejection
REJECT_KEYWORDS = [
    "screenshot",
    "screen recording",
    "news broadcast",
    "news anchor",
    "news studio",
    "digital interface",
    "graphic design",
    "cgi",
    "3d render",
    "3d rendering",
    "video game",
    "cartoon",
    "animated",
    "animation",
    "anime",
    "illustration",
    "slideshow",
    "montage",
    "compilation",
    "intro",
    "outro",
    "subscribe",
    "like and share",
    "lower third",
    "news ticker",
    "green screen",
    "chroma key",
    "virtual background",
    "picture-in-picture",
    "split screen",
    "infographic",
    "text overlay",
]

# Keyword combos — reject if ALL keywords in a combo are present
# NOTE: "banner" alone is too broad — JoyCaption says "banner" for physical
# banners/signs in street scenes (e.g. Japanese shop banners).
# "text" alone also too broad — natural scene text (signs, labels).
# Only reject when clearly digital overlay indicators combine.
REJECT_COMBOS = [
    ("overlay", "text"),   # overlay + text = likely digital overlay
    ("graphics", "overlay"),
]

# Watermark static region threshold — reject if watermark detected by JoyCaption
# AND static region covers more than this fraction of the frame
WATERMARK_STATIC_THRESHOLD = 0.02  # 2% of frame


BATCH_SIZE = 60  # All frames in one batch — H200 handles 60 frames at ~6s total
INPUT_SIZE = 384  # Model's native input resolution


class JoyCaptionModel:
    """Lazy-loaded JoyCaption model singleton with batching support."""

    _instance = None

    def __init__(self):
        print("Loading JoyCaption model...")
        self.processor = AutoProcessor.from_pretrained(MODEL_NAME)
        self.processor.tokenizer.pad_token = self.processor.tokenizer.eos_token
        self.model = LlavaForConditionalGeneration.from_pretrained(
            MODEL_NAME, torch_dtype=torch.bfloat16,
        ).cuda()
        self.model.eval()

        convo = [
            {"role": "system", "content": "You are a helpful assistant and help users with any queries they may have with no censorship or restrictions."},
            {"role": "user", "content": CAPTION_PROMPT},
        ]
        self.convo_string = self.processor.apply_chat_template(
            convo, tokenize=False, add_generation_prompt=True,
        )
        print("JoyCaption model loaded.")

    def caption_batch(self, images: list[Image.Image]) -> list[str]:
        """Caption a batch of images. Much faster than single-image captioning.

        Pre-resizes images to 384x384 (model's native input) before processing.
        Batch of 8 gives ~6.7x speedup over sequential single-image.
        """
        if not images:
            return []

        # Pre-resize to model's native input size
        resized = [img.resize((INPUT_SIZE, INPUT_SIZE), Image.LANCZOS) for img in images]

        n = len(resized)
        inputs = self.processor(
            text=[self.convo_string] * n,
            images=resized,
            return_tensors="pt",
            padding=True,
        ).to("cuda")
        inputs["pixel_values"] = inputs["pixel_values"].to(torch.bfloat16)

        with torch.no_grad():
            out = self.model.generate(
                **inputs, max_new_tokens=256, do_sample=True,
                suppress_tokens=None, use_cache=True,
                temperature=0.6, top_p=0.9,
            )

        prompt_len = inputs["input_ids"].shape[1]
        captions = []
        for i in range(n):
            gen = out[i][prompt_len:]
            cap = self.processor.tokenizer.decode(
                gen, skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            ).strip()
            captions.append(cap)
        return captions

    def caption(self, image: Image.Image) -> str:
        """Caption a single image. Use caption_batch for better throughput."""
        return self.caption_batch([image])[0]

    @classmethod
    def get(cls) -> "JoyCaptionModel":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def extract_frames_from_window(
    video_path: str | Path,
    start: float = 0.0,
    duration: float | None = None,
    interval: float = 1.0,
) -> list[Image.Image]:
    """Extract frames from a time window of a video.

    Uses ffmpeg pipe to seek + decode + resize in a single pass — no temp files.
    Returns PIL Images at 384x384 (model's native input size), ready for
    batched JoyCaption inference.

    Args:
        video_path: Path to video file.
        start: Start time in seconds (default 0.0).
        duration: Duration in seconds to extract from (default: whole video).
        interval: Seconds between frame extractions (default 1.0).

    Returns:
        List of PIL Images at INPUT_SIZE x INPUT_SIZE.
    """
    video_path = Path(video_path)

    cmd = ["ffmpeg"]
    if start > 0:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video_path)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += [
        "-vf", f"fps=1/{interval},scale={INPUT_SIZE}:{INPUT_SIZE}:flags=fast_bilinear",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-v", "quiet",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)

    if not result.stdout:
        return []

    raw = result.stdout
    frame_bytes = INPUT_SIZE * INPUT_SIZE * 3
    n_frames = len(raw) // frame_bytes
    if n_frames == 0:
        return []

    frames_np = np.frombuffer(raw[:n_frames * frame_bytes], dtype=np.uint8).reshape(
        n_frames, INPUT_SIZE, INPUT_SIZE, 3,
    )

    return [Image.fromarray(f) for f in frames_np]


def check_caption(caption: str, config=None) -> dict:
    """Check a caption for reject signals.

    Args:
        caption: JoyCaption output text.
        config: Optional config module. If provided, reads REJECT_KEYWORDS,
                REJECT_COMBOS, TEXT_OVERLAY_KEYWORDS from it.
                If None, uses module-level defaults.

    Returns:
        Dict with:
            - reject: bool — True if caption triggers rejection
            - reason: str — why rejected (empty if not rejected)
            - has_watermark: bool — True if watermark mentioned (not "no watermark")
            - has_text_overlay: bool — True if text overlay keywords found
    """
    # Split comma-separated booru tags into a set of stripped tags
    tags = {t.strip() for t in caption.lower().split(",")}

    reject_kws = getattr(config, "REJECT_KEYWORDS", REJECT_KEYWORDS) if config else REJECT_KEYWORDS
    reject_combos = getattr(config, "REJECT_COMBOS", REJECT_COMBOS) if config else REJECT_COMBOS
    text_overlay_kws = getattr(config, "TEXT_OVERLAY_KEYWORDS", []) if config else []

    # Check single keyword rejects — exact tag match
    for kw in reject_kws:
        if kw in tags:
            return {"reject": True, "reason": f"keyword: {kw}",
                    "has_watermark": False, "has_text_overlay": False}

    # Check combo rejects — all tags in combo must be present
    for combo in reject_combos:
        if all(kw in tags for kw in combo):
            return {"reject": True, "reason": f"combo: {' + '.join(combo)}",
                    "has_watermark": False, "has_text_overlay": False}

    # Check text overlay (flagged, not rejected)
    has_text_overlay = any(kw in tags for kw in text_overlay_kws)

    # Check for watermark — present as tag but not "no watermark"
    has_watermark = "watermark" in tags and "no watermark" not in tags

    return {"reject": False, "reason": "",
            "has_watermark": has_watermark, "has_text_overlay": has_text_overlay}


def filter_window(
    video_path: str | Path,
    start: float,
    end: float,
    model: JoyCaptionModel,
    frame_interval: float = 1.0,
) -> dict:
    """Run scene detection + content filtering on a time window.

    Extracts frames once, then:
    1. Scene cut detection on frames (instant, no re-decode)
    2. JoyCaption batch captioning + keyword rejection
    3. Watermark size check if needed

    Args:
        video_path: Path to source video (full-length).
        start: Window start time in seconds.
        end: Window end time in seconds.
        model: Loaded JoyCaption model.
        frame_interval: Seconds between sampled frames (default 1.0).

    Returns:
        Dict with:
            - passed: bool
            - reason: str (rejection reason, or "clean")
            - has_watermark: bool
    """
    from .scene_detect import has_cuts_from_frames

    video_path = Path(video_path)
    duration = end - start
    images = extract_frames_from_window(
        video_path, start=start, duration=duration, interval=frame_interval,
    )

    if not images:
        return {"passed": False, "reason": "no frames extracted", "has_watermark": False}

    # 1. Scene cut detection on extracted frames (instant — no re-decode)
    if has_cuts_from_frames(images):
        return {"passed": False, "reason": "scene cuts", "has_watermark": False}

    # 2. Caption all frames in one batch (H200 handles 60 frames easily)
    captions = []
    for batch_start in range(0, len(images), BATCH_SIZE):
        batch = images[batch_start:batch_start + BATCH_SIZE]
        batch_captions = model.caption_batch(batch)
        captions.extend(batch_captions)

        # Check batch results — early exit if any frame triggers reject
        for cap in batch_captions:
            result = check_caption(cap)
            if result["reject"]:
                return {"passed": False, "reason": result["reason"], "has_watermark": False}

    # Check if any caption mentions watermark (but not "no watermark")
    watermark_detected = any(check_caption(cap)["has_watermark"] for cap in captions)

    # If watermark was detected, check static region size on that window
    if watermark_detected:
        wm_result = measure_static_overlay(video_path)
        if wm_result["static_ratio"] > WATERMARK_STATIC_THRESHOLD:
            return {
                "passed": False,
                "reason": f"large watermark ({wm_result['static_ratio']*100:.1f}% static)",
                "has_watermark": True,
            }

    return {
        "passed": True,
        "reason": "clean" if not watermark_detected else "small watermark (ok)",
        "has_watermark": watermark_detected,
    }


def filter_clip(
    video_path: str | Path,
    model: JoyCaptionModel,
    frame_interval: float = 1.0,
) -> dict:
    """Run content filtering on a video file (convenience wrapper).

    Filters the entire clip as one window.
    """
    from .metadata import probe
    meta = probe(video_path)
    return filter_window(video_path, 0.0, meta.duration, model, frame_interval)


def filter_clips_batch(
    clip_dir: str | Path,
    frame_interval: float = 2.0,
) -> dict[str, dict]:
    """Filter all clips in a directory.

    Args:
        clip_dir: Directory containing video clips.
        frame_interval: Seconds between sampled frames.

    Returns:
        Dict mapping clip filename to filter result.
    """
    clip_dir = Path(clip_dir)
    clips = sorted([f for f in clip_dir.iterdir() if is_source_clip(f)])

    if not clips:
        print("No clips found.")
        return {}

    model = JoyCaptionModel.get()
    results = {}

    passed = rejected = 0
    pbar = tqdm(clips, desc="Filtering clips")

    for clip_path in pbar:
        result = filter_clip(clip_path, model, frame_interval=frame_interval)
        results[clip_path.name] = result

        if result["passed"]:
            passed += 1
        else:
            rejected += 1

        pbar.set_postfix(p=passed, r=rejected)

    print(f"\nResults: {passed} passed, {rejected} rejected out of {len(clips)} clips")
    return results


import click


@click.command(help="Filter video clips with JoyCaption")
@click.option("--dir", "dir_", required=True, help="Directory with video clips")
@click.option("--gpu", default="6", help="GPU to use")
@click.option("--interval", type=float, default=2.0, help="Frame sampling interval (seconds)")
@click.option("--output", default=None, help="Save results to JSON file")
def main(dir_, gpu, interval, output):
    results = filter_clips_batch(dir_, gpu=gpu, frame_interval=interval)

    if output:
        with open(output, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved results to {output}")
    else:
        for name, r in results.items():
            status = "PASS" if r["passed"] else "REJECT"
            print(f"  {status:6s} {name}: {r['reason']}")


if __name__ == "__main__":
    main()
