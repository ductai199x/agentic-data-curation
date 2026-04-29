"""Source-aware aspect-ratio / size picker.

Mandatory helper for EVERY video-gen workflow. Never hardcode (width, height)
or aspect_ratio — hardcoding stretched ~1,260 Wan 2.2 + LTX clips before it
was caught (see memory/feedback_aspect_ratio_must_be_source_aware.md).

Three pick strategies — use whichever matches the target model:

  (a) `pick_dims(first_frame_path, pixel_budget, stride)`
      For OSS models that accept arbitrary (w, h) at the sampler node.
      Preserves source aspect EXACTLY, scales to model's trained pixel budget,
      snaps to latent stride. Use for Wan 2.1/2.2, Hunyuan, LTX, CogVideoX
      (the last one automatically via CogVideoImageEncode's input-derived shape).

  (b) `pick_by_ratio(first_frame_path, ['16:9', '9:16', ...])`
      For paid APIs that accept an `aspect_ratio` string enum. Snaps to the
      closest supported aspect. Use for Runway Gen-4, Veo 3, Kling 2, Luma Ray 2.

  (c) `pick_by_size(first_frame_path, ['720x1280', '1280x720', ...])`
      For paid APIs that accept a `size`/`resolution` enum in 'WxH' format.
      Use for Sora 2.

  (d) API infers server-side from first_frame
      Some APIs (Kling 2.6, Hailuo 02) detect aspect from the conditioning
      image directly — pass NO aspect parameter and document the behavior at
      the top of the workflow. Verified empirically per pilot.

Examples:
    ratio = pick_by_ratio(first_frame_path, ['16:9', '9:16', '1:1'])
    size  = pick_by_size (first_frame_path, ['720x1280', '1280x720'])
    w, h  = pick_dims    (first_frame_path, pixel_budget=720*1280, stride=16)
"""
from __future__ import annotations

from pathlib import Path


def _read_size(frame_path: str | Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(str(frame_path)) as im:
        return im.size  # (width, height)


def pick_by_ratio(frame_path: str | Path, options: list[str], sep: str = ":") -> str:
    """Pick closest-aspect option from a list of 'WsepH' strings.

    `sep` defaults to ':' (Veo / Runway / Kling). Pass 'x' for Sora-style sizes.
    """
    w, h = _read_size(frame_path)
    src_ar = w / max(h, 1)
    def parse(o: str) -> float:
        a, b = o.split(sep)
        return float(a) / max(float(b), 1)
    return min(options, key=lambda o: abs(parse(o) - src_ar))


def pick_by_size(frame_path: str | Path, options: list[str]) -> str:
    """Convenience wrapper for 'WxH' size enums."""
    return pick_by_ratio(frame_path, options, sep="x")


def pick_dims(
    frame_path: str | Path,
    pixel_budget: int,
    stride: int = 16,
    min_side: int = 256,
) -> tuple[int, int]:
    """Preserve the source frame's exact aspect ratio, scaled to match a
    model's trained pixel budget (e.g. 720×1280 = 921,600 for Wan 720p),
    with dims snapped to the model's latent stride (16 for Wan/Hunyuan,
    32 for LTX, 8 for some others).

    Open-source video models (Wan 2.1/2.2, Hunyuan, LTX, CogVideoX) accept
    arbitrary (w, h) at the sampler node — they're NOT bucket-locked — but
    expect stride-aligned sizes and degrade quality far from their trained
    pixel count. So: hold pixel count constant, change aspect to match.

    Returns (width, height).
    """
    src_w, src_h = _read_size(frame_path)
    aspect = src_w / max(src_h, 1)
    # Scale up or down from the source so w*h ≈ pixel_budget at source aspect
    # w = sqrt(budget * aspect);  h = sqrt(budget / aspect)
    import math
    w = max(min_side, int(round(math.sqrt(pixel_budget * aspect))))
    h = max(min_side, int(round(math.sqrt(pixel_budget / aspect))))
    # Snap to stride using ROUND (not floor) so a 16:9 source at LTX's
    # stride-32 lands at 1088×1920 (0.8% off) instead of 1024×1920 (5% off).
    # Floor is safer for clipping but amplifies aspect drift at large strides.
    w = max(stride, int(round(w / stride)) * stride)
    h = max(stride, int(round(h / stride)) * stride)
    return w, h
