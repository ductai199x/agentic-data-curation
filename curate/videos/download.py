"""YouTube video downloader for real video dataset.

Downloads 4-minute chunks from verified channels in round-robin across categories.
Separate from the processing pipeline — just downloads and records metadata.

Usage:
    uv run python -m curate.videos.download --config configs/curate/videos/youtube.py
    uv run python -m curate.videos.download --config configs/curate/videos/youtube.py --workers 4
    uv run python -m curate.videos.download --config configs/curate/videos/youtube.py --dry-run
"""

import click
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from tqdm import tqdm

from .rate_limiter import run_ytdlp


# Fallback defaults — overridden by config
_VERIFIED_DIR = Path("configs/video_sources/verified")
_OUTPUT_BASE = Path("data/videos/real/youtube")  # root; "staging/" subdir joined below
_MAX_HEIGHT = 1080
_CHUNK_DURATION = 240
_SKIP_START = 120
_SKIP_END = 120

MANIFEST_FIELDS = [
    "channel_id", "channel_name", "video_id", "filename",
    "title", "upload_date", "duration", "chunk_start", "chunk_end",
    "width", "height", "max_available_height", "codec", "fps",
    "license", "yt_category", "tags", "description",
    "download_timestamp", "file_size", "status", "error",
]


class ProgressTracker:
    """Thread-safe progress tracker for bytes, speed, and video counts."""

    def __init__(self):
        self._lock = Lock()
        self.videos_done = 0
        self.videos_failed = 0
        self.bytes_downloaded = 0
        self.start_time = time.time()
        self.pbar = tqdm(
            desc="Downloading",
            unit="vid",
            file=sys.stderr,
            bar_format="{desc}: {n_fmt} vids | {postfix} | {elapsed}",
        )

    def record_success(self, file_size: int):
        with self._lock:
            self.videos_done += 1
            self.bytes_downloaded += file_size
            elapsed = time.time() - self.start_time
            speed_mbps = (self.bytes_downloaded / 1e6) / elapsed if elapsed > 0 else 0
            self.pbar.n = self.videos_done
            self.pbar.set_postfix_str(
                f"{self.bytes_downloaded / 1e9:.1f}GB | "
                f"{speed_mbps:.1f}MB/s | "
                f"{self.videos_failed} failed"
            )
            self.pbar.refresh()

    def record_failure(self):
        with self._lock:
            self.videos_failed += 1
            elapsed = time.time() - self.start_time
            speed_mbps = (self.bytes_downloaded / 1e6) / elapsed if elapsed > 0 else 0
            self.pbar.set_postfix_str(
                f"{self.bytes_downloaded / 1e9:.1f}GB | "
                f"{speed_mbps:.1f}MB/s | "
                f"{self.videos_failed} failed"
            )
            self.pbar.refresh()

    def close(self):
        self.pbar.close()


class CategoryDownloader:
    """Manages downloads for a single category."""

    def __init__(self, category: str, output_base: Path = _OUTPUT_BASE):
        self.category = category
        # output_base is the staging root (…/youtube/staging). Manifests
        # live at the dataset root under download_manifests/, not inside
        # each cat dir — staging/ holds only source videos.
        self.output_dir = output_base / category
        self.output_dir.mkdir(parents=True, exist_ok=True)
        dataset_root = output_base.parent
        manifest_root = dataset_root / "download_manifests"
        manifest_root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = manifest_root / f"{category}.csv"
        self._manifest_lock = Lock()

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


def load_channels(category: str, verified_dir: Path = _VERIFIED_DIR) -> list[tuple[str, str]]:
    """Load verified channels for a category. Returns [(channel_id, channel_name)]."""
    filepath = verified_dir / f"{category}.txt"
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
    """List video IDs from a channel. Returns [{id, duration, title}]."""
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


