"""YouTube channel discovery and quality pre-screening.

Two phases:
1. Discovery: search queries → unique channels per content category
2. Pre-screening: sample 2-3 videos per channel → auto-check quality

Usage:
    # Discover channels for all categories
    uv run python -m curate.videos.discover --discover --output configs/video_sources/

    # Pre-screen discovered channels (requires GPU for JoyCaption)
    uv run python -m curate.videos.discover --screen --input configs/video_sources/ --gpu 6

    # Both in one run
    uv run python -m curate.videos.discover --discover --screen --output configs/video_sources/ --gpu 6
"""

import click
import csv
import json
import subprocess
import sys
from pathlib import Path

from .rate_limiter import run_ytdlp
from .youtube import get_video_info, list_channel_videos

# ── Search queries per content category ─────────────────────────────

CATEGORY_QUERIES = {
    "C01_people_casual": [
        "vlog daily life", "street photography video 4K", "people watching 4K",
        "city life documentary", "daily routine vlog", "family vlog day",
        "travel vlog walking", "day in my life vlog", "student life vlog",
        "market shopping vlog", "everyday life Japan", "everyday life India",
        "everyday life Brazil", "everyday life Nigeria", "street interview",
    ],
    "C02_people_action": [
        "sports raw footage", "skateboarding POV GoPro", "surfing GoPro POV",
        "parkour POV", "rock climbing POV", "martial arts training footage",
        "CrossFit workout full", "basketball pickup game", "soccer match amateur",
        "running trail POV", "swimming GoPro underwater", "boxing training",
        "dance practice full", "gymnastics practice", "BMX riding POV",
    ],
    "C03_talking_head": [
        "podcast full episode", "long form interview", "podcast conversation",
        "video essay commentary", "reaction video full", "roundtable discussion",
        "therapy session roleplay", "coaching call recording", "book review vlog",
        "commentary video essay", "debate full video", "fireside chat",
        "creator podcast episode", "business interview full", "motivational talk",
    ],
    "C04_lecture": [
        "MIT OpenCourseWare lecture", "Stanford lecture full", "Harvard lecture",
        "Yale lecture", "university lecture full", "conference talk full",
        "TED talk", "academic seminar recording", "Coursera lecture",
        "Khan Academy", "physics lecture university", "math lecture full",
        "computer science lecture", "biology lecture university",
        "history lecture full", "economics lecture", "philosophy lecture full",
    ],
    "C05_nature_landscape": [
        "nature 4K relaxation", "nature documentary footage raw",
        "timelapse nature 4K", "sunset timelapse 4K", "ocean waves 4K",
        "forest ambience 4K", "mountain scenery 4K", "river stream 4K",
        "desert landscape 4K", "aurora borealis timelapse", "flower blooming timelapse",
        "nature sounds 4K video", "countryside 4K", "volcano footage 4K",
    ],
    "C06_nature_wildlife": [
        "wildlife footage 4K", "bird watching video", "safari footage raw",
        "underwater marine life 4K", "animal behavior documentary raw",
        "owl camera live", "eagle nest cam", "deer trail camera",
        "whale watching footage", "coral reef 4K", "African wildlife 4K",
        "insect macro video", "bear cam footage", "penguin colony footage",
    ],
    "C07_nature_water": [
        "ocean waves 4K", "underwater diving 4K", "river kayak POV",
        "waterfall 4K", "scuba diving footage", "snorkeling 4K",
        "rain 4K video", "storm footage 4K", "lake 4K relaxation",
        "ice formations 4K", "tsunami footage real", "flood footage real",
    ],
    "C08_walking_biking_tour": [
        "walking tour 4K", "city walk 4K", "night walk city 4K",
        "biking tour city 4K", "walking tour Europe 4K", "walking tour Asia 4K",
        "walking tour Africa 4K", "walking tour South America 4K",
        "market tour 4K", "hiking trail POV 4K", "walking tour Middle East",
        "walking tour rain 4K", "walking tour snow 4K", "walking tour morning",
        "bike ride city POV", "cycling tour countryside", "mall walking tour",
        "walking tour Tokyo", "walking tour New York", "walking tour London",
        "walking tour Paris", "walking tour Istanbul", "walking tour Bangkok",
        "walking tour Seoul", "walking tour Mumbai", "walking tour Lagos",
        "walking tour Cairo", "walking tour Rio", "walking tour Moscow",
        "walking tour Berlin", "walking tour Rome", "walking tour Barcelona",
        "walking tour Amsterdam", "walking tour Dubai", "walking tour Singapore",
    ],
    "C09_urban_street": [
        "street scene 4K", "city traffic 4K", "time lapse city traffic",
        "busy intersection 4K", "pedestrian crossing 4K",
        "night city 4K", "rainy city 4K", "market street 4K",
    ],
    "C10_urban_architecture": [
        "architecture tour 4K", "building exterior 4K", "interior design tour",
        "modern architecture walkthrough", "historic building tour",
        "skyscraper 4K", "cathedral interior 4K",
    ],
    "C11_vehicles_exterior": [
        "car spotting 4K", "train passing 4K", "airplane landing 4K",
        "boat sailing footage", "car race footage", "truck driving footage",
        "ship in storm footage", "motorcycle ride scenic",
    ],
    "C12_vehicles_pov": [
        "dashcam footage", "driving 4K", "dashcam compilation real",
        "road trip dashcam", "truck dashcam", "motorcycle POV ride",
        "cycling POV city", "bus ride POV window", "train ride window view 4K",
        "cockpit view flight", "dashcam highway", "driving rain dashcam",
        "driving snow dashcam", "cab ride POV", "taxi dashcam",
    ],
    "C13_cooking": [
        "cooking ASMR no talking", "cooking POV recipe", "outdoor cooking campfire",
        "professional chef cooking", "street food cooking POV",
        "baking recipe no music", "Korean cooking ASMR", "Japanese cooking video",
        "Italian cooking authentic", "Indian cooking recipe", "Mexican cooking",
        "BBQ smoking full cook", "wok cooking professional", "sushi making",
        "pasta making handmade", "bread baking from scratch", "pizza making",
    ],
    "C14_product_review": [
        "phone review unboxing", "laptop review 2024", "camera review hands on",
        "tech unboxing", "gadget review", "headphone review comparison",
        "shoe review on feet", "clothing haul try on",
    ],
    "C15_animals_domestic": [
        "cat video compilation", "dog park footage", "puppy cam live",
        "kitten playing", "farm animals video", "horse riding POV",
        "aquarium fish 4K", "pet birds video", "zoo animals footage 4K",
    ],
    "C16_hands_objects": [
        "ASMR crafting", "woodworking project full", "pottery making",
        "drawing timelapse", "calligraphy writing", "mechanical watch repair",
        "electronics repair", "lock picking", "origami folding",
    ],
    "C17_aerial_drone": [
        "drone footage 4K", "aerial view city 4K", "DJI drone cinematic",
        "FPV drone flight", "drone nature 4K", "drone beach 4K",
        "drone mountain 4K", "drone Europe 4K", "drone Asia 4K",
        "aerial landscape 4K", "drone sunset 4K", "drone river 4K",
    ],
    "C18_weather_atmosphere": [
        "storm footage 4K", "lightning storm video", "tornado footage real",
        "blizzard footage 4K", "fog timelapse 4K", "sunrise timelapse 4K",
        "cloud timelapse 4K", "rain ambience video 4K",
    ],
    "C19_macro_texture": [
        "macro video 4K", "slow motion 4K", "macro insect video",
        "water drops slow motion", "fire close up 4K", "bubbles macro",
        "crystal growing timelapse", "rust forming timelapse",
    ],
    "C20_security_camera": [
        "security camera footage real", "CCTV footage compilation real",
        "security camera catch", "home security camera footage",
        "parking lot security camera", "doorbell camera footage",
        "wildlife trail camera", "store security camera",
    ],
    "C21_indoor_everyday": [
        "room tour 4K", "home tour walkthrough", "office tour vlog",
        "gym workout POV", "classroom recording", "library ASMR",
        "restaurant ambience 4K", "cafe ambience 4K",
    ],
}


