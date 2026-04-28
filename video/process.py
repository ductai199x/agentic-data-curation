"""Process downloaded videos into validated clips.

Config-driven pipeline that works for both YouTube (category-based) and
Instagram (flat staging directory). Reads clip duration, min duration,
scene cut threshold, and content filter keywords from config.

Usage:
    # YouTube: process all categories
    CUDA_VISIBLE_DEVICES=0 uv run python -m video.process --config configs/youtube_real_video.py

    # Instagram: process staging directory
    CUDA_VISIBLE_DEVICES=0 uv run python -m video.process --config configs/instagram_real_video.py

    # Dry run
    uv run python -m video.process --config configs/youtube_real_video.py --dry-run
"""

import click
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from video_gen.common import is_source_clip
from .content_filter import (
    JoyCaptionModel,
    extract_frames_from_window,
    check_caption,
    BATCH_SIZE,
)
from .scene_detect import detect_cuts_from_frames
from .cutter import cut_clip, content_hash_file
from .quality_filter import check_quality


PROCESS_MANIFEST_FIELDS = [
    "source_file", "source_type", "username", "category",
    "channel_id", "video_id",
    "clip_filename", "clip_start", "clip_end", "clip_duration",
    "content_hash", "width", "height", "fps", "codec",
    "has_text_overlay", "has_watermark",
    "process_timestamp", "status", "reject_reason",
]

VIDEO_EXTENSIONS = {".webm", ".mkv", ".mp4", ".avi", ".mov"}


