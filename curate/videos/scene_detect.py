"""Scene cut detection.

Two modes:
1. From frames already in memory (fast — reuses frames from content filter)
2. From video file via ffmpeg (fallback)

Zero-tolerance: any detected cut means the clip is rejected.
"""

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


def detect_cuts_from_frames(
    frames: list[Image.Image | np.ndarray],
    threshold: float = 0.25,
) -> list[int]:
    """Detect scene cuts from a list of frames already in memory.

    Compares consecutive frames using mean absolute pixel difference.
    At 1fps sampling, a hard cut between frames will show a large difference.

    Args:
        frames: List of PIL Images or numpy arrays (same size).
        threshold: Fraction of max possible difference (0.0–1.0).
            0.35 means >35% of pixels changed significantly = cut.

    Returns:
        List of frame indices where cuts were detected.
    """
    if len(frames) < 2:
        return []

    # Convert to numpy if needed
    arrays = []
    for f in frames:
        if isinstance(f, Image.Image):
            arrays.append(np.array(f, dtype=np.float32))
        else:
            arrays.append(f.astype(np.float32))

    cuts = []
    for i in range(1, len(arrays)):
        # Mean absolute difference normalized to [0, 1]
        diff = np.abs(arrays[i] - arrays[i - 1]).mean() / 255.0
        if diff > threshold:
            cuts.append(i)

    return cuts


def has_cuts_from_frames(
    frames: list[Image.Image | np.ndarray],
    threshold: float = 0.25,
) -> bool:
    """Check if frames contain any scene cuts.

    Returns True if any cuts detected (clip should be rejected).
    """
    return len(detect_cuts_from_frames(frames, threshold)) > 0


def detect_cuts(path: str | Path, threshold: float = 0.25) -> list[float]:
    """Detect scene cuts in a video file using ffmpeg's scene filter.

    Fallback for when frames aren't already in memory.

    Args:
        path: Path to video file.
        threshold: Scene change threshold (0.0–1.0).

    Returns:
        List of timestamps (seconds) where cuts were detected.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    cmd = [
        "ffmpeg", "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr",
        "-f", "null", "-",
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120,
    )

    cuts = []
    for line in result.stderr.splitlines():
        if "Parsed_showinfo" not in line:
            continue
        for part in line.split():
            if part.startswith("pts_time:"):
                try:
                    ts = float(part.split(":")[1])
                    cuts.append(ts)
                except (ValueError, IndexError):
                    continue
    return cuts


def has_cuts(path: str | Path, threshold: float = 0.25) -> bool:
    """Check if a video file contains any scene cuts.

    Returns True if any cuts detected (clip should be rejected).
    """
    return len(detect_cuts(path, threshold)) > 0
