"""Backfill manifest.csv rows for orphan YouTube videos.

An "orphan" is a video file on disk (in `data/videos/real/youtube/Cxx_*/`)
whose filename is not recorded in that category's manifest.csv. They exist
because Hamed and Aref's downloads occasionally failed to write a row.

For each orphan, we:
  1. Parse the filename -> (channel_id, video_id, chunk_start, chunk_end)
  2. Fetch video metadata from yt-dlp (cached per video_id so the same video
     across multiple categories only costs one API call)
  3. ffprobe the local file for codec, width, height, fps
  4. Append a fully-populated row to that category's manifest.csv.

Usage:
    uv run python -m video.backfill_orphan_manifest \\
        --root data/videos/real/youtube \\
        --cookies data/cookies/cookies-youtube.txt
"""
from __future__ import annotations

import click
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp

VIDEO_EXTS = {".webm", ".mkv", ".mp4"}

# Filename pattern: UC<22chars>_<11char_video_id>_<start>-<end>.<ext>
FILENAME_RE = re.compile(r"^(UC[\w-]{22})_([\w-]{11})_(\d+)-(\d+)\.(\w+)$")

MANIFEST_FIELDS = [
    "channel_id", "channel_name", "video_id", "filename", "title",
    "upload_date", "duration", "chunk_start", "chunk_end",
    "width", "height", "max_available_height", "codec", "fps",
    "license", "yt_category", "tags", "description",
    "download_timestamp", "file_size", "status", "error",
]


def collect_orphans(root: Path) -> dict[str, list[tuple[Path, str, str, int, int, str]]]:
    """Scan `root/staging/<cat>/` for orphan video files (not in manifest).

    Manifests live at `root/download_manifests/<cat>.csv`. Returns
    {cat: [(path, channel_id, video_id, start, end, ext)...]}.
    """
    out: dict[str, list[tuple[Path, str, str, int, int, str]]] = {}
    staging_root = root / "staging"
    manifest_root = root / "download_manifests"
    for cat_dir in sorted(staging_root.glob("C*")):
        if not cat_dir.is_dir():
            continue
        cat = cat_dir.name
        mf = manifest_root / f"{cat}.csv"
        in_manifest: set[str] = set()
        if mf.exists():
            with open(mf) as f:
                for r in csv.DictReader(f):
                    fn = r.get("filename", "").strip()
                    if fn:
                        in_manifest.add(fn)
        orphans = []
        for vid_path in cat_dir.iterdir():
            if vid_path.suffix.lower() not in VIDEO_EXTS:
                continue
            if vid_path.name in in_manifest:
                continue
            m = FILENAME_RE.match(vid_path.name)
            if not m:
                continue
            ch, vid, s, e, ext = m.groups()
            orphans.append((vid_path, ch, vid, int(s), int(e), ext))
        if orphans:
            out[cat] = orphans
    return out


