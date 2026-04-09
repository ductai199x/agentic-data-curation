"""YouTube video downloader for real video dataset.

Downloads full videos from verified channels in round-robin across categories.
Separate from the processing pipeline — just downloads and records metadata.

Features:
- Round-robin across 21 categories for balanced progress
- Concurrent downloads (configurable workers)
- Full metadata manifest per category (license, title, tags, etc.)
- Resumable via manifest (skips already-downloaded videos)
- Rate-limited via centralized rate limiter
- Downloads at ≤1080p, records max available resolution

Usage:
    # Download with 4 concurrent workers, 10 videos per channel
    uv run python -m video.download --workers 4 --videos-per-channel 10

    # Download specific category only
    uv run python -m video.download --category C08_walking_biking_tour --workers 4

    # Dry run — list what would be downloaded
    uv run python -m video.download --dry-run
"""

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from tqdm import tqdm

from .rate_limiter import run_ytdlp


VERIFIED_DIR = Path("configs/video_sources/verified")
OUTPUT_BASE = Path("data/videos/real/youtube")
MAX_HEIGHT = 1080

MANIFEST_FIELDS = [
    "channel_id",
    "channel_name",
    "video_id",
    "filename",
    "title",
    "upload_date",
    "duration",
    "width",
    "height",
    "max_available_height",
    "codec",
    "fps",
    "license",
    "yt_category",
    "tags",
    "description",
    "download_timestamp",
    "file_size",
    "status",
]


class CategoryDownloader:
    """Manages downloads for a single category."""

    def __init__(self, category: str, output_base: Path = OUTPUT_BASE):
        self.category = category
        self.output_dir = output_base / category
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.output_dir / "manifest.csv"
        self._manifest_lock = Lock()

        # Load already-downloaded video IDs for resume
        self.downloaded_videos: set[str] = set()
        if self.manifest_path.exists():
            with open(self.manifest_path) as f:
                for row in csv.DictReader(f):
                    vid = row.get("video_id", "")
                    if vid:
                        self.downloaded_videos.add(vid)

    def append_manifest(self, row: dict):
        with self._manifest_lock:
            write_header = not self.manifest_path.exists()
            with open(self.manifest_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)


def load_channels(category: str) -> list[tuple[str, str]]:
    """Load verified channel IDs and names for a category.

    Returns list of (channel_id, channel_name).
    """
    filepath = VERIFIED_DIR / f"{category}.txt"
    if not filepath.exists():
        return []
    channels = []
    with open(filepath) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                channels.append((parts[0], parts[1]))
    return channels


def list_channel_video_ids(channel_id: str, max_videos: int = 20) -> list[dict]:
    """List video IDs from a channel with basic metadata.

    Returns list of dicts with id, duration, title.
    """
    result = run_ytdlp([
        "--flat-playlist",
        "--print", "%(id)s\t%(duration)s\t%(title)s",
        "--playlist-end", str(max_videos),
        f"https://www.youtube.com/channel/{channel_id}/videos",
    ], timeout=30)

    if result.returncode != 0:
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


