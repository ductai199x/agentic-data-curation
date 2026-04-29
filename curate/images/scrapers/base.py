"""Shared scraper infrastructure.

All scrapers inherit from BaseScraper, which provides:
- Content-addressed storage (SHA-256[:16] filename)
- Manifest-based resume (skip already-downloaded URLs/hashes)
- Async producer/consumer pattern with graceful shutdown
- Image pre-filtering (pixel count, format)
"""

import asyncio
import csv
import hashlib
import random
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image
from tqdm import tqdm

# Sentinel for queue completion signaling
_DONE = None

MANIFEST_FIELDS = [
    "filename", "url", "content_hash", "source", "subreddit",
    "post_id", "post_title", "flair", "timestamp", "status",
    "width", "height", "format", "file_size",
    "message_content", "is_upscaled", "post_date",
]


def content_hash(data: bytes) -> str:
    """Return SHA-256 hex digest of image data."""
    return hashlib.sha256(data).hexdigest()


class BaseScraper:
    """Base class for all image scrapers.

    Subclasses implement run_async() with producer/consumer tasks.
    Signal handling (SIGINT/SIGTERM) is provided by _setup_signals().
    """

    source_name: str = "unknown"  # override in subclass

    def __init__(self, output_dir: str | Path, max_images: int, min_pixels: int = 200_000,
                 force: bool = False):
        self.output_dir = Path(output_dir)
        self.staging_dir = self.output_dir / "staging"
        self.max_images = max_images
        self.min_pixels = min_pixels

        self.staging_dir.mkdir(parents=True, exist_ok=True)

        self.manifest_path = self.output_dir / "manifest.csv"
        self.downloaded_urls: set[str] = set()
        self.downloaded_hashes: set[str] = set()
        if not force:
            self._load_manifest()
        else:
            print("Force mode: ignoring existing manifest (fresh start)")

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "DataCuration/1.0 (research; image dataset collection)",
        })

        self.stats: dict[str, int] = {
            "downloaded": 0,
            "skipped_duplicate_url": 0,
            "skipped_duplicate_hash": 0,
            "skipped_too_small": 0,
            "skipped_video": 0,
            "failed": 0,
        }

    # ── Lifecycle ──────────────────────────────────────────────────

    @property
    def done(self) -> bool:
        """True if we've hit the download target."""
        return self.stats["downloaded"] >= self.max_images

    @property
    def _should_stop(self) -> bool:
        """True if target reached or shutdown signal received."""
        return self.done or (hasattr(self, '_shutdown') and self._shutdown.is_set())

    def _handle_shutdown(self):
        """Signal handler — set shutdown flag for graceful stop."""
        if not self._shutdown.is_set():
            tqdm.write("\n⚠ Shutdown signal received — finishing current downloads...")
            self._shutdown.set()

    def _setup_signals(self):
        """Install SIGINT/SIGTERM handlers. Call at start of run_async()."""
        self._shutdown = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown)

    def run(self):
        """Sync entry point — wraps run_async()."""
        asyncio.run(self.run_async())

    async def run_async(self):
        """Override in subclass with async producer/consumer logic."""
        raise NotImplementedError("Subclass must implement run_async()")

    # ── Manifest ───────────────────────────────────────────────────

    def _load_manifest(self):
        """Load previously downloaded URLs and hashes from manifest."""
        if not self.manifest_path.exists():
            return
        with open(self.manifest_path) as f:
            for row in csv.DictReader(f):
                self.downloaded_urls.add(row["url"])
                if row.get("content_hash"):
                    self.downloaded_hashes.add(row["content_hash"])
        print(f"Loaded {len(self.downloaded_urls)} previously downloaded URLs")

    def _append_manifest(self, row: dict):
        """Append a row to the manifest CSV."""
        write_header = not self.manifest_path.exists()
        with open(self.manifest_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    # ── Download ───────────────────────────────────────────────────

    def download_image(self, url: str, source: str = "", metadata: dict | None = None) -> bool:
        """Download image, dedup, pre-filter, save to staging.

        Args:
            url: Image URL to download
            source: Source identifier (e.g. "reddit", "civitai", "twitter")
            metadata: Extra metadata dict (subreddit, post_id, post_title, flair)

        Returns:
            True if image was downloaded and saved, False if skipped/failed.
        """
        metadata = metadata or {}
        source = source or self.source_name

        if url in self.downloaded_urls:
            self.stats["skipped_duplicate_url"] += 1
            return False

        try:
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            data = resp.content

            img_hash = content_hash(data)
            if img_hash in self.downloaded_hashes:
                self.stats["skipped_duplicate_hash"] += 1
                return False

            # Determine extension from content type or URL
            ext = self._detect_extension(url, resp.headers.get("content-type", ""))

            filename = f"{img_hash[:16]}{ext}"
            filepath = self.staging_dir / filename
            filepath.write_bytes(data)

            # Get image dimensions
            try:
                img = Image.open(filepath)
                width, height = img.size
                fmt = img.format or "UNKNOWN"
            except Exception:
                width, height, fmt = 0, 0, "UNKNOWN"

            # Pre-filter tiny images
            pixels = width * height
            if pixels > 0 and pixels < self.min_pixels:
                filepath.unlink()
                self.stats["skipped_too_small"] += 1
                return False

            self.downloaded_urls.add(url)
            self.downloaded_hashes.add(img_hash)
            self.stats["downloaded"] += 1

            self._append_manifest({
                "filename": filename,
                "url": url,
                "content_hash": img_hash,
                "source": source,
                "subreddit": metadata.get("subreddit", ""),
                "post_id": metadata.get("post_id", ""),
                "post_title": str(metadata.get("post_title", ""))[:200],
                "flair": metadata.get("flair", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "downloaded",
                "width": width,
                "height": height,
                "format": fmt,
                "file_size": len(data),
                "message_content": metadata.get("message_content", ""),
                "is_upscaled": metadata.get("is_upscaled", ""),
                "post_date": metadata.get("post_date", ""),
            })
            return True

        except Exception as e:
            self.stats["failed"] += 1
            print(f"  Failed: {e}")
            return False

    @staticmethod
    def _detect_extension(url: str, content_type: str) -> str:
        """Guess file extension from URL and content-type header."""
        url_lower = url.lower().split("?")[0]
        ct = content_type.lower()

        if "png" in ct or url_lower.endswith(".png") or "format=png" in url.lower():
            return ".png"
        if "webp" in ct or url_lower.endswith(".webp"):
            return ".webp"
        return ".jpg"

    # ── Reporting ──────────────────────────────────────────────────

    def print_stats(self):
        """Print download statistics."""
        print(f"\n{'=' * 60}")
        print(f"{self.source_name.title()} Scraper Results")
        print(f"{'=' * 60}")
        for key, value in self.stats.items():
            label = key.replace("_", " ").replace("skipped ", "Skipped (").rstrip()
            if key.startswith("skipped_"):
                label = f"Skipped ({key.split('_', 1)[1].replace('_', ' ')})"
            else:
                label = key.replace("_", " ").title()
            print(f"  {label + ':':<30} {value}")
        print(f"{'=' * 60}")
