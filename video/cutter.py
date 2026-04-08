"""Video clip cutting with ffmpeg.

Two-phase approach:
1. Generate dense candidate windows across the video
2. Pipeline iterates candidates, filters, cuts only passing clips

Rules:
- Clip quota scales with video duration (1-4 clips)
- Candidate windows are densely spaced (every 2 minutes)
- Skip first/last 2 minutes (intros/outros)
- Each clip is ≤60s
- Content-addressed filenames (SHA256[:16] + ext)
"""

import hashlib
import subprocess
from pathlib import Path

from .metadata import VideoMeta, probe


# Margins to skip at start/end of source video
SKIP_START_SECS = 120  # 2 minutes
SKIP_END_SECS = 120    # 2 minutes
MAX_CLIP_DURATION = 60  # seconds
CANDIDATE_SPACING = 120  # Generate a candidate window every 2 minutes


def clip_quota(duration: float) -> int:
    """How many clips to keep from a video based on its duration.

    Args:
        duration: Video duration in seconds.

    Returns:
        Target number of clips to keep.
    """
    if duration <= 120:     # ≤2 min
        return 1
    if duration <= 600:     # ≤10 min
        return 2
    if duration <= 1800:    # ≤30 min
        return 3
    return 4                # 30min+


def compute_candidate_windows(
    duration: float,
    skip_start: float = SKIP_START_SECS,
    skip_end: float = SKIP_END_SECS,
    clip_duration: float = MAX_CLIP_DURATION,
    spacing: float = CANDIDATE_SPACING,
) -> list[tuple[float, float]]:
    """Generate dense candidate windows across a video.

    Returns many more candidates than the clip quota — the pipeline
    iterates through them and keeps the first N that pass filtering.

    Args:
        duration: Total video duration in seconds.
        skip_start: Seconds to skip at the beginning.
        skip_end: Seconds to skip at the end.
        clip_duration: Length of each candidate clip.
        spacing: Seconds between candidate start times.

    Returns:
        List of (start_time, end_time) tuples in seconds.
    """
    # For short videos (< skip margins), use reduced margins
    if duration <= skip_start + skip_end:
        if duration <= clip_duration:
            if duration >= 5:
                return [(0.0, duration)]
            return []
        # Medium video — skip 10% at start/end
        margin = duration * 0.1
        usable_start = margin
        usable_end = duration - margin
    else:
        usable_start = skip_start
        usable_end = duration - skip_end

    usable_duration = usable_end - usable_start
    if usable_duration < 5:
        return []

    # Generate candidate windows at regular intervals
    windows = []
    t = usable_start
    while t + min(clip_duration, 5) <= usable_end:
        end = min(t + clip_duration, usable_end)
        if end - t >= 5:
            windows.append((round(t, 2), round(end, 2)))
        t += spacing

    return windows


def cut_clip(
    source_path: str | Path,
    output_path: str | Path,
    start: float,
    end: float,
) -> Path:
    """Extract a clip from a video using ffmpeg.

    Uses stream copy (no re-encoding) for speed. Falls back to re-encoding
    if stream copy produces bad output (rare, happens with some codecs).

    Args:
        source_path: Path to source video.
        output_path: Path for output clip.
        start: Start time in seconds.
        end: End time in seconds.

    Returns:
        Path to the output clip.
    """
    source_path = Path(source_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = end - start

    # Try stream copy first (fast, no quality loss)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(source_path),
        "-t", str(duration),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        # Fall back to re-encoding
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(source_path),
            "-t", str(duration),
            "-c:v", "libx264", "-crf", "18",
            "-c:a", "aac",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg cut failed: {result.stderr[:300]}")

    return output_path


def content_hash_file(path: str | Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()
