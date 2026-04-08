"""Video curation pipeline.

End-to-end: download → metadata → cut → scene detect → content filter → manifest.

Two modes:
- Default: full pipeline including JoyCaption content filtering + watermark detection
- --skip-filter: only download/cut/scene-detect, skip JoyCaption (clips stay in staging/)

Usage:
    # Full pipeline with content filtering
    uv run python -m video.pipeline --video-id dQw4w9WgXcQ --source youtube --gpu 6

    # Skip content filtering (just download + cut + scene detect)
    uv run python -m video.pipeline --search "walking tour tokyo 4k" --source youtube --skip-filter

    # Process from a file of video IDs
    uv run python -m video.pipeline --id-file video_ids.txt --source youtube --gpu 6

    # Process a YouTube channel
    uv run python -m video.pipeline --channel "https://www.youtube.com/@channel" --source youtube --max-videos 50
"""

import argparse
import csv
import hashlib
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .cutter import compute_candidate_windows, clip_quota, cut_clip, content_hash_file
from .metadata import probe, VideoMeta
from .youtube import (
    download_video,
    list_channel_videos,
    list_playlist_videos,
    search_videos,
    YTVideoInfo,
)


# Minimum requirements for a clip to pass
MIN_DURATION = 3.0       # seconds
MIN_HEIGHT = 480         # pixels (480p minimum)
MIN_FPS = 15.0


MANIFEST_FIELDS = [
    "clip_filename",
    "source_video_id",
    "source_url",
    "channel",
    "channel_id",
    "source_title",
    "upload_date",
    "platform",
    "clip_index",
    "clip_start",
    "clip_end",
    "duration",
    "width",
    "height",
    "fps",
    "codec",
    "bitrate",
    "file_size",
    "max_available_height",
    "downloaded_height",
    "content_hash",
    "has_audio",
    "timestamp",
    "status",
]