def find_clean_segments(
    frames: list,
    threshold: float = 0.25,
    min_length: int = 60,
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

    if len(frames) - seg_start >= min_length:
        segments.append((seg_start, len(frames)))

    return segments



def process_video(
    video_path: Path,
    config,
    model: JoyCaptionModel,
    validated_dir: Path,
    processed_set: set[str],
    source_type: str = "youtube",
    username: str = "",
    category: str = "",
) -> list[dict]:
    """Process a single video into validated clips.

    Steps:
    1. Check duration (discard if < MIN_DURATION)
    2. Extract frames at 1fps
    3. Find clean segments (no scene cuts)
    4. For each segment, run JoyCaption on frames
    5. If passes, cut clips from it
    6. Content-address and save to validated_dir

    Source videos are never moved — they always live in staging/. The
    manifest is the single source of truth for which clips passed/failed.

    Returns (manifest_rows, captions_dict) where captions_dict maps
    clip_filename -> list of caption strings.
    """
    results = []
    clip_captions: dict[str, list[str]] = {}
    video_name = video_path.stem

    if video_name in processed_set:
        return [], {}

    clip_duration = getattr(config, "CLIP_DURATION", 60)
    min_duration = getattr(config, "MIN_DURATION", 10)
    min_clean = getattr(config, "MIN_CLEAN_SEGMENT", clip_duration)
    max_clips = getattr(config, "MAX_CLIPS_PER_VIDEO", 4)
    scene_threshold = getattr(config, "SCENE_CUT_THRESHOLD", 0.25)

    # Parse metadata from filename
    channel_id = ""
    video_id = ""
    if source_type == "youtube":
        parts = video_name.rsplit("_", 1)
        if len(parts) >= 2:
            prefix = parts[0]
            cv = prefix.rsplit("_", 1)
            if len(cv) == 2:
                channel_id, video_id = cv
    elif source_type == "instagram":
        # Content-addressed filename — no parseable metadata
        pass

    # 1. Check duration
    dur_cmd = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, timeout=10,
    )
    try:
        duration = float(dur_cmd.stdout.strip())
    except (ValueError, AttributeError):
        results.append(_make_row(
            video_name, source_type, username, category, channel_id, video_id,
            status="error", reason="couldn't read duration",
        ))
        return results, clip_captions

    if duration < min_duration:
        results.append(_make_row(
            video_name, source_type, username, category, channel_id, video_id,
            status="rejected", reason=f"too short ({duration:.0f}s < {min_duration}s)",
        ))
        return results, clip_captions

    # 2. Extract frames at 1fps
    frames = extract_frames_from_window(str(video_path), start=0, duration=duration, interval=1)
    if not frames:
        results.append(_make_row(
            video_name, source_type, username, category, channel_id, video_id,
            status="error", reason="no frames extracted",
        ))
        return results, clip_captions

    # 3. Find clean segments
    segments = find_clean_segments(frames, threshold=scene_threshold, min_length=min_clean)
    if not segments:
        results.append(_make_row(
            video_name, source_type, username, category, channel_id, video_id,
            status="rejected", reason="no clean segments (all cuts)",
        ))
        return results, clip_captions

    # 4. For each clean segment, try to extract clips
    validated_dir.mkdir(parents=True, exist_ok=True)

    clips_cut = 0
    for seg_start, seg_end in segments:
        seg_len = seg_end - seg_start
        n_clips = seg_len // clip_duration
        if n_clips == 0:
            continue

        for clip_idx in range(min(n_clips, max_clips - clips_cut)):
            if clips_cut >= max_clips:
                break

            clip_start_frame = seg_start + clip_idx * clip_duration
            clip_end_frame = clip_start_frame + clip_duration
            if clip_end_frame > seg_end:
                break

            clip_frames = frames[clip_start_frame:clip_end_frame]

            # JoyCaption batch check
            captions = model.caption_batch(clip_frames)
            rejected = False
            reject_reason = ""
            has_text_overlay = False
            has_watermark = False

            for cap in captions:
                result = check_caption(cap, config)
                if result["reject"]:
                    rejected = True
                    reject_reason = result["reason"]
                    break
                if result["has_text_overlay"]:
                    has_text_overlay = True
                if result["has_watermark"]:
                    has_watermark = True

            if rejected:
                results.append(_make_row(
                    video_name, source_type, username, category, channel_id, video_id,
                    status="rejected", reason=f"content: {reject_reason}",
                    clip_start=clip_start_frame, clip_end=clip_end_frame,
                ))
                continue

            # 5. Cut the clip
            clip_start_sec = clip_start_frame  # 1fps so frame index = seconds
            clip_end_sec = clip_end_frame
            tmp_clip = validated_dir / f"_tmp_clip_{os.getpid()}_{clips_cut}.mp4"

            try:
                cut_clip(video_path, tmp_clip, clip_start_sec, clip_end_sec)
            except Exception as e:
                results.append(_make_row(
                    video_name, source_type, username, category, channel_id, video_id,
                    status="error", reason=f"cut failed: {str(e)[:100]}",
                    clip_start=clip_start_sec, clip_end=clip_end_sec,
                ))
                if tmp_clip.exists():
                    tmp_clip.unlink()
                continue

            if not tmp_clip.exists():
                continue

            # 5b. Quality gate — cheap post-cut check for too-dark / too-static /
            # too-low-bitrate clips. Catches AI-ambience / CGI content that
            # slips past the JoyCaption content filter. No GPU needed.
            ok, reason, _ = check_quality(tmp_clip)
            if not ok:
                results.append(_make_row(
                    video_name, source_type, username, category, channel_id, video_id,
                    status="rejected", reason=f"quality: {reason}",
                    clip_start=clip_start_sec, clip_end=clip_end_sec,
                ))
                tmp_clip.unlink()
                continue

            # 6. Content-address
            clip_hash = content_hash_file(tmp_clip)
            ext = tmp_clip.suffix
            final_name = f"{clip_hash[:16]}{ext}"
            final_path = validated_dir / final_name

            if final_path.exists():
                tmp_clip.unlink()
                continue

            shutil.move(str(tmp_clip), str(final_path))
            clips_cut += 1

            # Store captions for this clip
            clip_captions[final_name] = captions

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
                    except Exception:
                        pass

            results.append({
                "source_file": video_name,
                "source_type": source_type,
                "username": username,
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
                "has_text_overlay": has_text_overlay,
                "has_watermark": has_watermark,
                "process_timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "validated",
                "reject_reason": "",
            })

    return results, clip_captions