def _compute_chunk_range(
    duration: float,
    chunk_duration: int = _CHUNK_DURATION,
    skip_start: int = _SKIP_START,
    skip_end: int = _SKIP_END,
    min_video_duration: int = 60,
) -> tuple[int, int] | None:
    """Compute a chunk from the middle, skipping intro/outro."""
    if duration < min_video_duration:
        return None

    if duration < chunk_duration:
        return (0, int(duration))

    usable_start = min(skip_start, duration * 0.1)
    usable_end = max(duration - skip_end, duration * 0.9)
    usable = usable_end - usable_start

    if usable < chunk_duration:
        center = duration / 2
        start = max(0, int(center - chunk_duration / 2))
        return (start, start + chunk_duration)

    center = usable_start + usable / 2
    start = int(center - chunk_duration / 2)
    return (start, start + chunk_duration)


def download_video(
    video_id: str,
    video_duration: float,
    channel_id: str,
    channel_name: str,
    cat_downloader: CategoryDownloader,
    progress: ProgressTracker,
    max_height: int = _MAX_HEIGHT,
    chunk_duration: int = _CHUNK_DURATION,
    skip_start: int = _SKIP_START,
    skip_end: int = _SKIP_END,
    min_video_duration: int = 60,
) -> bool:
    """Download a chunk and record metadata in one yt-dlp call."""
    if video_id in cat_downloader.downloaded_videos:
        return False

    chunk = _compute_chunk_range(
        video_duration, chunk_duration, skip_start, skip_end, min_video_duration,
    )
    if chunk is None:
        cat_downloader.append_manifest({
            **{k: "" for k in MANIFEST_FIELDS},
            "channel_id": channel_id, "channel_name": channel_name,
            "video_id": video_id, "status": "skipped",
            "error": f"too short ({video_duration:.0f}s)",
            "download_timestamp": datetime.now(timezone.utc).isoformat(),
        })
        cat_downloader.downloaded_videos.add(video_id)
        return False

    start, end = chunk
    base_name = f"{channel_id}_{video_id}_{start}-{end}"
    output_template = str(cat_downloader.output_dir / f"{base_name}.%(ext)s")

    # Check if already downloaded (any extension)
    existing = [f for f in cat_downloader.output_dir.glob(f"{base_name}.*")
                if f.suffix not in (".json", ".part")]
    if existing:
        cat_downloader.downloaded_videos.add(video_id)
        return False

    # Single yt-dlp call: download chunk + write metadata json
    # rate_limit=False — downloads are CDN transfers, not API calls
    result = run_ytdlp([
        "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
        "--download-sections", f"*{start}-{end}",
        "--write-info-json",
        "-o", output_template,
        "--no-playlist",
        f"https://www.youtube.com/watch?v={video_id}",
    ], timeout=300, rate_limit=False)

    # Find the downloaded file (could be .webm, .mkv, .mp4, .avi, etc.)
    downloaded = [f for f in cat_downloader.output_dir.glob(f"{base_name}.*")
                  if f.suffix not in (".json", ".part")]
    filepath = downloaded[0] if downloaded else None

    if result.returncode != 0 or not filepath:
        error_msg = result.stderr[-300:].strip() if result.stderr else "unknown error"
        cat_downloader.append_manifest({
            **{k: "" for k in MANIFEST_FIELDS},
            "channel_id": channel_id, "channel_name": channel_name,
            "video_id": video_id, "status": "failed",
            "error": error_msg[:500],
            "download_timestamp": datetime.now(timezone.utc).isoformat(),
        })
        cat_downloader.downloaded_videos.add(video_id)
        progress.record_failure()
        return False

    # Parse metadata from info.json (written by yt-dlp alongside the video)
    info = {}
    info_json = list(cat_downloader.output_dir.glob(f"{base_name}.info.json"))
    if info_json:
        try:
            with open(info_json[0]) as f:
                info = json.load(f)
            info_json[0].unlink()  # Clean up — we've captured what we need in manifest
        except (json.JSONDecodeError, OSError):
            pass

    max_avail = max((fmt.get("height") or 0) for fmt in info.get("formats", [{}]))
    file_size = filepath.stat().st_size

    cat_downloader.downloaded_videos.add(video_id)
    cat_downloader.append_manifest({
        "channel_id": channel_id,
        "channel_name": channel_name,
        "video_id": video_id,
        "filename": filepath.name,
        "title": str(info.get("title", ""))[:200],
        "upload_date": info.get("upload_date", ""),
        "duration": info.get("duration", video_duration),
        "chunk_start": start,
        "chunk_end": end,
        "width": info.get("width", 0),
        "height": info.get("height", 0),
        "max_available_height": max_avail,
        "codec": info.get("vcodec", ""),
        "fps": info.get("fps", 0),
        "license": info.get("license", "Standard YouTube License"),
        "yt_category": (info.get("categories", []) or [""])[0],
        "tags": "|".join(info.get("tags") or [])[:500],
        "description": str(info.get("description", ""))[:500],
        "download_timestamp": datetime.now(timezone.utc).isoformat(),
        "file_size": file_size,
        "status": "downloaded",
        "error": "",
    })

    progress.record_success(file_size)
    return True