def search_channels(query: str, max_results: int = 30) -> dict[str, str]:
    """Search YouTube and extract unique channel IDs from results.

    Returns dict of channel_id → channel_name.
    """
    result = run_ytdlp([
        "--flat-playlist",
        "--print", "%(channel_id)s\t%(channel)s",
        "--playlist-end", str(max_results),
        f"ytsearch{max_results}:{query}",
    ], timeout=60)
    channels = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t", 1)
        if len(parts) == 2 and parts[0] not in ("NA", ""):
            channels[parts[0]] = parts[1]
    return channels


def discover_channels(output_dir: str | Path) -> dict[str, dict]:
    """Run discovery queries for all categories. Save per-category channel lists.

    Returns summary dict of category → {channels: N, queries: N}.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = {}
    global_channels = {}  # track cross-category duplicates

    for category, queries in CATEGORY_QUERIES.items():
        cat_channels = {}
        for q in queries:
            try:
                channels = search_channels(q, max_results=30)
                for cid, name in channels.items():
                    if cid not in cat_channels:
                        cat_channels[cid] = name
            except Exception as e:
                print(f"  Query failed: {q} ({e})")

        # Save channel list
        outfile = output_dir / f"{category}.txt"
        with open(outfile, "w") as f:
            f.write(f"# {category} — {len(cat_channels)} channels\n")
            f.write(f"# Auto-discovered, needs pre-screening\n")
            f.write(f"# Format: channel_id<tab>channel_name\n\n")
            for cid, name in sorted(cat_channels.items(), key=lambda x: x[1]):
                f.write(f"{cid}\t{name}\n")

        new_global = sum(1 for c in cat_channels if c not in global_channels)
        global_channels.update(cat_channels)

        print(f"{category:35s}: {len(cat_channels):4d} channels "
              f"({new_global} new, {len(queries)} queries)")
        summary[category] = {"channels": len(cat_channels), "queries": len(queries)}

    print(f"\n{'='*60}")
    print(f"Total unique channels: {len(global_channels)}")
    print(f"Saved to: {output_dir}/")

    # Save global summary
    with open(output_dir / "_summary.json", "w") as f:
        json.dump({
            "total_unique_channels": len(global_channels),
            "categories": summary,
        }, f, indent=2)

    return summary


def screen_channel(
    channel_id: str,
    channel_name: str,
) -> dict:
    """Pre-screen a channel using a single yt-dlp flat-playlist call.

    Uses --flat-playlist to get video count + durations in one request,
    avoiding multiple API calls that trigger rate limiting.

    Checks:
    - Number of videos (≥5)
    - Average video duration (≥120s)
    """
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    try:
        result = run_ytdlp([
            "--flat-playlist",
            "--print", "%(id)s\t%(duration)s\t%(title)s",
            "--playlist-end", "20",
            url,
        ], timeout=30)
    except Exception as e:
        return {"status": "error", "reason": str(e)[:100], "channel_id": channel_id}

    if result.returncode != 0:
        return {"status": "error", "reason": "yt-dlp failed", "channel_id": channel_id}

    videos = []
    for line in result.stdout.splitlines():
        parts = line.strip().split("\t", 2)
        if len(parts) >= 2:
            try:
                dur = float(parts[1]) if parts[1] != "NA" else 0
                title = parts[2] if len(parts) > 2 else ""
                videos.append({"id": parts[0], "duration": dur, "title": title})
            except (ValueError, IndexError):
                continue

    if len(videos) < 20:
        return {"status": "reject", "reason": f"too few videos ({len(videos)})",
                "channel_id": channel_id, "video_count": len(videos)}

    durations = [v["duration"] for v in videos if v["duration"] > 0]
    if not durations:
        return {"status": "error", "reason": "no duration info", "channel_id": channel_id}

    avg_duration = sum(durations) / len(durations)

    # Check if any titles mention 4K/1080p as a quality signal
    has_hd = any("4k" in v["title"].lower() or "1080" in v["title"].lower()
                  for v in videos)

    if avg_duration < 120:
        return {"status": "reject", "reason": f"avg duration too short ({avg_duration:.0f}s)",
                "channel_id": channel_id, "avg_duration": avg_duration,
                "video_count": len(videos)}

    return {
        "status": "pass",
        "reason": "ok",
        "channel_id": channel_id,
        "channel_name": channel_name,
        "video_count": len(videos),
        "avg_duration": round(avg_duration, 0),
        "has_hd_in_title": has_hd,
    }


# Tags that indicate non-camera content (matched as exact comma-separated tags)
# "digital art" excluded — JoyCaption uses it loosely on photorealistic content
NOT_CAMERA_TAGS = {
    "screenshot", "screen recording", "digital interface",
    "animation", "anime", "cartoon", "illustration",
    "3d render", "3d rendering", "cgi", "video game",
    "slideshow", "powerpoint",
    "graphic design", "infographic",
    "software", "app interface", "website", "browser",
}


def _caption_has_not_camera_tag(caption: str) -> str | None:
    """Check if a JoyCaption output indicates non-camera content.

    Uses exact tag matching on comma-separated booru tags.
    "scientific illustration" does NOT match "illustration".
    "animated expression" does NOT match "animated".

    Special handling for "digital art": only reject if "photograph" is NOT
    also present. JoyCaption says "photograph, digital art" on stylized
    photorealistic content, which is fine. But "digital art" without
    "photograph" means it's purely digital (not camera-captured).

    Returns the matched tag, or None if clean.
    """
    tags = {t.strip().lower() for t in caption.split(",")}

    # Check for "digital art" — only reject if "photograph" is absent
    if "digital art" in tags and "photograph" not in tags:
        return "digital art"

    matched = tags & NOT_CAMERA_TAGS
    return next(iter(matched)) if matched else None


def _list_channel_videos(
    channel_id: str,
    channel_name: str = "",
    max_videos: int = 20,
) -> tuple[list[dict], str]:
    """List videos from a channel, with automatic ID correction.

    1. Try the given channel_id URL
    2. If that fails and channel_name is provided, search for a video by name,
       extract the correct channel_id, and retry

    Returns:
        Tuple of (video list, resolved_channel_id).
        resolved_channel_id may differ from input if it was corrected.
    """
    def _fetch(cid: str) -> list[dict]:
        url = f"https://www.youtube.com/channel/{cid}/videos"
        try:
            result = run_ytdlp([
                "--flat-playlist",
                "--print", "%(id)s\t%(duration)s\t%(title)s",
                "--playlist-end", str(max_videos),
                url,
            ], timeout=30)
            if result.returncode != 0:
                return []
        except Exception:
            return []

        videos = []
        for line in result.stdout.splitlines():
            parts = line.strip().split("\t", 2)
            if len(parts) >= 2 and parts[0] != "NA":
                try:
                    dur = float(parts[1]) if parts[1] not in ("NA", "None", "") else 0
                    title = parts[2] if len(parts) > 2 else ""
                    videos.append({"id": parts[0], "duration": dur, "title": title})
                except (ValueError, IndexError):
                    continue
        return videos

    # Try with original channel ID
    videos = _fetch(channel_id)
    if videos:
        return videos, channel_id

    # Channel ID failed — try to resolve correct ID via search
    if not channel_name:
        return [], channel_id

    try:
        result = run_ytdlp([
            "--flat-playlist",
            "--print", "%(channel_id)s",
            "--playlist-end", "1",
            f"ytsearch1:{channel_name}",
        ], timeout=15)
        resolved_id = result.stdout.strip().split("\n")[0].strip()
        if not resolved_id or resolved_id == "NA" or resolved_id == channel_id:
            return [], channel_id
    except Exception:
        return [], channel_id

    # Retry with resolved ID
    videos = _fetch(resolved_id)
    if videos:
        return videos, resolved_id

    return [], channel_id


def _check_video_camera_captured(
    vid_id: str,
    vid_dur: float,
    model,
    tmp_dir: Path,
) -> dict:
    """Check if a single video is camera-captured.

    Downloads 30s from the middle, extracts 5 frames, runs JoyCaption.
    Uses majority vote within the video: reject only if >50% of frames
    are flagged as non-camera.

    Returns dict with status ("pass", "reject", "error") and reason.
    """
    import uuid
    from .content_filter import extract_frames_from_window

    # Download 30s from the middle
    start_sec = max(30, vid_dur / 2 - 15) if vid_dur > 60 else 0
    duration_sec = min(30, vid_dur)
    # Unique filename to avoid collision with parallel workers
    tmp_video = tmp_dir / f"_screen_{vid_id}_{uuid.uuid4().hex[:8]}.webm"

    try:
        dl_result = run_ytdlp([
            "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
            "--merge-output-format", "webm",
            "--download-sections", f"*{start_sec:.0f}-{start_sec + duration_sec:.0f}",
            "-o", str(tmp_video),
            "--no-playlist", "--quiet",
            f"https://www.youtube.com/watch?v={vid_id}",
        ], timeout=120)
        if dl_result.returncode != 0 or not tmp_video.exists():
            return {"status": "error", "reason": "download failed"}
    except Exception as e:
        return {"status": "error", "reason": f"download: {str(e)[:60]}"}

    # Extract 5 frames (every 6s over 30s)
    try:
        frames = extract_frames_from_window(str(tmp_video), start=0, duration=duration_sec, interval=6)
    except Exception as e:
        return {"status": "error", "reason": f"frames: {str(e)[:60]}"}
    finally:
        # Cleanup — catch stale files from crashes too
        for p in tmp_dir.glob(f"_screen_{vid_id}_*"):
            try:
                p.unlink()
            except OSError:
                pass

    if not frames:
        return {"status": "error", "reason": "no frames"}

    # Caption
    try:
        captions = model.caption_batch(frames)
    except Exception as e:
        return {"status": "error", "reason": f"caption: {str(e)[:60]}"}

    # Check each frame — majority vote within video
    not_camera_count = 0
    reject_reasons = []

    for cap in captions:
        tag = _caption_has_not_camera_tag(cap)
        if tag:
            not_camera_count += 1
            reject_reasons.append(tag)

    # Majority vote: reject only if >50% of frames are non-camera
    total_frames = len(captions)
    is_reject = not_camera_count > total_frames / 2

    return {
        "status": "reject" if is_reject else "pass",
        "reason": (f"not camera: {', '.join(set(reject_reasons))} "
                   f"({not_camera_count}/{total_frames} frames)"
                   if is_reject else "camera-captured"),
        "captions": captions,
        "not_camera_count": not_camera_count,
    }


MIN_CHANNEL_VIDEOS = 20  # Reject channels with fewer than this many eligible videos


def deep_screen_channel(
    channel_id: str,
    channel_name: str,
    model,
    tmp_dir: Path,
) -> dict:
    """Deep-screen a channel by checking 1 video for camera-captured content.

    Downloads 30s from 1 video, extracts 5 frames, runs JoyCaption.
    Rejects channels with < 5 eligible videos (> 60s duration).

    Args:
        channel_id: YouTube channel ID.
        channel_name: Channel display name.
        model: Loaded JoyCaptionModel instance.
        tmp_dir: Temp directory for downloads.

    Returns:
        Dict with status, reason, and sample info.
    """
    # 1. List videos from the channel (with auto ID correction)
    all_videos, resolved_id = _list_channel_videos(channel_id, channel_name, max_videos=20)
    if resolved_id != channel_id:
        channel_id = resolved_id

    # Filter out Shorts and very short videos (< 61s)
    eligible = [v for v in all_videos if v["duration"] > 60]

    if len(eligible) < MIN_CHANNEL_VIDEOS:
        return {
            "status": "reject",
            "reason": f"too few videos ({len(eligible)} eligible, need {MIN_CHANNEL_VIDEOS})",
            "channel_id": channel_id,
            "channel_name": channel_name,
        }

    # 2. Pick 1 video from the middle of the listing
    video = eligible[len(eligible) // 2]

    # 3. Check if it's camera-captured
    vid_id = video["id"]
    vid_dur = video["duration"] if video["duration"] > 0 else 300

    result = _check_video_camera_captured(vid_id, vid_dur, model, tmp_dir)

    if result["status"] == "pass":
        return {
            "status": "pass",
            "reason": "camera-captured",
            "channel_id": channel_id,
            "channel_name": channel_name,
            "sample_videos": [vid_id],
        }
    elif result["status"] == "reject":
        return {
            "status": "reject",
            "reason": result["reason"],
            "channel_id": channel_id,
            "channel_name": channel_name,
            "sample_videos": [vid_id],
        }
    else:
        # Error on the first pick — try one more from the end
        video2 = eligible[-1]
        result2 = _check_video_camera_captured(
            video2["id"], video2["duration"] or 300, model, tmp_dir,
        )
        if result2["status"] == "pass":
            return {
                "status": "pass",
                "reason": "camera-captured",
                "channel_id": channel_id,
                "channel_name": channel_name,
                "sample_videos": [video2["id"]],
            }
        elif result2["status"] == "reject":
            return {
                "status": "reject",
                "reason": result2["reason"],
                "channel_id": channel_id,
                "channel_name": channel_name,
                "sample_videos": [video2["id"]],
            }
        else:
            return {
                "status": "error",
                "reason": "both sample videos failed to process",
                "channel_id": channel_id,
                "channel_name": channel_name,
            }


def screen_channels(
    input_dir: str | Path,
    output_dir: str | Path = None,
    max_workers: int = 4,
):
    """Pre-screen all discovered channels with parallel execution.

    Reads per-category .txt files, screens each channel (parallelized),
    writes approved channels to _approved/ subdirectory.

    Args:
        input_dir: Directory with discovered channel .txt files.
        output_dir: Output directory (default: input_dir/_approved/).
        max_workers: Number of parallel screening threads (default 16).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    input_dir = Path(input_dir)
    output_dir = Path(output_dir or input_dir) / "_approved"
    output_dir.mkdir(parents=True, exist_ok=True)

    global_approved = 0
    global_rejected = 0
    global_errors = 0

    import time

    for cat_file in sorted(input_dir.glob("C*.txt")):
        category = cat_file.stem
        channels = {}
        with open(cat_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    channels[parts[0]] = parts[1]

        if not channels:
            continue

        # Skip categories already screened (approved file has content beyond header)
        approved_file = output_dir / f"{category}.txt"
        if approved_file.exists() and approved_file.stat().st_size > 200:
            print(f"Skipping {category} (already screened)")
            continue

        print(f"\n{'='*60}")
        print(f"Screening {category}: {len(channels)} channels ({max_workers} workers)")
        print(f"{'='*60}")

        approved = []
        rejected = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(screen_channel, cid, name): (cid, name)
                for cid, name in channels.items()
            }
            for future in as_completed(futures):
                cid, name = futures[future]
                try:
                    result = future.result(timeout=60)
                except Exception as e:
                    errors += 1
                    continue
                time.sleep(0.5)  # Rate limit — avoid YouTube throttling

                if result["status"] == "pass":
                    approved.append(result)
                    hd = " 4K" if result.get("has_hd_in_title") else ""
                    print(f"  PASS  {name:40s} | {result['video_count']:3d} vids "
                          f"| avg {result['avg_duration']:.0f}s{hd}")
                elif result["status"] == "reject":
                    rejected += 1
                else:
                    errors += 1

        # Save approved channels
        outfile = output_dir / f"{category}.txt"
        with open(outfile, "w") as f:
            f.write(f"# {category} — {len(approved)} approved channels\n")
            f.write(f"# Pre-screened: {rejected} rejected, {errors} errors\n")
            f.write(f"# Format: channel_id<tab>channel_name<tab>video_count<tab>avg_duration<tab>has_hd\n\n")
            for ch in sorted(approved, key=lambda x: x["video_count"], reverse=True):
                f.write(f"{ch['channel_id']}\t{ch['channel_name']}\t"
                        f"{ch['video_count']}\t{ch['avg_duration']:.0f}\t"
                        f"{'4K' if ch.get('has_hd_in_title') else ''}\n")

        print(f"\n  Summary: {len(approved)} approved, {rejected} rejected, {errors} errors")
        global_approved += len(approved)
        global_rejected += rejected
        global_errors += errors

    print(f"\n{'='*60}")
    print(f"TOTAL: {global_approved} approved, {global_rejected} rejected, {global_errors} errors")
    print(f"Saved to: {output_dir}/")
    print(f"{'='*60}")


