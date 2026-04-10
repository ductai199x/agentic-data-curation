"""Process downloaded video chunks into validated 60s clips.

Reads 4-min chunks from the download directory, runs scene detection
and JoyCaption filtering, cuts clean 60s clips, content-addresses and
saves to validated directory.

Usage:
    # Process all categories on GPU 0
    CUDA_VISIBLE_DEVICES=0 uv run python -m video.process --gpu 0

    # Process specific category
    CUDA_VISIBLE_DEVICES=0 uv run python -m video.process --category C08_walking_biking_tour

    # Dry run — show what would be processed
    uv run python -m video.process --dry-run
"""

import argparse
import csv
import hashlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from .content_filter import (
    JoyCaptionModel,
    extract_frames_from_window,
    check_caption,
    BATCH_SIZE,
)
from .scene_detect import detect_cuts_from_frames
from .cutter import cut_clip, content_hash_file, MAX_CLIP_DURATION


INPUT_BASE = Path("data/videos/real/youtube")
OUTPUT_BASE = Path("data/videos/real/youtube")  # validated/ subdir per category

CLIP_DURATION = 60  # seconds
MIN_CLEAN_SEGMENT = 60  # minimum clean segment to extract a clip

PROCESS_MANIFEST_FIELDS = [
    "source_file", "category", "channel_id", "video_id",
    "clip_filename", "clip_start", "clip_end", "clip_duration",
    "content_hash", "width", "height", "fps", "codec",
    "process_timestamp", "status", "reject_reason",
]


def find_clean_segments(
    frames: list,
    threshold: float = 0.25,
    min_length: int = MIN_CLEAN_SEGMENT,
) -> list[tuple[int, int]]:
    """Find continuous segments without scene cuts.

    Returns list of (start_frame, end_frame) tuples where each segment
    has no cuts and is at least min_length frames long.
    """
    cuts = detect_cuts_from_frames(frames, threshold=threshold)
    cut_set = set(cuts)

    segments = []
    seg_start = 0

    for i in range(len(frames)):
        if i in cut_set:
            if i - seg_start >= min_length:
                segments.append((seg_start, i))
            seg_start = i

    # Last segment
    if len(frames) - seg_start >= min_length:
        segments.append((seg_start, len(frames)))

    return segments


def process_chunk(
    chunk_path: Path,
    category: str,
    model: JoyCaptionModel,
    output_dir: Path,
    processed_set: set[str],
) -> list[dict]:
    """Process a single 4-min chunk into validated 60s clips.

    Steps:
    1. Extract frames at 1fps
    2. Find clean segments (no scene cuts)
    3. For each clean segment, run JoyCaption on its frames
    4. If passes, cut 60s clips from it
    5. Content-address and save

    Returns list of manifest rows.
    """
    results = []
    chunk_name = chunk_path.stem

    if chunk_name in processed_set:
        return []

    # Parse channel_id and video_id from filename
    # Format: {channel_id}_{video_id}_{start}-{end}
    parts = chunk_name.rsplit("_", 1)
    if len(parts) >= 2:
        prefix = parts[0]
        channel_video = prefix.rsplit("_", 1)
        if len(channel_video) == 2:
            channel_id, video_id = channel_video
        else:
            channel_id = prefix
            video_id = ""
    else:
        channel_id = chunk_name
        video_id = ""

    # 1. Extract frames at 1fps from the whole chunk
    # Get duration first
    dur_cmd = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(chunk_path)],
        capture_output=True, text=True, timeout=10,
    )
    try:
        duration = float(dur_cmd.stdout.strip())
    except (ValueError, AttributeError):
        results.append(_make_row(chunk_name, category, channel_id, video_id,
                                 status="error", reason="couldn't read duration"))
        return results

    frames = extract_frames_from_window(str(chunk_path), start=0, duration=duration, interval=1)
    if not frames:
        results.append(_make_row(chunk_name, category, channel_id, video_id,
                                 status="error", reason="no frames extracted"))
        return results

    # 2. Find clean segments
    segments = find_clean_segments(frames)
    if not segments:
        results.append(_make_row(chunk_name, category, channel_id, video_id,
                                 status="rejected", reason="no clean segments (all cuts)"))
        return results

    # 3. For each clean segment, try to extract 60s clips
    validated_dir = output_dir / "validated"
    validated_dir.mkdir(parents=True, exist_ok=True)

    for seg_start, seg_end in segments:
        seg_len = seg_end - seg_start

        # How many 60s clips can we extract from this segment?
        n_clips = seg_len // CLIP_DURATION
        if n_clips == 0:
            continue

        # For each potential clip, run JoyCaption check
        for clip_idx in range(min(n_clips, 4)):  # Max 4 clips per segment
            clip_start_frame = seg_start + clip_idx * CLIP_DURATION
            clip_end_frame = clip_start_frame + CLIP_DURATION

            if clip_end_frame > seg_end:
                break

            clip_frames = frames[clip_start_frame:clip_end_frame]

            # JoyCaption batch check
            captions = model.caption_batch(clip_frames)
            rejected = False
            reject_reason = ""

            for cap in captions:
                result = check_caption(cap)
                if result["reject"]:
                    rejected = True
                    reject_reason = result["reason"]
                    break

            if rejected:
                results.append(_make_row(
                    chunk_name, category, channel_id, video_id,
                    status="rejected", reason=f"content: {reject_reason}",
                    clip_start=clip_start_frame, clip_end=clip_end_frame,
                ))
                continue

            # 4. Cut the clip from the chunk file
            clip_start_sec = clip_start_frame  # 1fps so frame index = seconds
            clip_end_sec = clip_end_frame
            tmp_clip = output_dir / f"_tmp_clip_{clip_idx}.webm"

            try:
                cut_clip(chunk_path, tmp_clip, clip_start_sec, clip_end_sec)
            except Exception as e:
                results.append(_make_row(
                    chunk_name, category, channel_id, video_id,
                    status="error", reason=f"cut failed: {str(e)[:100]}",
                    clip_start=clip_start_sec, clip_end=clip_end_sec,
                ))
                if tmp_clip.exists():
                    tmp_clip.unlink()
                continue

            if not tmp_clip.exists():
                continue

            # 5. Content-address
            clip_hash = content_hash_file(tmp_clip)
            ext = tmp_clip.suffix
            final_name = f"{clip_hash[:16]}{ext}"
            final_path = validated_dir / final_name

            if final_path.exists():
                tmp_clip.unlink()
                continue

            shutil.move(str(tmp_clip), str(final_path))

            # Get clip metadata
            meta_cmd = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries",
                 "stream=width,height,r_frame_rate,codec_name",
                 "-of", "default=noprint_wrappers=1", str(final_path)],
                capture_output=True, text=True, timeout=10,
            )
            width = height = fps = 0
            codec = ""
            for line in meta_cmd.stdout.splitlines():
                if line.startswith("width="): width = int(line.split("=")[1])
                elif line.startswith("height="): height = int(line.split("=")[1])
                elif line.startswith("codec_name="): codec = line.split("=")[1]
                elif line.startswith("r_frame_rate="):
                    try:
                        n, d = line.split("=")[1].split("/")
                        fps = round(float(n) / float(d), 1)
                    except: pass

            results.append({
                "source_file": chunk_name,
                "category": category,
                "channel_id": channel_id,
                "video_id": video_id,
                "clip_filename": final_name,
                "clip_start": clip_start_sec,
                "clip_end": clip_end_sec,
                "clip_duration": clip_end_sec - clip_start_sec,
                "content_hash": clip_hash,
                "width": width,
                "height": height,
                "fps": fps,
                "codec": codec,
                "process_timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "validated",
                "reject_reason": "",
            })

    return results