class RoundRobinDownloader:
    """Downloads video chunks round-robin across categories and channels."""

    def __init__(
        self,
        config=None,
        categories: list[str] | None = None,
        videos_per_channel: int = 10,
        max_per_category: int = 0,
        workers: int = 4,
        max_height: int | None = None,
    ):
        # Read from config, fall back to defaults
        self.verified_dir = Path(getattr(config, "VERIFIED_CHANNELS_DIR", _VERIFIED_DIR))
        # OUTPUT_DIR is the dataset root; downloads land in <root>/staging/<cat>/
        self.output_base = Path(getattr(config, "OUTPUT_DIR", _OUTPUT_BASE)) / "staging"
        self.chunk_duration = getattr(config, "CHUNK_DURATION", _CHUNK_DURATION)
        self.skip_start = getattr(config, "SKIP_START", _SKIP_START)
        self.skip_end = getattr(config, "SKIP_END", _SKIP_END)
        self.min_video_duration = getattr(config, "MIN_VIDEO_DURATION", 60)
        self.max_height = max_height or getattr(config, "MAX_HEIGHT", _MAX_HEIGHT)

        if categories is None:
            categories = getattr(config, "CATEGORIES", None)
        if categories is None:
            categories = sorted([f.stem for f in self.verified_dir.glob("C*.txt")])

        self.categories = categories
        self.videos_per_channel = videos_per_channel
        self.max_per_category = max_per_category
        self.workers = workers

        self.downloaders: dict[str, CategoryDownloader] = {}
        self.channel_queues: dict[str, list[tuple[str, str]]] = {}
        self.channel_index: dict[str, int] = {}
        self.video_cache: dict[str, list[dict]] = {}
        self.cat_downloaded: dict[str, int] = {}

        for cat in categories:
            self.downloaders[cat] = CategoryDownloader(cat, self.output_base)
            self.channel_queues[cat] = load_channels(cat, self.verified_dir)
            self.channel_index[cat] = 0
            self.cat_downloaded[cat] = len(self.downloaders[cat].downloaded_videos)

    def _get_next_video(self, category: str) -> tuple[str, str, str, float] | None:
        """Get next (channel_id, channel_name, video_id, duration).

        Round-robins across channels for maximum diversity.
        """
        channels = self.channel_queues[category]
        downloader = self.downloaders[category]

        if self.max_per_category and self.cat_downloaded[category] >= self.max_per_category:
            return None

        attempts = 0
        while attempts < len(channels):
            idx = self.channel_index[category] % len(channels)
            channel_id, channel_name = channels[idx]
            self.channel_index[category] = idx + 1

            if channel_id not in self.video_cache:
                videos = list_channel_video_ids(channel_id, self.videos_per_channel)
                self.video_cache[channel_id] = [
                    v for v in videos
                    if v["duration"] > self.min_video_duration
                    and v["id"] not in downloader.downloaded_videos
                ]

            vids = self.video_cache[channel_id]
            if vids:
                video = vids.pop(0)
                return (channel_id, channel_name, video["id"], video["duration"])

            attempts += 1
        return None

    def _generate_tasks(self) -> list[tuple[str, str, str, str, float]]:
        """Generate round-robin tasks: (cat, cid, cname, vid, duration)."""
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
                    tasks.append((cat, *result))

            if len(tasks) >= self.workers * 2:
                break

        return tasks

    def run(self, total_limit: int = 0):
        """Run the downloader."""
        progress = ProgressTracker()

        while True:
            tasks = self._generate_tasks()
            if not tasks:
                tqdm.write("All categories exhausted.")
                break

            if total_limit and progress.videos_done >= total_limit:
                break

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {}
                for cat, cid, cname, vid, dur in tasks:
                    if total_limit and progress.videos_done + len(futures) >= total_limit:
                        break
                    future = executor.submit(
                        download_video, vid, dur, cid, cname,
                        self.downloaders[cat], progress, self.max_height,
                        self.chunk_duration, self.skip_start, self.skip_end,
                        self.min_video_duration,
                    )
                    futures[future] = (cat, vid)

                for future in as_completed(futures):
                    cat, vid = futures[future]
                    try:
                        ok = future.result(timeout=660)
                        if ok:
                            self.cat_downloaded[cat] = self.cat_downloaded.get(cat, 0) + 1
                    except Exception:
                        progress.record_failure()

        progress.close()

        print(f"\n{'='*60}")
        print(f"Download Summary")
        print(f"{'='*60}")
        print(f"  Downloaded: {progress.videos_done}")
        print(f"  Failed: {progress.videos_failed}")
        print(f"  Total size: {progress.bytes_downloaded / 1e9:.1f}GB")
        print(f"\n  Per category:")
        for cat in sorted(self.categories):
            count = len(self.downloaders[cat].downloaded_videos)
            if count:
                print(f"    {cat}: {count}")
        print(f"{'='*60}")


