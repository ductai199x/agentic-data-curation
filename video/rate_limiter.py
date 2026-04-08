"""Centralized rate limiter for YouTube API calls.

All yt-dlp calls should go through run_ytdlp() to ensure
we don't exceed YouTube's rate limits.

Uses a file-based lock + timestamp to coordinate across
multiple processes (multiprocessing workers).
"""

import fcntl
import subprocess
import time
from pathlib import Path


# Global rate limit: max N calls per minute across ALL processes
# With cookies, 50/min is safe — targets ~23hr for 12K channels on 8 GPUs
MAX_CALLS_PER_MINUTE = 50
MIN_INTERVAL = 60.0 / MAX_CALLS_PER_MINUTE  # seconds between calls

LOCK_FILE = Path("/tmp/ytdlp_rate_limit.lock")
TIMESTAMP_FILE = Path("/tmp/ytdlp_rate_limit_ts")

# Default cookies path — set to None to disable
DEFAULT_COOKIES = Path("data/cookies/cookies-youtube.txt")


def _wait_for_slot():
    """Wait until we can make another yt-dlp call without exceeding rate limit.

    Uses file locking for cross-process coordination.
    """
    LOCK_FILE.touch(exist_ok=True)
    TIMESTAMP_FILE.touch(exist_ok=True)

    with open(LOCK_FILE, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            # Read last call timestamp
            ts_text = TIMESTAMP_FILE.read_text().strip()
            last_call = float(ts_text) if ts_text else 0.0

            # Wait if needed
            elapsed = time.time() - last_call
            if elapsed < MIN_INTERVAL:
                time.sleep(MIN_INTERVAL - elapsed)

            # Record this call
            TIMESTAMP_FILE.write_text(str(time.time()))
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_ytdlp(
    args: list[str],
    timeout: int = 60,
    cookies_path: str | None = "auto",
) -> subprocess.CompletedProcess:
    """Run a yt-dlp command with rate limiting.

    All yt-dlp calls should go through this function.

    Args:
        args: yt-dlp arguments (without the 'yt-dlp' command itself).
        timeout: Subprocess timeout in seconds.
        cookies_path: Path to cookies file. "auto" = use default if exists.
            None = no cookies.

    Returns:
        subprocess.CompletedProcess result.
    """
    _wait_for_slot()

    cmd = ["yt-dlp"]

    # Resolve cookies path
    if cookies_path == "auto":
        if DEFAULT_COOKIES.exists():
            cmd += ["--cookies", str(DEFAULT_COOKIES)]
    elif cookies_path:
        cmd += ["--cookies", cookies_path]

    cmd += args

    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