def _make_row(video_name, source_type, username, category, channel_id, video_id,
              status="", reason="", clip_start="", clip_end=""):
    return {
        "source_file": video_name, "source_type": source_type,
        "username": username, "category": category,
        "channel_id": channel_id, "video_id": video_id,
        "clip_filename": "", "clip_start": clip_start, "clip_end": clip_end,
        "clip_duration": "", "content_hash": "", "width": "", "height": "",
        "fps": "", "codec": "",
        "has_text_overlay": "", "has_watermark": "",
        "process_timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status, "reject_reason": reason,
    }


def process_directory(
    input_dir: Path,
    config,
    model: JoyCaptionModel,
    validated_dir: Path,
    manifest_dir: Path,
    captions_dir: Path,
    source_type: str = "youtube",
    category: str = "",
    shard_id: int = 0,
    num_shards: int = 1,
):
    """Process all videos in a directory.

    Layout (both source types):
      input_dir          — source videos live here (e.g. <root>/staging/<cat>/)
      validated_dir      — cut clips are written here (e.g. <root>/validated/<cat>/)
      manifest_dir       — process_manifest[_shard<N>].csv lives at dataset root
      captions_dir       — captions[_shard<N>].json lives at dataset root

    All metadata (manifests, captions, info JSONs) live at the dataset root,
    not inside staging/. Source videos in staging/ are never moved; the
    manifest is the single source of truth for per-clip validation outcomes.
    """
    video_dir = input_dir

    videos = sorted([
        f for f in video_dir.iterdir()
        if is_source_clip(f) and not f.name.startswith("_tmp")
    ]) if video_dir.exists() else []

    if not videos:
        print(f"  No videos in {video_dir}")
        return

    # Load already-processed from main manifest + all shard manifests. For
    # resume, consider ALL rows regardless of category (manifest_dir is the
    # single root-level location), but filter to THIS category so other cats'
    # source_file names don't accidentally mark this cat's sources as done.
    manifest_dir.mkdir(parents=True, exist_ok=True)
    captions_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "process_manifest.csv"
    processed = set()
    for mf in [manifest_path] + list(manifest_dir.glob("process_manifest_shard*.csv")):
        if mf.exists():
            with open(mf) as f:
                for row in csv.DictReader(f):
                    if row.get("category", "") == category or source_type == "instagram":
                        processed.add(row.get("source_file", ""))

    remaining = [v for v in videos if v.stem not in processed]

    # Shard: each worker takes every Nth video
    if num_shards > 1:
        remaining = [v for i, v in enumerate(remaining) if i % num_shards == shard_id]

    if not remaining:
        print(f"  {category or source_type}: nothing to process (shard {shard_id}/{num_shards})")
        return

    # Per-shard manifest to avoid file locking between workers
    if num_shards > 1:
        manifest_path = manifest_dir / f"process_manifest_shard{shard_id}.csv"

    label = category or source_type
    if num_shards > 1:
        label = f"{label} [shard {shard_id}/{num_shards}]"
    print(f"  {label}: {len(remaining)} to process ({len(processed)} already done)")

    # For Instagram, load manifest to get username per file. IG download
    # manifest lives at the dataset root alongside process manifests.
    username_map: dict[str, str] = {}
    if source_type == "instagram":
        for candidate in (
            manifest_dir / "download_manifest.csv",
            manifest_dir / "manifest.csv",
            input_dir.parent / "manifest.csv",
        ):
            if candidate.exists():
                with open(candidate) as f:
                    for row in csv.DictReader(f):
                        fn = row.get("filename", "")
                        username_map[fn] = row.get("username", "")
                break

    # Captions file — per-shard to avoid locking
    captions_path = captions_dir / (f"captions_shard{shard_id}.json" if num_shards > 1
                                    else "captions.json")
    all_captions: dict[str, list[str]] = {}
    if captions_path.exists():
        with open(captions_path) as f:
            all_captions = json.load(f)

    validated = rejected = errors = 0
    pbar = tqdm(remaining, desc=label, unit="vid")

    for video_path in pbar:
        username = username_map.get(video_path.name, "")
        rows, clip_caps = process_video(
            video_path, config, model,
            validated_dir=validated_dir,
            processed_set=processed,
            source_type=source_type,
            username=username,
            category=category,
        )

        if rows:
            write_header = not manifest_path.exists()
            with open(manifest_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROCESS_MANIFEST_FIELDS)
                if write_header:
                    writer.writeheader()
                for row in rows:
                    writer.writerow(row)

        # Save captions incrementally
        if clip_caps:
            all_captions.update(clip_caps)
            with open(captions_path, "w") as f:
                json.dump(all_captions, f)

        for r in rows:
            if r["status"] == "validated":
                validated += 1
            elif r["status"] == "rejected":
                rejected += 1
            else:
                errors += 1

        processed.add(video_path.stem)
        pbar.set_postfix(v=validated, r=rejected, e=errors)

    pbar.close()
    print(f"  {category or source_type}: {validated} validated, {rejected} rejected, {errors} errors")


