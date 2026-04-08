"""Static overlay / watermark detection.

Detects persistent static regions across video frames.
If pixels don't change across multiple sampled frames, they're likely
a watermark, logo, banner, or other static overlay.

Small watermarks (< threshold % of frame) are tolerated.
Large static overlays trigger rejection.
"""

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def extract_frames(
    video_path: str | Path,
    n_frames: int = 8,
    skip_start: float = 2.0,
    skip_end: float = 2.0,
) -> list[np.ndarray]:
    """Extract evenly spaced frames from a video as numpy arrays.

    Args:
        video_path: Path to video file.
        n_frames: Number of frames to extract.
        skip_start: Seconds to skip at start.
        skip_end: Seconds to skip at end.

    Returns:
        List of numpy arrays (H, W, 3) in RGB.
    """
    video_path = Path(video_path)

    # Get duration
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    duration = float(result.stdout.strip())

    usable_start = skip_start
    usable_end = max(duration - skip_end, skip_start + 1)
    usable_duration = usable_end - usable_start

    if usable_duration < 1:
        usable_start = 0
        usable_end = duration
        usable_duration = duration

    # Compute evenly spaced timestamps
    if n_frames == 1:
        timestamps = [usable_start + usable_duration / 2]
    else:
        step = usable_duration / (n_frames - 1)
        timestamps = [usable_start + i * step for i in range(n_frames)]

    frames = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, ts in enumerate(timestamps):
            out_path = Path(tmpdir) / f"frame_{i:04d}.png"
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(ts),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "1",
                str(out_path),
            ]
            subprocess.run(cmd, capture_output=True, timeout=10)
            if out_path.exists():
                img = Image.open(out_path).convert("RGB")
                frames.append(np.array(img))

    return frames


def detect_static_regions(
    frames: list[np.ndarray],
    tolerance: int = 8,
) -> np.ndarray:
    """Find pixels that remain static across all frames.

    Args:
        frames: List of numpy arrays (H, W, 3), same dimensions.
        tolerance: Max per-channel pixel difference to consider "static".

    Returns:
        Boolean mask (H, W) where True = static pixel.
    """
    if len(frames) < 2:
        return np.zeros(frames[0].shape[:2], dtype=bool)

    reference = frames[0].astype(np.int16)
    static_mask = np.ones(reference.shape[:2], dtype=bool)

    for frame in frames[1:]:
        diff = np.abs(frame.astype(np.int16) - reference)
        # A pixel is "changing" if any channel differs by more than tolerance
        changed = np.any(diff > tolerance, axis=2)
        static_mask &= ~changed

    return static_mask


def measure_static_overlay(
    video_path: str | Path,
    n_frames: int = 8,
    tolerance: int = 8,
    ignore_border: int = 5,
) -> dict:
    """Measure the size and location of static overlays in a video.

    Args:
        video_path: Path to video file.
        n_frames: Number of frames to sample.
        tolerance: Pixel difference tolerance for "static" classification.
        ignore_border: Pixels to ignore at frame edges (encoding artifacts).

    Returns:
        Dict with:
            - static_ratio: fraction of frame that is static (0.0–1.0)
            - static_pixels: total number of static pixels
            - total_pixels: total frame pixels
            - has_large_overlay: True if static_ratio > threshold
            - regions: list of (y, x, h, w) bounding boxes of static clusters
    """
    frames = extract_frames(video_path, n_frames=n_frames)
    if len(frames) < 2:
        return {
            "static_ratio": 0.0,
            "static_pixels": 0,
            "total_pixels": 0,
            "has_large_overlay": False,
            "regions": [],
        }

    mask = detect_static_regions(frames, tolerance=tolerance)

    # Ignore border pixels (compression artifacts at edges)
    if ignore_border > 0:
        mask[:ignore_border, :] = False
        mask[-ignore_border:, :] = False
        mask[:, :ignore_border] = False
        mask[:, -ignore_border:] = False

    total_pixels = mask.shape[0] * mask.shape[1]
    static_pixels = int(np.sum(mask))
    static_ratio = static_pixels / total_pixels if total_pixels > 0 else 0.0

    # Find connected regions using simple bounding box approach
    regions = _find_static_regions(mask)

    return {
        "static_ratio": round(static_ratio, 6),
        "static_pixels": static_pixels,
        "total_pixels": total_pixels,
        "has_large_overlay": static_ratio > 0.02,  # >2% of frame
        "regions": regions,
    }


def _find_static_regions(mask: np.ndarray, min_size: int = 100) -> list[dict]:
    """Find bounding boxes of connected static regions.

    Simple approach: find contiguous horizontal runs, then merge vertically.
    For watermark detection we don't need pixel-perfect segmentation,
    just approximate bounding boxes.
    """
    # Use scipy if available for proper connected components
    try:
        from scipy import ndimage
        labeled, n_features = ndimage.label(mask)
        regions = []
        for i in range(1, n_features + 1):
            ys, xs = np.where(labeled == i)
            if len(ys) < min_size:
                continue
            region = {
                "y": int(ys.min()),
                "x": int(xs.min()),
                "h": int(ys.max() - ys.min() + 1),
                "w": int(xs.max() - xs.min() + 1),
                "pixels": len(ys),
                "area_ratio": round(len(ys) / mask.size, 6),
            }
            regions.append(region)
        return sorted(regions, key=lambda r: r["pixels"], reverse=True)
    except ImportError:
        # Fallback: just report total static area
        static_pixels = int(np.sum(mask))
        if static_pixels < min_size:
            return []
        ys, xs = np.where(mask)
        return [{
            "y": int(ys.min()),
            "x": int(xs.min()),
            "h": int(ys.max() - ys.min() + 1),
            "w": int(xs.max() - xs.min() + 1),
            "pixels": static_pixels,
            "area_ratio": round(static_pixels / mask.size, 6),
        }]


def has_large_watermark(
    video_path: str | Path,
    threshold: float = 0.02,
    n_frames: int = 8,
) -> bool:
    """Check if a video has a large static watermark/overlay.

    Args:
        video_path: Path to video file.
        threshold: Reject if static region covers more than this fraction
            of the frame. Default 0.02 = 2%.
        n_frames: Number of frames to sample.

    Returns:
        True if large watermark detected (clip should be reviewed/rejected).
    """
    result = measure_static_overlay(video_path, n_frames=n_frames)
    return result["static_ratio"] > threshold