@click.command(help="Download YouTube videos")
@click.option("--config", "-c", default=None, help="Config file (e.g. configs/curate/videos/youtube.py)")
@click.option("--workers", type=int, default=None, help="Override config DOWNLOAD_WORKERS")
@click.option("--videos-per-channel", type=int, default=None, help="Override config VIDEOS_PER_CHANNEL")
@click.option("--max-per-category", type=int, default=0)
@click.option("--total-limit", type=int, default=0)
@click.option("--category", default=None, help="Single category")
@click.option("--dry-run", is_flag=True)
def main(config, workers, videos_per_channel, max_per_category, total_limit,
         category, dry_run):
    cfg = None
    if config:
        from configs import load_config
        cfg = load_config(config)

    categories = [category] if category else None
    workers_n = workers or getattr(cfg, "DOWNLOAD_WORKERS", 4)
    vpc = videos_per_channel or getattr(cfg, "VIDEOS_PER_CHANNEL", 10)
    verified_dir = Path(getattr(cfg, "VERIFIED_CHANNELS_DIR", _VERIFIED_DIR))
    # OUTPUT_DIR is the dataset root; downloaders join "staging/<cat>/"
    output_base = Path(getattr(cfg, "OUTPUT_DIR", _OUTPUT_BASE)) / "staging"

    if dry_run:
        cats = categories or getattr(cfg, "CATEGORIES", None)
        if cats is None:
            cats = sorted([f.stem for f in verified_dir.glob("C*.txt")])
        for cat in cats:
            channels = load_channels(cat, verified_dir)
            dl = CategoryDownloader(cat, output_base)
            print(f"{cat}: {len(channels)} channels, {len(dl.downloaded_videos)} downloaded")
        return

    downloader = RoundRobinDownloader(
        config=cfg,
        categories=categories,
        videos_per_channel=vpc,
        max_per_category=max_per_category,
        workers=workers_n,
    )
    downloader.run(total_limit=total_limit)


if __name__ == "__main__":
    main()
