"""YouTube video downloader using yt-dlp.

Downloads videos at ≤1080p, records max available resolution in metadata.
Supports downloading by video ID, URL, channel, or playlist.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .rate_limiter import run_ytdlp


@dataclass
class YTVideoInfo:
    """Info about a YouTube video before/after download."""
    video_id: str
    title: str
    channel: str
    channel_id: str
    duration: float          # seconds
    upload_date: str         # YYYYMMDD
    max_height: int          # highest available resolution
    downloaded_height: int   # resolution we actually downloaded
    filepath: Path | None    # path to downloaded file (None if not yet downloaded)
    description: str = ""
    tags: list[str] | None = None


def get_video_info(video_id: str) -> YTVideoInfo:
    """Fetch video metadata without downloading.

    Args:
        video_id: YouTube video ID (e.g. "dQw4w9WgXcQ").

    Returns:
        YTVideoInfo with metadata. filepath will be None.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"
    result = run_ytdlp(["--dump-json", "--no-download", url], timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp info failed for {video_id}: {result.stderr[:200]}")

    info = json.loads(result.stdout)

    # Find max available height
    max_height = 0
    for fmt in info.get("formats", []):
        h = fmt.get("height") or 0
        if h > max_height:
            max_height = h

    return YTVideoInfo(
        video_id=info.get("id", video_id),
        title=info.get("title", ""),
        channel=info.get("channel", info.get("uploader", "")),
        channel_id=info.get("channel_id", ""),
        duration=float(info.get("duration", 0)),
        upload_date=info.get("upload_date", ""),
        max_height=max_height,
        downloaded_height=0,
        filepath=None,
        description=info.get("description", "")[:500],
        tags=info.get("tags"),
    )


def download_video(
    video_id: str,
    output_dir: str | Path,
    max_height: int = 1080,
) -> YTVideoInfo:
    """Download a YouTube video at ≤max_height resolution.

    Args:
        video_id: YouTube video ID.
        output_dir: Directory to save the video.
        max_height: Maximum download resolution (default 1080p).

    Returns:
        YTVideoInfo with filepath set to the downloaded file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    url = f"https://www.youtube.com/watch?v={video_id}"

    # Template: save as video_id.ext
    output_template = str(output_dir / "%(id)s.%(ext)s")

    result = run_ytdlp([
        # Format: best video ≤max_height + best audio
        "-f", f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]",
        # Use webm — AV1 in mp4 crashes ffmpeg 6.x, but AV1 in webm works
        "--merge-output-format", "webm",
        "-o", output_template,
        "--write-info-json",
        "--no-playlist",
        "--no-warnings",
        "--print-json",
        url,
    ], timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp download failed for {video_id}: {result.stderr[:300]}")

    info = json.loads(result.stdout)

    # Find the actual downloaded file (could be .webm, .mp4, .mkv)
    filepath = None
    for ext in [".webm", ".mp4", ".mkv"]:
        candidate = output_dir / f"{video_id}{ext}"
        if candidate.exists():
            filepath = candidate
            break
    if filepath is None:
        raise FileNotFoundError(
            f"Downloaded file not found for {video_id} in {output_dir}"
        )

    # Find max available height from format list
    max_available = 0
    for fmt in info.get("formats", []):
        h = fmt.get("height") or 0
        if h > max_available:
            max_available = h

    downloaded_height = info.get("height", 0)

    return YTVideoInfo(
        video_id=info.get("id", video_id),
        title=info.get("title", ""),
        channel=info.get("channel", info.get("uploader", "")),
        channel_id=info.get("channel_id", ""),
        duration=float(info.get("duration", 0)),
        upload_date=info.get("upload_date", ""),
        max_height=max_available,
        downloaded_height=downloaded_height,
        filepath=filepath,
        description=info.get("description", "")[:500],
        tags=info.get("tags"),
    )


def list_channel_videos(
    channel_url: str,
    max_videos: int = 100,
) -> list[str]:
    """List video IDs from a YouTube channel.

    Args:
        channel_url: Channel URL (e.g. "https://www.youtube.com/@channel/videos").
        max_videos: Maximum number of video IDs to return.

    Returns:
        List of video IDs.
    """
    result = run_ytdlp([
        "--flat-playlist", "--print", "id",
        "--playlist-end", str(max_videos),
        channel_url,
    ], timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist failed: {result.stderr[:200]}")

    video_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return video_ids


def list_playlist_videos(
    playlist_url: str,
    max_videos: int = 500,
) -> list[str]:
    """List video IDs from a YouTube playlist.

    Args:
        playlist_url: Playlist URL.
        max_videos: Maximum number of video IDs to return.

    Returns:
        List of video IDs.
    """
    result = run_ytdlp([
        "--flat-playlist", "--print", "id",
        "--playlist-end", str(max_videos),
        playlist_url,
    ], timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp playlist failed: {result.stderr[:200]}")

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def search_videos(
    query: str,
    max_results: int = 50,
) -> list[str]:
    """Search YouTube for videos matching a query.

    Args:
        query: Search query string.
        max_results: Maximum results to return.

    Returns:
        List of video IDs.
    """
    result = run_ytdlp([
        "--flat-playlist", "--print", "id",
        "--playlist-end", str(max_results),
        f"ytsearch{max_results}:{query}",
    ], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp search failed: {result.stderr[:200]}")

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