def _make_row(chunk_name, category, channel_id, video_id,
              status="", reason="", clip_start="", clip_end=""):
    return {
        "source_file": chunk_name, "category": category,
        "channel_id": channel_id, "video_id": video_id,
        "clip_filename": "", "clip_start": clip_start, "clip_end": clip_end,
        "clip_duration": "", "content_hash": "", "width": "", "height": "",
        "fps": "", "codec": "",
        "process_timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status, "reject_reason": reason,
    }


def process_category(
    category: str,
    model: JoyCaptionModel,
    input_base: Path = INPUT_BASE,
    output_base: Path = OUTPUT_BASE,
):
    """Process all chunks in a category."""
    cat_dir = input_base / category
    if not cat_dir.exists():
        return

    # Find all chunk files
    chunks = sorted([
        f for f in cat_dir.iterdir()
        if f.suffix in (".webm", ".mkv", ".mp4") and not f.name.startswith("_tmp")
    ])

    if not chunks:
        return

    # Load already-processed chunks
    manifest_path = cat_dir / "process_manifest.csv"
    processed = set()
    if manifest_path.exists():
        with open(manifest_path) as f:
            for row in csv.DictReader(f):
                processed.add(row.get("source_file", ""))

    remaining = [c for c in chunks if c.stem not in processed]
    if not remaining:
        print(f"{category}: all {len(chunks)} chunks already processed")
        return

    print(f"{category}: {len(remaining)} chunks to process ({len(processed)} already done)")

    validated = 0
    rejected = 0
    errors = 0

    pbar = tqdm(remaining, desc=category, unit="chunk")
    for chunk_path in pbar:
        results = process_chunk(chunk_path, category, model, cat_dir, processed)

        # Append to manifest
        if results:
            write_header = not manifest_path.exists()
            with open(manifest_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROCESS_MANIFEST_FIELDS)
                if write_header:
                    writer.writeheader()
                for row in results:
                    writer.writerow(row)

        for r in results:
            if r["status"] == "validated":
                validated += 1
            elif r["status"] == "rejected":
                rejected += 1
            else:
                errors += 1

        processed.add(chunk_path.stem)
        pbar.set_postfix(v=validated, r=rejected, e=errors)

    pbar.close()
    print(f"  {category}: {validated} validated, {rejected} rejected, {errors} errors")


def main():
    parser = argparse.ArgumentParser(description="Process video chunks into validated clips")
    parser.add_argument("--category", help="Process specific category")
    parser.add_argument("--gpu", type=int, default=0, help="GPU index (set CUDA_VISIBLE_DEVICES externally)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        for d in sorted(INPUT_BASE.iterdir()):
            if d.is_dir() and d.name.startswith("C"):
                chunks = [f for f in d.iterdir() if f.suffix in (".webm", ".mkv", ".mp4")]
                manifest = d / "process_manifest.csv"
                done = 0
                if manifest.exists():
                    with open(manifest) as f:
                        done = sum(1 for _ in csv.DictReader(f))
                print(f"{d.name}: {len(chunks)} chunks, {done} processed")
        return

    categories = [args.category] if args.category else sorted([
        d.name for d in INPUT_BASE.iterdir()
        if d.is_dir() and d.name.startswith("C")
    ])

    model = JoyCaptionModel()

    for cat in categories:
        process_category(cat, model)


if __name__ == "__main__":
    main()