def ffprobe_video(path: Path) -> dict:
    """Return {width, height, codec, fps, file_size}. Best-effort — empty on error."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,codec_name,r_frame_rate",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {"file_size": path.stat().st_size}
        j = json.loads(r.stdout)
        s = (j.get("streams") or [{}])[0]
        fps_expr = s.get("r_frame_rate", "0/1")
        try:
            n, d = fps_expr.split("/")
            fps = round(float(n) / float(d), 2) if float(d) else None
        except Exception:
            fps = None
        return {
            "width": s.get("width"),
            "height": s.get("height"),
            "codec": s.get("codec_name"),
            "fps": fps,
            "file_size": path.stat().st_size,
        }
    except Exception:
        return {"file_size": path.stat().st_size if path.exists() else 0}


def fetch_yt_info(ydl: yt_dlp.YoutubeDL, video_id: str) -> dict | None:
    """Return yt-dlp metadata dict, or None on error."""
    try:
        return ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}",
            download=False, process=False,
        )
    except Exception as e:
        return {"__error": str(e)[:180]}


def build_row(
    path: Path, channel_id: str, video_id: str, chunk_s: int, chunk_e: int,
    yt_info: dict | None, probe: dict,
) -> dict:
    """Compose a manifest row from filename + yt-dlp + ffprobe."""
    now = datetime.now(timezone.utc).isoformat()

    if yt_info is None:
        yt_info = {}
    error = yt_info.get("__error", "")

    # Max available height = maximum height across fetched formats
    formats = yt_info.get("formats") or []
    heights = [f.get("height") for f in formats if isinstance(f.get("height"), int)]
    max_h = max(heights) if heights else ""

    return {
        "channel_id": channel_id,
        "channel_name": (yt_info.get("channel") or yt_info.get("uploader") or "").strip(),
        "video_id": video_id,
        "filename": path.name,
        "title": (yt_info.get("title") or "").strip(),
        "upload_date": yt_info.get("upload_date") or "",
        "duration": yt_info.get("duration") or "",
        "chunk_start": chunk_s,
        "chunk_end": chunk_e,
        "width": probe.get("width") or "",
        "height": probe.get("height") or "",
        "max_available_height": max_h,
        "codec": probe.get("codec") or "",
        "fps": probe.get("fps") or "",
        "license": yt_info.get("license") or "",
        "yt_category": (yt_info.get("categories") or [""])[0] if yt_info.get("categories") else "",
        "tags": "|".join(yt_info.get("tags") or []),
        "description": yt_info.get("description") or "",
        "download_timestamp": now,
        "file_size": probe.get("file_size", 0),
        "status": "downloaded",
        "error": error,
    }


@click.command()
@click.option("--root", type=click.Path(path_type=Path), required=True,
              help="Root of youtube dataset (contains Cxx_* subdirs)")
@click.option("--cookies", type=click.Path(path_type=Path), required=True,
              help="Netscape-format cookies file; copied to tmp (yt-dlp rewrites)")
@click.option("--sleep", "sleep_s", type=float, default=1.0,
              help="Seconds to sleep between yt-dlp calls (rate limit).")
@click.option("--limit", type=int, default=0,
              help="Stop after this many orphans (0 = no limit).")
def main(root: Path, cookies: Path, sleep_s: float, limit: int):
    # Make a writable copy of cookies (yt-dlp's cookiejar.save rewrites)
    cookies_tmp = Path(tempfile.mkdtemp(prefix="yt_cookies_")) / "cookies.txt"
    shutil.copy(cookies, cookies_tmp)
    cookies_tmp.chmod(0o600)

    orphans_by_cat = collect_orphans(root)
    total = sum(len(v) for v in orphans_by_cat.values())
    print(f"orphan videos: {total} across {len(orphans_by_cat)} categories", flush=True)
    if limit and total > limit:
        print(f"(will stop after {limit} per --limit)", flush=True)

    ydl_opts = {
        "quiet": True, "skip_download": True, "no_warnings": True,
        "cookiefile": str(cookies_tmp),
        "sleep_interval_requests": sleep_s,
    }
    ydl = yt_dlp.YoutubeDL(ydl_opts)

    yt_cache: dict[str, dict | None] = {}
    processed = 0
    errs = 0
    written_by_cat: dict[str, int] = {}

    try:
        for cat, orphans in orphans_by_cat.items():
            rows_to_write: list[dict] = []
            for path, ch, vid, s, e, ext in orphans:
                if limit and processed >= limit:
                    break
                processed += 1
                if vid in yt_cache:
                    info = yt_cache[vid]
                else:
                    info = fetch_yt_info(ydl, vid)
                    yt_cache[vid] = info
                    time.sleep(sleep_s)
                if info and "__error" in info:
                    errs += 1
                probe = ffprobe_video(path)
                row = build_row(path, ch, vid, s, e, info, probe)
                rows_to_write.append(row)
                if processed % 25 == 0 or processed == total:
                    print(f"  [{processed:>4}/{total}] cat={cat:<30} errs={errs}",
                          flush=True)

            # Append rows to download_manifests/<cat>.csv (create header if new)
            if rows_to_write:
                mf = root / "download_manifests" / f"{cat}.csv"
                existed = mf.exists()
                with open(mf, "a", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
                    if not existed:
                        w.writeheader()
                    for row in rows_to_write:
                        w.writerow({k: row.get(k, "") for k in MANIFEST_FIELDS})
                written_by_cat[cat] = len(rows_to_write)

            if limit and processed >= limit:
                break
    finally:
        ydl.close()

    print(f"\ndone. wrote {sum(written_by_cat.values())} rows across "
          f"{len(written_by_cat)} categories; yt-dlp errors: {errs}")
    for cat in sorted(written_by_cat):
        print(f"  {cat:30s} +{written_by_cat[cat]}")


if __name__ == "__main__":
    main()
