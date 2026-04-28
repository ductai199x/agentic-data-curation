"""Shared helpers for the video generation pipeline.

- Frame extraction (first + last frames from a video)
- Manifest tracking per model (resume + dedup)
- Sharding helpers
"""

import csv
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


VIDEO_EXTS = {".mp4", ".webm", ".mkv", ".mov"}

MANIFEST_FIELDS = [
    "real_clip", "first_frame", "last_frame",
    "prompt_source", "prompt_preview",
    "output_path", "duration_s", "status",
    "model_name", "elapsed_s", "error",
]


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


@dataclass
class ClipJob:
    real_clip: Path
    first_frame: Path
    last_frame: Path
    prompt: str
    duration: float


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


def load_captions(captions_path: Path, key: str = "caption") -> dict[str, str]:
    """Load the SALMONN caption JSON, returning {filename: <key-field>}.

    The JSON value for each clip may be a bare string (legacy) or a dict with
    at least a `caption` field and optionally `short_caption` (added by
    `video_gen.rewrite_captions`). When `key != 'caption'`, clips missing that
    key fall back to the long `caption` field so nothing ever returns empty.
    """
    data = json.load(open(captions_path))
    out = {}
    for fn, v in data.items():
        if isinstance(v, dict):
            picked = v.get(key) or v.get("caption")
            if picked:
                out[fn] = picked
        elif isinstance(v, str):
            out[fn] = v
    return out


def build_jobs(
    clips_dir: Path,
    captions_path: Path,
    frames_dir: Path,
    rank_file: Path | None = None,
    max_clips: int | None = None,
    caption_key: str = "caption",
) -> list[ClipJob]:
    """Build the full list of generation jobs.

    For each validated clip that has a SALMONN caption:
      - extract first/last frames (cached in frames_dir)
      - create a ClipJob
    Clips without captions are skipped.

    If `rank_file` is set, the output is filtered + ordered by the ranks in
    that CSV (columns `rank`, `stem`) and truncated to `max_clips` (if set).
    If only `max_clips` is set, the first K in directory order are returned.
    """
    captions = load_captions(captions_path, key=caption_key)

    # If rank_file is set, only process clips in the ranking (skip the rest)
    allowed_stems: set[str] | None = None
    if rank_file is not None:
        ranking = load_ranking(rank_file)  # {stem: rank}
        allowed_stems = set(ranking.keys())
        if max_clips is not None and max_clips > 0:
            # Only need the top-K stems — skip everything else
            top_k = sorted(ranking.items(), key=lambda kv: kv[1])[:max_clips]
            allowed_stems = {stem for stem, _ in top_k}

    jobs: list[ClipJob] = []
    for clip in list_clips(clips_dir):
        stem = clip.stem
        if allowed_stems is not None and stem not in allowed_stems:
            continue
        cap = captions.get(clip.name)
        if not cap:
            continue
        first = frames_dir / f"{stem}_first.png"
        last = frames_dir / f"{stem}_last.png"

        # Frames must be pre-extracted via `python -m video_gen.extract_frames`.
        # Skip (with warning) any clip missing its first frame. Last frame is
        # optional: FLF workflows check `job.last_frame.exists()`, I2V ignores.
        if not first.exists():
            print(f"[build_jobs] skipping {stem}: missing first frame "
                  f"(run `python -m video_gen.extract_frames` to pre-extract)",
                  flush=True)
            continue

        jobs.append(ClipJob(
            real_clip=clip, first_frame=first, last_frame=last,
            prompt=cap, duration=0.0,
        ))

    if rank_file is not None:
        jobs.sort(key=lambda j: ranking.get(j.real_clip.stem, 999999))

    if max_clips is not None and max_clips > 0:
        jobs = jobs[:max_clips]

    return jobs


def load_ranking(rank_file: Path) -> dict[str, int]:
    """Read a diversity_rank.csv (`rank, stem, ...`) into `{stem: rank}`."""
    ranking: dict[str, int] = {}
    with open(rank_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            stem = row.get("stem")
            try:
                rank = int(row.get("rank", "0"))
            except Exception:
                continue
            if stem and rank:
                ranking[stem] = rank
    return ranking


# ---------------------------------------------------------------------------
# Manifest tracking
# ---------------------------------------------------------------------------

def load_processed(manifest_path: Path) -> set[str]:
    """Load clip names that have already been processed from a manifest."""
    if not manifest_path.exists():
        return set()
    processed = set()
    with open(manifest_path) as f:
        for row in csv.DictReader(f):
            rc = row.get("real_clip", "")
            if rc and row.get("status") in ("generated", "failed_permanent"):
                processed.add(rc)
    return processed


def append_manifest(manifest_path: Path, row: dict):
    write_header = not manifest_path.exists()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)


def shard_jobs(jobs: list, shard_id: int, num_shards: int) -> list:
    """Partition jobs across workers — each gets every Nth job."""
    if num_shards <= 1:
        return jobs
    return [j for i, j in enumerate(jobs) if i % num_shards == shard_id]