def download_video(
    video_id: str,
    channel_id: str,
    channel_name: str,
    cat_downloader: CategoryDownloader,
    max_height: int = MAX_HEIGHT,
) -> bool:
    """Download a single video and record metadata.

    Returns True if downloaded successfully.
    """
    if video_id in cat_downloader.downloaded_videos:
        return False

    filename = f"{channel_id}_{video_id}.webm"
    filepath = cat_downloader.output_dir / filename

    if filepath.exists():
        cat_downloader.downloaded_videos.add(video_id)
        return False

    # Download with full metadata
    result = run_ytdlp([
        "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
        "--merge-output-format", "webm",
        "-o", str(filepath),
        "--no-playlist",
        "--print-json",
        f"https://www.youtube.com/watch?v={video_id}",
    ], timeout=600)

    if result.returncode != 0:
        return False

    # Parse metadata from yt-dlp JSON output
    try:
        info = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        # Download might have succeeded but JSON parsing failed
        if filepath.exists() and filepath.stat().st_size > 0:
            info = {}
        else:
            return False

    if not filepath.exists():
        return False

    # Find max available height
    max_avail = 0
    for fmt in info.get("formats", []):
        h = fmt.get("height") or 0
        if h > max_avail:
            max_avail = h

    # Record metadata
    cat_downloader.downloaded_videos.add(video_id)
    cat_downloader.append_manifest({
        "channel_id": channel_id,
        "channel_name": channel_name,
        "video_id": video_id,
        "filename": filename,
        "title": str(info.get("title", ""))[:200],
        "upload_date": info.get("upload_date", ""),
        "duration": info.get("duration", 0),
        "width": info.get("width", 0),
        "height": info.get("height", 0),
        "max_available_height": max_avail,
        "codec": info.get("vcodec", ""),
        "fps": info.get("fps", 0),
        "license": info.get("license", "Standard YouTube License"),
        "yt_category": info.get("categories", [""])[0] if info.get("categories") else "",
        "tags": "|".join(info.get("tags", []))[:500] if info.get("tags") else "",
        "description": str(info.get("description", ""))[:500],
        "download_timestamp": datetime.now(timezone.utc).isoformat(),
        "file_size": filepath.stat().st_size,
        "status": "downloaded",
    })

    return True


def build_download_queue(
    categories: list[str],
    videos_per_channel: int = 10,
    max_per_category: int = 0,
) -> list[tuple[str, str, str, str]]:
    """Build a round-robin download queue across categories.

    Returns list of (category, channel_id, channel_name, video_id).
    """
    # For each category, build list of (channel_id, channel_name, video_ids)
    cat_queues: dict[str, list[tuple[str, str, str]]] = {}

    for category in categories:
        channels = load_channels(category)
        if not channels:
            continue

        # Load already-downloaded for this category
        downloader = CategoryDownloader(category)
        already = downloader.downloaded_videos

        queue = []
        for channel_id, channel_name in channels:
            # We'll resolve video IDs lazily during download
            # For now, just queue channel entries
            queue.append((channel_id, channel_name))

        cat_queues[category] = queue

    return cat_queues