class VideoPipeline:
    """Orchestrates the full video curation pipeline."""

    def __init__(
        self,
        source: str = "youtube",
        output_base: str | Path = "data/videos/real",
        max_height: int = 1080,
        force: bool = False,
        skip_filter: bool = False,
        gpu: str = "6",
    ):
        self.source = source
        self.output_dir = Path(output_base) / source
        self.staging_dir = self.output_dir / "staging"
        self.validated_dir = self.output_dir / "validated"
        self.rejected_dir = self.output_dir / "rejected"
        self.max_height = max_height
        self.force = force
        self.skip_filter = skip_filter
        self.gpu = gpu
        self._filter_model = None

        # Create directories
        for d in [self.staging_dir, self.validated_dir, self.rejected_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Temp dir for raw downloads before cutting
        self.tmp_dir = self.output_dir / "_tmp_downloads"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        # Manifest
        self.manifest_path = self.output_dir / "manifest.csv"

        # Load already-processed video IDs for resume
        self.processed_ids: set[str] = set()
        self.processed_hashes: set[str] = set()
        if not force:
            self._load_manifest()

        # Stats
        self.stats = {
            "videos_processed": 0,
            "videos_skipped_resume": 0,
            "videos_skipped_short": 0,
            "videos_skipped_low_res": 0,
            "videos_failed_download": 0,
            "clips_scanned": 0,
            "clips_rejected_cuts": 0,
            "clips_rejected_content": 0,
            "clips_rejected_watermark": 0,
            "clips_duplicate": 0,
            "clips_staged": 0,
            "clips_validated": 0,
        }

    def _load_manifest(self):
        """Load previously processed video IDs and clip hashes."""
        if not self.manifest_path.exists():
            return
        with open(self.manifest_path) as f:
            for row in csv.DictReader(f):
                self.processed_ids.add(row.get("source_video_id", ""))
                h = row.get("content_hash", "")
                if h:
                    self.processed_hashes.add(h)
        print(f"Resume: {len(self.processed_ids)} videos already processed, "
              f"{len(self.processed_hashes)} clips in manifest")

    def _append_manifest(self, row: dict):
        """Append a row to the manifest CSV."""
        write_header = not self.manifest_path.exists()
        with open(self.manifest_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def process_video(self, video_id: str) -> int:
        """Process a single YouTube video through the full pipeline.

        Flow: download → compute candidates → iterate (filter → scene detect → cut) → stop at quota.

        Returns number of validated clips produced.
        """
        if video_id in self.processed_ids:
            self.stats["videos_skipped_resume"] += 1
            return 0

        # 1. Download
        print(f"\n--- Processing {video_id} ---")
        try:
            info = download_video(video_id, self.tmp_dir, max_height=self.max_height)
        except Exception as e:
            print(f"  Download failed: {e}")
            self.stats["videos_failed_download"] += 1
            self.processed_ids.add(video_id)
            return 0

        source_path = info.filepath
        self.stats["videos_processed"] += 1

        # 2. Check metadata
        try:
            meta = probe(source_path)
        except Exception as e:
            print(f"  Metadata extraction failed: {e}")
            self._cleanup_source(source_path, video_id)
            return 0

        if meta.duration < MIN_DURATION:
            print(f"  Too short: {meta.duration:.1f}s")
            self.stats["videos_skipped_short"] += 1
            self._cleanup_source(source_path, video_id)
            return 0

        if meta.height < MIN_HEIGHT:
            print(f"  Low res: {meta.height}p")
            self.stats["videos_skipped_low_res"] += 1
            self._cleanup_source(source_path, video_id)
            return 0

        # 3. Compute candidate windows and clip quota
        quota = clip_quota(meta.duration)
        candidates = compute_candidate_windows(meta.duration)

        print(f"  Source: {meta.width}x{meta.height} {meta.fps}fps "
              f"{meta.codec} {meta.duration:.0f}s "
              f"(max available: {info.max_height}p) "
              f"| quota={quota}, candidates={len(candidates)}")

        if not candidates:
            print(f"  No candidate windows (video too short)")
            self._cleanup_source(source_path, video_id)
            return 0

        # 4. Iterate candidates: filter → scene detect → cut → stop at quota
        kept = 0
        scanned = 0
        for i, (start, end) in enumerate(candidates):
            if kept >= quota:
                break
            scanned += 1
            self.stats["clips_scanned"] += 1

            # 4a. Scene detection + content filter on the window
            #     (both use the same extracted frames — no redundant decoding)
            if not self.skip_filter:
                filter_result = self._filter_window(source_path, start, end)
                if not filter_result["passed"]:
                    reason = filter_result["reason"]
                    print(f"  Window {i} [{start:.0f}s-{end:.0f}s]: rejected ({reason})")
                    if "scene cuts" in reason:
                        self.stats["clips_rejected_cuts"] += 1
                    elif "watermark" in reason:
                        self.stats["clips_rejected_watermark"] += 1
                    else:
                        self.stats["clips_rejected_content"] += 1
                    continue

            # 4b. Cut the clip (only if it passed filter + scene detection)
            ext = source_path.suffix
            tmp_clip = self.staging_dir / f"_tmp_clip{ext}"
            try:
                cut_clip(source_path, tmp_clip, start, end)
            except Exception as e:
                print(f"  Window {i} [{start:.0f}s-{end:.0f}s]: cut failed ({e})")
                if tmp_clip.exists():
                    tmp_clip.unlink()
                continue

            # 4c. Content-address and check duplicate
            clip_hash = content_hash_file(tmp_clip)
            if clip_hash in self.processed_hashes:
                self.stats["clips_duplicate"] += 1
                tmp_clip.unlink()
                continue

            # 4e. Finalize — rename to content-addressed filename
            final_name = f"{clip_hash[:16]}{ext}"
            dest_dir = self.validated_dir if not self.skip_filter else self.staging_dir
            final_path = dest_dir / final_name
            shutil.move(str(tmp_clip), str(final_path))

            self.processed_hashes.add(clip_hash)
            kept += 1
            status = "validated" if not self.skip_filter else "staging"
            if self.skip_filter:
                self.stats["clips_staged"] += 1
            else:
                self.stats["clips_validated"] += 1

            clip_meta = probe(final_path)

            self._append_manifest({
                "clip_filename": final_name,
                "source_video_id": video_id,
                "source_url": f"https://www.youtube.com/watch?v={video_id}",
                "channel": info.channel,
                "channel_id": info.channel_id,
                "source_title": info.title[:200],
                "upload_date": info.upload_date,
                "platform": self.source,
                "clip_index": i,
                "clip_start": round(start, 2),
                "clip_end": round(end, 2),
                "duration": round(clip_meta.duration, 2),
                "width": clip_meta.width,
                "height": clip_meta.height,
                "fps": clip_meta.fps,
                "codec": clip_meta.codec,
                "bitrate": clip_meta.bitrate,
                "file_size": clip_meta.file_size,
                "max_available_height": info.max_height,
                "downloaded_height": info.downloaded_height,
                "content_hash": clip_hash,
                "has_audio": clip_meta.has_audio,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": status,
            })

            print(f"  Window {i} [{start:.0f}s-{end:.0f}s]: kept ({final_name})")

        label = "Staged" if self.skip_filter else "Validated"
        print(f"  {label}: {kept}/{scanned} windows scanned (quota={quota})")
        self.processed_ids.add(video_id)

        self._cleanup_source(source_path, video_id)

        return kept

    def _filter_window(self, source_path: Path, start: float, end: float) -> dict:
        """Run JoyCaption content filtering on a time window of the source video.

        Lazy-loads the JoyCaption model on first call.
        """
        from .content_filter import JoyCaptionModel, filter_window

        if self._filter_model is None:
            self._filter_model = JoyCaptionModel.get()

        return filter_window(source_path, start, end, self._filter_model)

    def _cleanup_source(self, source_path: Path, video_id: str):
        """Remove source video and its info json after processing."""
        if source_path and source_path.exists():
            source_path.unlink()
        # yt-dlp writes .info.json alongside
        info_json = source_path.with_suffix(".info.json") if source_path else None
        if info_json and info_json.exists():
            info_json.unlink()

    def process_video_ids(self, video_ids: list[str]) -> int:
        """Process a list of video IDs. Returns total validated clips."""
        total = 0
        for i, vid in enumerate(video_ids):
            print(f"\n[{i+1}/{len(video_ids)}]", end="")
            total += self.process_video(vid)
        return total

    def print_stats(self):
        """Print pipeline statistics."""
        print(f"\n{'=' * 60}")
        print(f"Video Pipeline Results ({self.source})")
        print(f"{'=' * 60}")
        for key, value in self.stats.items():
            label = key.replace("_", " ").title()
            print(f"  {label + ':':<35} {value}")

        # Count staging and validated files
        staging_count = len(list(self.staging_dir.glob("*.*")))
        validated_count = len(list(self.validated_dir.glob("*.*")))
        print(f"  {'Total in staging:':<35} {staging_count}")
        print(f"  {'Total validated:':<35} {validated_count}")
        print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="Video curation pipeline")
    parser.add_argument("--source", default="youtube", help="Source platform")
    parser.add_argument("--output", default="data/videos/real", help="Output base dir")
    parser.add_argument("--max-height", type=int, default=1080, help="Max download resolution")
    parser.add_argument("--force", action="store_true", help="Ignore manifest, fresh start")

    # Input modes (mutually exclusive)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video-id", help="Single YouTube video ID")
    group.add_argument("--id-file", help="File with video IDs (one per line)")
    group.add_argument("--channel", help="YouTube channel URL")
    group.add_argument("--playlist", help="YouTube playlist URL")
    group.add_argument("--search", help="YouTube search query")

    parser.add_argument("--max-videos", type=int, default=50,
                        help="Max videos to process (for channel/playlist/search)")
    parser.add_argument("--skip-filter", action="store_true",
                        help="Skip JoyCaption content filtering (clips stay in staging/)")
    parser.add_argument("--gpu", default="6", help="GPU for JoyCaption (default: 6)")

    args = parser.parse_args()

    pipeline = VideoPipeline(
        source=args.source,
        output_base=args.output,
        max_height=args.max_height,
        force=args.force,
        skip_filter=args.skip_filter,
        gpu=args.gpu,
    )

    # Collect video IDs
    if args.video_id:
        video_ids = [args.video_id]
    elif args.id_file:
        with open(args.id_file) as f:
            video_ids = [line.strip() for line in f if line.strip()
                         and not line.startswith("#")]
    elif args.channel:
        print(f"Listing videos from channel: {args.channel}")
        video_ids = list_channel_videos(args.channel, args.max_videos)
        print(f"Found {len(video_ids)} videos")
    elif args.playlist:
        print(f"Listing videos from playlist: {args.playlist}")
        video_ids = list_playlist_videos(args.playlist, args.max_videos)
        print(f"Found {len(video_ids)} videos")
    elif args.search:
        print(f"Searching YouTube for: {args.search}")
        video_ids = search_videos(args.search, args.max_videos)
        print(f"Found {len(video_ids)} videos")

    if not video_ids:
        print("No video IDs to process.")
        sys.exit(0)

    # Process
    total = pipeline.process_video_ids(video_ids)
    pipeline.print_stats()
    print(f"\nTotal validated clips: {total}")


if __name__ == "__main__":
    main()
