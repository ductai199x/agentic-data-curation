"""File-level clip helpers: identification, listing, frame extraction.

`is_source_clip` is the canonical filter that excludes derived/auxiliary
files (.flow.mp4, .tmp.*.mp4) which live alongside real clips and would
otherwise pollute manifests, frame extractions, etc.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}


def is_source_clip(p: Path) -> bool:
    """True iff p is a primary source/generation video, not a derived file.

    Real clips are named `<sha16>.<ext>`. Derived files like
    `<sha16>.flow.mp4` (optical-flow outputs used for training detection
    models) and temp fragments (`<sha16>.flow.mp4.tmp.w10.mp4`) have more
    dots in the filename and must be excluded from everything that
    enumerates source videos.
    """
    return (
        p.is_file()
        and p.suffix.lower() in VIDEO_EXTS
        and not p.name.startswith("_")
        and p.name.count(".") == 1
    )


def list_clips(clips_dir: Path) -> list[Path]:
    """Sorted list of validated video clips under a directory (recursive).

    Uses rglob so it works for both flat layouts (Instagram:
    validated/<stem>.mp4) and nested ones (YouTube: validated/<cat>/<stem>.mp4).
    Filters out derived/auxiliary files via `is_source_clip`.
    """
    return sorted(f for f in Path(clips_dir).rglob("*") if is_source_clip(f))


def probe_duration(video: Path) -> float:
    """Return duration in seconds via ffprobe."""
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, timeout=15,
    )
    try:
        return float(r.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _save_decord_frame(frame_nparray, output: Path) -> bool:
    """Save a decord-returned numpy frame (H, W, 3) RGB to PNG."""
    try:
        from PIL import Image
        Image.fromarray(frame_nparray).save(output)
        return output.exists() and output.stat().st_size > 0
    except Exception:
        return False


def extract_frame(video: Path, timestamp: float, output: Path) -> bool:
    """Extract a single video frame at `timestamp` seconds via decord."""
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import decord
        vr = decord.VideoReader(str(video), ctx=decord.cpu(0))
        if len(vr) == 0:
            return False
        fps = float(vr.get_avg_fps()) or 1.0
        idx = max(0, min(len(vr) - 1, round(timestamp * fps)))
        return _save_decord_frame(vr[idx].asnumpy(), output)
    except Exception:
        return False


def extract_last_frame(video: Path, output: Path) -> bool:
    """Extract the final video frame via decord (random-access last index)."""
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import decord
        vr = decord.VideoReader(str(video), ctx=decord.cpu(0))
        if len(vr) == 0:
            return False
        return _save_decord_frame(vr[-1].asnumpy(), output)
    except Exception:
        return False


def extract_first_last_frames(
    video: Path, frames_dir: Path, overwrite: bool = False,
) -> tuple[Path, Path] | None:
    """Extract first + last frame PNGs for a video. Returns (first, last) or None."""
    stem = video.stem
    first = frames_dir / f"{stem}_first.png"
    last = frames_dir / f"{stem}_last.png"

    if not overwrite and first.exists() and last.exists():
        return first, last

    if not extract_frame(video, 0.0, first):
        return None
    if not extract_last_frame(video, last):
        return None
    return first, last
