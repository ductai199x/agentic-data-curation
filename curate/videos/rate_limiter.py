"""Centralized rate limiter for YouTube API calls.

All yt-dlp calls should go through run_ytdlp() to ensure
we don't exceed YouTube's rate limits.

Uses a file-based lock + timestamp to coordinate across
multiple processes (multiprocessing workers).
"""

import fcntl
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


# API rate limit: search, metadata, channel listing etc.
API_CALLS_PER_MINUTE = 59
API_MIN_INTERVAL = 60.0 / API_CALLS_PER_MINUTE

# Download rate limit: CDN transfers (YouTube throttles + rate-limits these too)
DOWNLOAD_CALLS_PER_MINUTE = 1
DOWNLOAD_MIN_INTERVAL = 60.0 / DOWNLOAD_CALLS_PER_MINUTE

LOCK_FILE = Path("/tmp/ytdlp_rate_limit.lock")
TIMESTAMP_FILE = Path("/tmp/ytdlp_rate_limit_ts")
DOWNLOAD_LOCK_FILE = Path("/tmp/ytdlp_download_rate_limit.lock")
DOWNLOAD_TIMESTAMP_FILE = Path("/tmp/ytdlp_download_rate_limit_ts")

# Default cookies path — set to None to disable
DEFAULT_COOKIES = Path("data/cookies/cookies-youtube.txt")


def _wait_for_slot(lock_file: Path, ts_file: Path, min_interval: float):
    """Wait until we can make another call without exceeding rate limit.

    Uses file locking for cross-process coordination.
    """
    lock_file.touch(exist_ok=True)
    ts_file.touch(exist_ok=True)

    with open(lock_file, "r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            ts_text = ts_file.read_text().strip()
            last_call = float(ts_text) if ts_text else 0.0

            elapsed = time.time() - last_call
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

            ts_file.write_text(str(time.time()))
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run_ytdlp(
    args: list[str],
    timeout: int = 60,
    cookies_path: str | None = "auto",
    rate_limit: bool = True,
) -> subprocess.CompletedProcess:
    """Run a yt-dlp command, optionally with rate limiting.

    Args:
        args: yt-dlp arguments (without the 'yt-dlp' command itself).
        timeout: Subprocess timeout in seconds.
        cookies_path: Path to cookies file. "auto" = use default if exists.
        rate_limit: If True, wait for rate limit slot. Set False for
            downloads (CDN transfers don't trigger API rate limits).

    Returns:
        subprocess.CompletedProcess result.
    """
    if rate_limit:
        _wait_for_slot(LOCK_FILE, TIMESTAMP_FILE, API_MIN_INTERVAL)
    else:
        # Downloads are also rate-limited, just at a lower rate
        _wait_for_slot(DOWNLOAD_LOCK_FILE, DOWNLOAD_TIMESTAMP_FILE, DOWNLOAD_MIN_INTERVAL)

    cmd = ["yt-dlp", "--remote-components", "ejs:github"]

    # Copy cookies to a temp file so yt-dlp doesn't rewrite the original
    tmp_cookie = None
    if cookies_path == "auto":
        if DEFAULT_COOKIES.exists():
            tmp_cookie = tempfile.NamedTemporaryFile(
                suffix=".txt", prefix="ytdlp_cookies_", delete=False,
            )
            shutil.copy(DEFAULT_COOKIES, tmp_cookie.name)
            os.chmod(tmp_cookie.name, 0o644)
            tmp_cookie.close()
            cmd += ["--cookies", tmp_cookie.name]
    elif cookies_path:
        cmd += ["--cookies", cookies_path]

    cmd += args

    # Ensure deno is on PATH for YouTube's n-parameter challenge
    env = os.environ.copy()
    deno_bin = Path.home() / ".deno" / "bin"
    if deno_bin.exists() and str(deno_bin) not in env.get("PATH", ""):
        env["PATH"] = f"{deno_bin}:{env.get('PATH', '')}"

    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    finally:
        if tmp_cookie:
            Path(tmp_cookie.name).unlink(missing_ok=True)