@click.command(help="Process videos into validated clips")
@click.option("--config", "-c", required=True, help="Config file")
@click.option("--category", default=None, help="Process specific category (YouTube only)")
@click.option("--gpu", type=int, default=0, help="GPU index (set CUDA_VISIBLE_DEVICES externally)")
@click.option("--shards", type=int, default=1, help="Total number of shards")
@click.option("--shard-id", type=int, default=0, help="This worker's shard ID (0-indexed)")
@click.option("--dry-run", is_flag=True)
def main(config, category, gpu, shards, shard_id, dry_run):
    from configs import load_config
    cfg = load_config(config)

    media_type = getattr(cfg, "MEDIA_TYPE", "video")
    source_type = "instagram" if "instagram" in cfg.NAME else "youtube"
    # OUTPUT_DIR is the dataset root. All metadata (manifests, captions)
    # lives directly under the root — not inside staging/. Source videos
    # live in staging/<cat>/, cut clips in validated/<cat>/.
    base_dir = Path(getattr(cfg, "OUTPUT_DIR", f"data/videos/real/{source_type}"))
    staging_root = base_dir / "staging"
    validated_root = base_dir / "validated"
    manifest_dir = base_dir     # process_manifest.csv sits at root
    captions_dir = base_dir     # captions.json sits at root

    if dry_run:
        main_mf = manifest_dir / "process_manifest.csv"
        done_by_cat = {}
        if main_mf.exists():
            with open(main_mf) as f:
                for r in csv.DictReader(f):
                    done_by_cat[r.get("category", "")] = done_by_cat.get(r.get("category", ""), 0) + 1
        if source_type == "youtube":
            categories = [category] if category else getattr(cfg, "CATEGORIES", [])
            for cat in categories:
                cat_dir = staging_root / cat
                if not cat_dir.exists():
                    continue
                chunks = [f for f in cat_dir.iterdir() if is_source_clip(f)]
                print(f"{cat}: {len(chunks)} chunks in staging, {done_by_cat.get(cat, 0)} manifest rows")
        else:
            if staging_root.exists():
                videos = [f for f in staging_root.iterdir() if is_source_clip(f)]
                print(f"{cfg.NAME}: {len(videos)} videos in staging, {sum(done_by_cat.values())} manifest rows")
        return

    model = JoyCaptionModel()

    if source_type == "youtube":
        categories = [category] if category else getattr(cfg, "CATEGORIES", [])
        for cat in categories:
            input_dir = staging_root / cat
            if not input_dir.exists():
                continue
            process_directory(
                input_dir, cfg, model,
                validated_dir=validated_root / cat,
                manifest_dir=manifest_dir,
                captions_dir=captions_dir,
                source_type="youtube", category=cat,
                shard_id=shard_id, num_shards=shards,
            )
    else:
        process_directory(
            staging_root, cfg, model,
            validated_dir=validated_root,
            manifest_dir=manifest_dir,
            captions_dir=captions_dir,
            source_type="instagram",
            shard_id=shard_id, num_shards=shards,
        )


if __name__ == "__main__":
    main()