class RoundRobinDownloader:
    """Downloads videos round-robin across categories with concurrent workers."""

    def __init__(
        self,
        categories: list[str] | None = None,
        videos_per_channel: int = 10,
        max_per_category: int = 0,
        workers: int = 4,
        max_height: int = MAX_HEIGHT,
    ):
        if categories is None:
            categories = sorted([
                f.stem for f in VERIFIED_DIR.glob("C*.txt")
            ])

        self.categories = categories
        self.videos_per_channel = videos_per_channel
        self.max_per_category = max_per_category
        self.workers = workers
        self.max_height = max_height

        # Per-category state
        self.downloaders: dict[str, CategoryDownloader] = {}
        self.channel_queues: dict[str, list[tuple[str, str]]] = {}
        self.channel_index: dict[str, int] = {}
        self.video_cache: dict[str, list[dict]] = {}  # channel_id -> video list
        self.cat_downloaded: dict[str, int] = {}

        for cat in categories:
            self.downloaders[cat] = CategoryDownloader(cat)
            channels = load_channels(cat)
            self.channel_queues[cat] = channels
            self.channel_index[cat] = 0
            self.cat_downloaded[cat] = len(self.downloaders[cat].downloaded_videos)

    def _get_next_video(self, category: str) -> tuple[str, str, str] | None:
        """Get next (channel_id, channel_name, video_id) for a category.

        Round-robins across channels: takes 1 video from the current channel,
        then advances to the next channel. This maximizes channel diversity.
        Returns None if all channels exhausted.
        """
        channels = self.channel_queues[category]
        downloader = self.downloaders[category]
        max_cat = self.max_per_category

        if max_cat and self.cat_downloaded[category] >= max_cat:
            return None

        # Try channels starting from current index
        attempts = 0
        while attempts < len(channels):
            idx = self.channel_index[category] % len(channels)
            channel_id, channel_name = channels[idx]

            # Always advance to next channel for next call (round-robin)
            self.channel_index[category] = idx + 1

            # Get or fetch video list for this channel
            if channel_id not in self.video_cache:
                videos = list_channel_video_ids(channel_id, self.videos_per_channel)
                # Filter to >60s, not already downloaded
                self.video_cache[channel_id] = [
                    v for v in videos
                    if v["duration"] > 60 and v["id"] not in downloader.downloaded_videos
                ]

            vids = self.video_cache[channel_id]
            if vids:
                video = vids.pop(0)
                return (channel_id, channel_name, video["id"])

            # This channel exhausted, try next
            attempts += 1

        return None

    def _generate_tasks(self) -> list[tuple[str, str, str, str]]:
        """Generate round-robin download tasks across categories.

        Yields (category, channel_id, channel_name, video_id) in round-robin order.
        """
        tasks = []
        active_cats = list(self.categories)
        exhausted = set()

        while active_cats:
            for cat in list(active_cats):
                if cat in exhausted:
                    continue
                result = self._get_next_video(cat)
                if result is None:
                    exhausted.add(cat)
                    active_cats.remove(cat)
                else:
                    channel_id, channel_name, video_id = result
                    tasks.append((cat, channel_id, channel_name, video_id))

            # Stop after generating a batch
            if len(tasks) >= self.workers * 2:
                break

        return tasks

    def run(self, total_limit: int = 0):
        """Run the downloader."""
        total_downloaded = 0
        total_failed = 0

        pbar = tqdm(desc="Downloading", unit="vid", file=sys.stderr)

        while True:
            # Generate next batch of tasks
            tasks = self._generate_tasks()
            if not tasks:
                print("All categories exhausted.", flush=True)
                break

            if total_limit and total_downloaded >= total_limit:
                break

            # Execute batch concurrently
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {}
                for cat, cid, cname, vid in tasks:
                    if total_limit and total_downloaded + len(futures) >= total_limit:
                        break
                    future = executor.submit(
                        download_video, vid, cid, cname,
                        self.downloaders[cat], self.max_height,
                    )
                    futures[future] = (cat, cid, cname, vid)

                for future in as_completed(futures):
                    cat, cid, cname, vid = futures[future]
                    try:
                        ok = future.result(timeout=660)
                    except Exception as e:
                        ok = False

                    if ok:
                        total_downloaded += 1
                        self.cat_downloaded[cat] = self.cat_downloaded.get(cat, 0) + 1
                        pbar.update(1)
                        pbar.set_postfix(total=total_downloaded)
                    else:
                        total_failed += 1

        pbar.close()

        # Print summary
        print(f"\n{'='*60}")
        print(f"Download Summary")
        print(f"{'='*60}")
        print(f"  Total downloaded: {total_downloaded}")
        print(f"  Total failed: {total_failed}")
        print(f"\n  Per category:")
        for cat in sorted(self.categories):
            count = len(self.downloaders[cat].downloaded_videos)
            print(f"    {cat}: {count}")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Download YouTube videos for real video dataset")
    parser.add_argument("--workers", type=int, default=4,
                        help="Concurrent download workers (default 4)")
    parser.add_argument("--videos-per-channel", type=int, default=10,
                        help="Max videos to consider per channel (default 10)")
    parser.add_argument("--max-per-category", type=int, default=0,
                        help="Max videos per category (0 = unlimited)")
    parser.add_argument("--total-limit", type=int, default=0,
                        help="Total download limit (0 = unlimited)")
    parser.add_argument("--category", help="Download specific category only")
    parser.add_argument("--dry-run", action="store_true",
                        help="List what would be downloaded without downloading")
    args = parser.parse_args()

    categories = None
    if args.category:
        categories = [args.category]

    if args.dry_run:
        cats = categories or sorted([f.stem for f in VERIFIED_DIR.glob("C*.txt")])
        for cat in cats:
            channels = load_channels(cat)
            dl = CategoryDownloader(cat)
            print(f"{cat}: {len(channels)} channels, {len(dl.downloaded_videos)} already downloaded")
        return

    downloader = RoundRobinDownloader(
        categories=categories,
        videos_per_channel=args.videos_per_channel,
        max_per_category=args.max_per_category,
        workers=args.workers,
    )
    downloader.run(total_limit=args.total_limit)


if __name__ == "__main__":
    main()