def deep_screen_channels(
    input_dir: str | Path,
    output_dir: str | Path = None,
    gpu: str = "6",
    max_workers: int = 2,
):
    """Deep-screen approved channels by downloading a sample video.

    Reads _approved/ channel lists, downloads 30s from 1 video per channel,
    verifies it's camera-captured via JoyCaption.

    Writes verified channels to _verified/ subdirectory.

    Args:
        input_dir: Directory with _approved/ channel lists.
        output_dir: Base output directory.
        gpu: GPU for JoyCaption.
        max_workers: Parallel download+caption workers (keep low to avoid YT throttle).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from .content_filter import JoyCaptionModel
    import time

    input_dir = Path(input_dir)
    approved_dir = input_dir / "_approved"
    verified_dir = (Path(output_dir) if output_dir else input_dir) / "_verified"
    verified_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = input_dir / "_tmp_screen"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Load JoyCaption model
    model = JoyCaptionModel.get()

    global_verified = 0
    global_rejected = 0
    global_errors = 0

    for cat_file in sorted(approved_dir.glob("C*.txt")):
        category = cat_file.stem

        # Skip already verified
        verified_file = verified_dir / f"{category}.txt"
        if verified_file.exists() and verified_file.stat().st_size > 200:
            print(f"Skipping {category} (already verified)")
            continue

        channels = {}
        with open(cat_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    channels[parts[0]] = parts[1]

        if not channels:
            continue

        print(f"\n{'='*60}")
        print(f"Deep screening {category}: {len(channels)} channels")
        print(f"{'='*60}")

        verified = []
        rejected = 0
        errors = 0

        # Sequential for now — each channel needs GPU + download
        for i, (cid, name) in enumerate(channels.items()):
            result = deep_screen_channel(cid, name, model, tmp_dir)

            if result["status"] == "pass":
                verified.append(result)
                print(f"  [{i+1}/{len(channels)}] PASS  {name:40s} | {result.get('caption_snippet', '')[:60]}")
            elif result["status"] == "reject":
                rejected += 1
                print(f"  [{i+1}/{len(channels)}] FAIL  {name:40s} | {result['reason'][:60]}")
            else:
                errors += 1
                print(f"  [{i+1}/{len(channels)}] ERR   {name:40s} | {result['reason'][:60]}")

            time.sleep(0.5)  # Rate limit

        # Save verified channels
        with open(verified_file, "w") as f:
            f.write(f"# {category} — {len(verified)} verified camera-captured channels\n")
            f.write(f"# Deep-screened: {rejected} rejected (not camera), {errors} errors\n")
            f.write(f"# Format: channel_id<tab>channel_name<tab>sample_video\n\n")
            for ch in verified:
                f.write(f"{ch['channel_id']}\t{ch['channel_name']}\t"
                        f"{ch.get('sample_video', '')}\n")

        print(f"\n  Summary: {len(verified)} verified, {rejected} rejected, {errors} errors")
        global_verified += len(verified)
        global_rejected += rejected
        global_errors += errors

    # Cleanup
    import shutil
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{'='*60}")
    print(f"TOTAL: {global_verified} verified, {global_rejected} rejected, {global_errors} errors")
    print(f"Saved to: {verified_dir}/")
    print(f"{'='*60}")


@click.command(help="YouTube channel discovery and screening")
@click.option("--discover", "do_discover", is_flag=True, help="Run discovery queries")
@click.option("--screen", "do_screen", is_flag=True, help="Quick pre-screen (metadata only)")
@click.option("--deep-screen", "do_deep_screen", is_flag=True,
              help="Deep screen (download sample, verify camera-captured)")
@click.option("--output", default="configs/video_sources",
              help="Output directory for channel lists")
@click.option("--input", "input_dir_opt", default=None,
              help="Input directory for screening (default: same as --output)")
@click.option("--gpu", default="6", help="GPU for JoyCaption")
def main(do_discover, do_screen, do_deep_screen, output, input_dir_opt, gpu):
    if not do_discover and not do_screen and not do_deep_screen:
        print("Specify --discover, --screen, --deep-screen, or a combination.")
        sys.exit(1)

    if do_discover:
        discover_channels(output)

    if do_screen:
        input_dir = input_dir_opt or output
        screen_channels(input_dir, output)

    if do_deep_screen:
        input_dir = input_dir_opt or output
        deep_screen_channels(input_dir, output, gpu=gpu)


if __name__ == "__main__":
    main()
