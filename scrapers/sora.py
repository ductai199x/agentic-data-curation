"""Sora (sora.chatgpt.com) scraper for AI-generated videos and images.

Sora is shutting down April 26, 2026. This scraper archives content from
the authenticated feed API before the deadline.

Uses curl_cffi with Chrome TLS impersonation to bypass Cloudflare. This is
necessary because cf_clearance cookies are TLS-fingerprint-bound.

API endpoints (discovered via JS bundle analysis):
  - /backend/public/feed           — public curated feed (no auth, ~46 items)
  - /backend/public/feed/{variant} — single-item unfurl (home, recent)
  - /backend/generations/{id}      — generation detail (needs bearer token)
  - /backend/generations/{id}/download — download URL (needs bearer token)
  - /backend/feed/videos?limit=24  — authenticated paginated feed (needs sentinel PoW)

The authenticated feed (/backend/feed/*) requires:
  - Bearer token from /api/auth/session
  - Sentinel PoW token (browser-generated, saved in data/sora/sentinel_token.json)
  - oai-device-id header

Feed variants: videos, images, featured, recent, ranked
Pagination via ?limit=24&after=CURSOR (URL-encoded cursor from response)

Downloads both videos (.mp4) and images (.png/.webp).

Feed variants (by depth of pagination):
  - recent:   1200+ items, possibly unlimited (deepest pagination)
  - featured: ~800 items
  - images:   ~233 items
  - ranked:   ~235 items
  - videos:   ~127 items
  - all:      scrape all variants sequentially (default, recommended)

Usage:
    uv run python -m scrapers.sora --max-videos 5000
    uv run python -m scrapers.sora --feed recent --max-videos 10000
    uv run python -m scrapers.sora --config configs/sora.py --max-videos 100
    uv run python -m scrapers.sora --feed images --max-videos 1000
    uv run python -m scrapers.sora --force
"""

import argparse
import asyncio
import csv
import http.cookiejar
import json
import random
import signal
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from scrapers.base import BaseScraper, content_hash

# Feed variants supported by the authenticated API
# Order matters: "recent" has the deepest pagination (1200+ items, possibly unlimited),
# "featured" has ~800, others are smaller. "all" scrapes all variants sequentially.
FEED_VARIANTS = ("recent", "featured", "images", "ranked", "videos")
FEED_VARIANT_ORDER = ("recent", "featured", "images", "ranked", "videos")


class SoraScraper(BaseScraper):
    source_name = "sora"

    def __init__(
        self,
        config=None,
        max_items: int = 5000,
        force: bool = False,
        feed_variant: str = "all",
    ):
        output_dir = f"data/images/{config.NAME}" if config else "data/images/sora"
        super().__init__(output_dir, max_items, min_pixels=0, force=force)
        self.config = config
        self.feed_variant = feed_variant

        self.cookies_path = Path(
            getattr(config, "SORA_COOKIES_PATH", "data/cookies/cookies-sora.txt")
            if config else "data/cookies/cookies-sora.txt"
        )

        # Sentinel token file (user provides this from browser DevTools)
        self.sentinel_token_path = Path(output_dir) / "sentinel_token.json"

        self.api_delay = getattr(config, "API_DELAY", (3.0, 5.0)) if config else (3.0, 5.0)
        self.download_delay = getattr(config, "DOWNLOAD_DELAY", (2.0, 3.0)) if config else (2.0, 3.0)

        # Track downloaded post_ids for resume
        self._downloaded_post_ids: set[str] = set()
        if not force:
            self._load_post_ids()

        # Metadata file for extra fields (prompt, caption, creator, duration, likes)
        self.metadata_path = Path(output_dir) / "sora_metadata.jsonl"

        # Cursor persistence for resumable pagination
        self.cursor_path = Path(output_dir) / "feed_cursors.json"
        self._cursors: dict[str, str | None] = {}
        self._exhausted_variants: set[str] = set()
        if not force:
            self._load_cursors()

        # Video-aware stats
        self.stats["downloaded_videos"] = 0
        self.stats["downloaded_images"] = 0
        self.stats["sentinel_expired"] = 0

        # curl_cffi session (initialized in run_async)
        self._session = None
        self._access_token: str | None = None
        self._sentinel_token: dict | None = None
        self._device_id: str | None = None

    def _load_post_ids(self):
        """Load already-downloaded post_ids from manifest for fast skipping."""
        if not self.manifest_path.exists():
            return
        with open(self.manifest_path) as f:
            for row in csv.DictReader(f):
                pid = row.get("post_id", "")
                if pid:
                    self._downloaded_post_ids.add(pid)
        if self._downloaded_post_ids:
            print(f"Loaded {len(self._downloaded_post_ids)} post_ids for resume")

    def _load_cursors(self):
        """Load saved feed cursors and exhausted variant list for resume."""
        if self.cursor_path.exists():
            try:
                data = json.loads(self.cursor_path.read_text())
                self._cursors = data.get("cursors", {})
                self._exhausted_variants = set(data.get("exhausted", []))
                if self._cursors:
                    print(f"Loaded cursors for variants: {list(self._cursors.keys())}")
                if self._exhausted_variants:
                    print(f"Previously exhausted variants: {self._exhausted_variants}")
            except Exception as e:
                print(f"Failed to load cursors: {e}")

    def _save_cursors(self):
        """Persist current feed cursors to disk for resume."""
        data = {
            "cursors": self._cursors,
            "exhausted": list(self._exhausted_variants),
        }
        self.cursor_path.write_text(json.dumps(data, indent=2))

    def _init_session(self):
        """Initialize curl_cffi session with Chrome TLS impersonation and cookies."""
        from curl_cffi import requests as cffi_requests

        self._session = cffi_requests.Session(impersonate="chrome131")

        # Load cookies — try Netscape format first, then raw cookie string
        if self.cookies_path.exists():
            cookies_text = self.cookies_path.read_text().strip()
            if cookies_text.startswith("#") or "\t" in cookies_text.split("\n")[0]:
                # Netscape-format cookie jar
                try:
                    cj = http.cookiejar.MozillaCookieJar(str(self.cookies_path))
                    cj.load(ignore_discard=True, ignore_expires=True)
                    count = 0
                    for cookie in cj:
                        self._session.cookies.set(
                            cookie.name, cookie.value,
                            domain=cookie.domain, path=cookie.path,
                        )
                        count += 1
                    print(f"Loaded {count} cookies (Netscape) from {self.cookies_path}", flush=True)
                except Exception as e:
                    print(f"Failed to load Netscape cookies: {e}", flush=True)
            else:
                # Raw cookie string: "name1=value1; name2=value2; ..."
                count = 0
                for pair in cookies_text.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        name, value = pair.split("=", 1)
                        self._session.cookies.set(
                            name.strip(), value.strip(),
                            domain=".chatgpt.com",
                        )
                        count += 1
                        # Extract device ID from oai-did cookie
                        if name.strip() == "oai-did":
                            self._device_id = value.strip()
                print(f"Loaded {count} cookies (raw string) from {self.cookies_path}", flush=True)
        else:
            print(f"No cookies file at {self.cookies_path}", flush=True)

        # Load sentinel token
        self._load_sentinel_token()

    def _get_access_token(self) -> str | None:
        """Get bearer token from ChatGPT session endpoint."""
        if self._access_token:
            return self._access_token

        try:
            resp = self._session.get(
                "https://sora.chatgpt.com/api/auth/session",
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                token = data.get("accessToken", "")
                if token:
                    self._access_token = token
                    user = data.get("user", {})
                    print(f"Authenticated as: {user.get('name', 'unknown')}", flush=True)
                    return token
        except Exception as e:
            print(f"Failed to get access token: {e}", flush=True)

        return None

    def _load_sentinel_token(self):
        """Load sentinel PoW token from file."""
        if self.sentinel_token_path.exists():
            try:
                self._sentinel_token = json.loads(self.sentinel_token_path.read_text())
                # Extract device ID from sentinel token if not already set
                if not self._device_id and self._sentinel_token.get("id"):
                    self._device_id = self._sentinel_token["id"]
                print(f"Loaded sentinel token from {self.sentinel_token_path}", flush=True)
                print(f"  Device ID: {self._device_id}", flush=True)
            except Exception as e:
                print(f"Failed to load sentinel token: {e}", flush=True)
                self._sentinel_token = None
        else:
            print(f"No sentinel token at {self.sentinel_token_path}", flush=True)
            print("  To use the authenticated feed, save the sentinel token JSON to this file.", flush=True)
            self._sentinel_token = None

    def _get_auth_headers(self) -> dict:
        """Build the full set of authenticated headers for the feed API."""
        headers = {}

        token = self._get_access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if self._sentinel_token:
            headers["openai-sentinel-token"] = json.dumps(self._sentinel_token)

        if self._device_id:
            headers["oai-device-id"] = self._device_id

        headers["oai-language"] = "en-US"

        return headers

    def _fetch_authenticated_feed(self, variant: str = "videos", limit: int = 24) -> list[dict]:
        """Fetch items from the authenticated paginated feed.

        Paginates through /backend/feed/{variant}?limit={limit}&after={cursor}
        until no more items or max_items reached.

        Supports resume via saved cursors: if a cursor was persisted from a
        previous run, pagination continues from where it left off.

        Returns a deduplicated list of generation dicts.
        """
        headers = self._get_auth_headers()
        if "Authorization" not in headers or "openai-sentinel-token" not in headers:
            print("Cannot use authenticated feed: missing bearer token or sentinel token", flush=True)
            return []

        # Skip if this variant was previously exhausted
        if variant in self._exhausted_variants:
            print(f"  /feed/{variant}: previously exhausted, skipping", flush=True)
            return []

        all_items: dict[str, dict] = {}  # id -> item (dedup)
        # Resume from saved cursor if available
        cursor: str | None = self._cursors.get(variant)
        if cursor:
            print(f"  /feed/{variant}: resuming from saved cursor", flush=True)
        page = 0
        stale_pages = 0
        consecutive_errors = 0

        while True:
            if self._should_stop:
                break

            # Build URL
            url = f"https://sora.chatgpt.com/backend/feed/{variant}?limit={limit}"
            if cursor:
                url += f"&after={urllib.parse.quote(cursor, safe='')}"

            page += 1
            try:
                resp = self._session.get(url, headers=headers, timeout=30)

                if resp.status_code == 400 or resp.status_code == 401 or resp.status_code == 403:
                    self.stats["sentinel_expired"] += 1
                    print(f"\n{'='*60}", flush=True)
                    print("SENTINEL TOKEN EXPIRED or INVALID", flush=True)
                    print(f"HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
                    print(f"\nPlease refresh the sentinel token:", flush=True)
                    print(f"  1. Open sora.chatgpt.com in your browser", flush=True)
                    print(f"  2. Open DevTools > Network tab", flush=True)
                    print(f"  3. Browse the feed to trigger a /backend/feed/ request", flush=True)
                    print(f"  4. Copy the 'openai-sentinel-token' request header value", flush=True)
                    print(f"  5. Save it to: {self.sentinel_token_path}", flush=True)
                    print(f"  6. Re-run the scraper", flush=True)
                    print(f"{'='*60}", flush=True)
                    break

                if resp.status_code == 429:
                    wait = random.uniform(30, 60)
                    print(f"  Rate limited (429), waiting {wait:.0f}s...", flush=True)
                    time.sleep(wait)
                    continue

                if resp.status_code != 200:
                    consecutive_errors += 1
                    print(f"  /feed/{variant} page {page}: HTTP {resp.status_code}", flush=True)
                    if consecutive_errors >= 3:
                        print(f"  /feed/{variant}: {consecutive_errors} consecutive errors, stopping", flush=True)
                        break
                    time.sleep(random.uniform(5, 10))
                    continue

                consecutive_errors = 0
                data = resp.json()
                feed_items = data.get("data", [])

                if not isinstance(feed_items, list) or len(feed_items) == 0:
                    print(f"  /feed/{variant} page {page}: empty (end of feed)", flush=True)
                    self._exhausted_variants.add(variant)
                    break

                new_count = 0
                for item in feed_items:
                    gen_id = item.get("id", "")
                    if gen_id and gen_id not in all_items:
                        all_items[gen_id] = item
                        new_count += 1

                print(f"  /feed/{variant} page {page}: {len(feed_items)} items (+{new_count} new, {len(all_items)} total)", flush=True)

                if new_count == 0:
                    stale_pages += 1
                    if stale_pages >= 5:
                        print(f"  /feed/{variant}: {stale_pages} consecutive stale pages, done", flush=True)
                        self._exhausted_variants.add(variant)
                        break
                else:
                    stale_pages = 0

                # Build cursor from last item — the format uses the item's rank_id and score
                last_item = feed_items[-1]
                last_id = last_item.get("id", "")
                rank_fields = last_item.get("rank_fields", {})
                if isinstance(rank_fields, dict) and rank_fields.get("cursor"):
                    cursor = rank_fields["cursor"]
                elif isinstance(rank_fields, dict):
                    # Try to reconstruct cursor from rank_id and score
                    rank_id = rank_fields.get("rank_id", "")
                    score = rank_fields.get("score", 0)
                    if rank_id:
                        cursor = f"rf:{rank_id}:{score}"
                    else:
                        cursor = None
                else:
                    cursor = None

                # If we couldn't extract a cursor, look for it in the response metadata
                if cursor is None:
                    next_cursor = data.get("last_id") or data.get("next_cursor") or data.get("cursor") or data.get("after")
                    if next_cursor:
                        cursor = next_cursor
                    else:
                        print(f"  /feed/{variant}: no cursor found, stopping pagination", flush=True)
                        break

                # Save cursor for resume after every page
                self._cursors[variant] = cursor
                if page % 5 == 0:
                    self._save_cursors()

                # Check has_more flag from response
                if data.get("has_more") is False:
                    print(f"  /feed/{variant}: has_more=false, done ({len(all_items)} items)", flush=True)
                    self._exhausted_variants.add(variant)
                    break

                # Check if we have enough items
                if len(all_items) >= self.max_images + len(self._downloaded_post_ids):
                    print(f"  /feed/{variant}: collected enough items ({len(all_items)})", flush=True)
                    break

                # Rate limit between API pages
                delay = random.uniform(*self.api_delay)
                time.sleep(delay)

            except json.JSONDecodeError as e:
                print(f"  /feed/{variant} page {page}: JSON decode error: {e}", flush=True)
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                time.sleep(random.uniform(5, 10))
            except Exception as e:
                print(f"  /feed/{variant} page {page}: error: {e}", flush=True)
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                time.sleep(random.uniform(5, 10))

        # Save final cursor state
        self._save_cursors()
        return list(all_items.values())

    def _append_sora_metadata(self, meta: dict):
        """Append extra Sora metadata to sora_metadata.jsonl."""
        with open(self.metadata_path, "a") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    async def run_async(self):
        """Main scraping loop: async producer/consumer pipeline.

        Producer paginates through feed variants, enqueuing items.
        Consumers download videos/images in parallel (4 workers).
        """
        self._setup_signals()

        # Initialize HTTP session
        self._init_session()

        # Get auth token
        self._get_access_token()

        # Create subdirectories for videos and images
        (self.staging_dir / "videos").mkdir(parents=True, exist_ok=True)
        (self.staging_dir / "images").mkdir(parents=True, exist_ok=True)

        n_workers = 4
        self._pbar = tqdm(desc="Sora", unit="item", file=sys.stderr)
        self._processed = 0
        self._seen_ids: set[str] = set(self._downloaded_post_ids)

        item_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        producer = self._produce_items(item_queue)
        consumers = [
            self._consume_items(item_queue, worker_id=i)
            for i in range(n_workers)
        ]
        await asyncio.gather(producer, *consumers)
        self._pbar.close()
        self._save_cursors()
        self.print_stats()

    async def _produce_items(self, item_queue: asyncio.Queue):
        """Paginate through feed variants and enqueue items for download."""
        variants = FEED_VARIANT_ORDER if self.feed_variant == "all" else (self.feed_variant,)

        for variant in variants:
            if self._should_stop or self.done:
                break
            print(f"\nScraping /feed/{variant}...", flush=True)
            await self._paginate_feed(variant, item_queue)

        # Fall back to public feed if nothing was found
        if self.stats.get("downloaded", 0) == 0 and not self._sentinel_token:
            print("\nFalling back to public feed...", flush=True)
            items = self._fetch_public_feed()
            for item in items:
                if self._should_stop or self.done:
                    break
                gen_id = item.get("id", "")
                if gen_id and gen_id not in self._seen_ids:
                    self._seen_ids.add(gen_id)
                    await item_queue.put(item)

        # Signal consumers to stop
        for _ in range(4):
            await item_queue.put(None)

    async def _paginate_feed(self, variant: str, item_queue: asyncio.Queue):
        """Paginate a single feed variant, enqueuing new items immediately."""
        headers = self._get_auth_headers()
        if "Authorization" not in headers or "openai-sentinel-token" not in headers:
            print("  Missing auth headers, skipping", flush=True)
            return

        if variant in self._exhausted_variants:
            print(f"  /feed/{variant}: previously exhausted, skipping", flush=True)
            return

        cursor: str | None = self._cursors.get(variant)
        if cursor:
            print(f"  /feed/{variant}: resuming from saved cursor", flush=True)
        page = 0
        stale_pages = 0
        consecutive_errors = 0
        total_new = 0

        while not self._should_stop and not self.done:
            import urllib.parse
            url = f"https://sora.chatgpt.com/backend/feed/{variant}?limit=24"
            if cursor:
                url += f"&after={urllib.parse.quote(cursor)}"

            try:
                resp = await asyncio.to_thread(
                    self._session.get, url, headers=headers, timeout=30
                )
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    print(f"  /feed/{variant}: {consecutive_errors} errors, stopping", flush=True)
                    break
                await asyncio.sleep(random.uniform(5, 10))
                continue

            if resp.status_code == 429:
                wait = random.uniform(30, 60)
                print(f"  Rate limited, waiting {wait:.0f}s...", flush=True)
                await asyncio.sleep(wait)
                continue

            if resp.status_code != 200:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    break
                await asyncio.sleep(random.uniform(5, 10))
                continue

            consecutive_errors = 0
            data = resp.json()
            feed_items = data.get("data", [])

            if not feed_items:
                self._exhausted_variants.add(variant)
                break

            page += 1
            new_count = 0
            for item in feed_items:
                gen_id = item.get("id", "")
                if gen_id and gen_id not in self._seen_ids:
                    self._seen_ids.add(gen_id)
                    new_count += 1
                    await item_queue.put(item)

            total_new += new_count

            if new_count == 0:
                stale_pages += 1
                if stale_pages >= 5:
                    break
            else:
                stale_pages = 0

            if page % 10 == 0:
                print(f"  /feed/{variant} page {page}: +{total_new} new items enqueued", flush=True)

            # Save cursor periodically
            cursor = data.get("last_id")
            if cursor:
                self._cursors[variant] = cursor
                if page % 5 == 0:
                    self._save_cursors()

            if not cursor or data.get("has_more") is False:
                self._exhausted_variants.add(variant)
                break

            await asyncio.sleep(random.uniform(5, 10))

        print(f"  /feed/{variant}: {page} pages, {total_new} new items", flush=True)
        self._save_cursors()

    async def _consume_items(self, item_queue: asyncio.Queue, worker_id: int = 0):
        """Pull items from queue and download each."""
        while True:
            try:
                item = await asyncio.wait_for(item_queue.get(), timeout=120)
            except asyncio.TimeoutError:
                # Queue empty for 2 min — producer is probably done
                print(f"  Consumer {worker_id}: timed out waiting, exiting", flush=True)
                break

            if item is None:
                item_queue.task_done()
                break

            try:
                success = await asyncio.wait_for(
                    asyncio.to_thread(self._download_item, item),
                    timeout=300,  # 5 min max per download
                )
            except asyncio.TimeoutError:
                print(f"  Consumer {worker_id}: download timed out, skipping", flush=True)
                self.stats["failed"] += 1
                success = False

            self._processed += 1
            self._pbar.n = self._processed
            self._pbar.set_postfix(
                dl=self.stats["downloaded"],
                fail=self.stats["failed"],
                vid=self.stats["downloaded_videos"],
                img=self.stats["downloaded_images"],
            )
            self._pbar.refresh()
            item_queue.task_done()

            if self._should_stop or self.done:
                break

            if success:
                await asyncio.sleep(random.uniform(1, 3))

        # Worker 0 drains remaining
        if worker_id == 0:
            while not item_queue.empty():
                try:
                    item_queue.get_nowait()
                    item_queue.task_done()
                except asyncio.QueueEmpty:
                    break

    def _download_item(self, item: dict) -> bool:
        """Download a single item (video or image). Returns True on success."""
        gen_id = item.get("id", "")
        task_type = item.get("task_type", "unknown")
        is_video = task_type == "video_gen"

        if gen_id in self._downloaded_post_ids:
            return False

        source_url = self._get_source_url(item)
        if not source_url:
            self.stats["failed"] += 1
            return False

        data = self._download_media(source_url)
        if data is None:
            self.stats["failed"] += 1
            return False

        file_hash = content_hash(data)
        if file_hash in self.downloaded_hashes:
            self.stats["skipped_duplicate_hash"] += 1
            return False

        ext = self._detect_extension_from_data(data, source_url)
        is_video = ext == ".mp4"

        filename = f"{file_hash[:16]}{ext}"
        subdir = "videos" if is_video else "images"
        filepath = self.staging_dir / subdir / filename
        filepath.write_bytes(data)

        # Extract metadata
        width = item.get("width", 0)
        height = item.get("height", 0)
        prompt = item.get("prompt", "") or ""
        title = item.get("title", "") or ""
        user = item.get("user", {}) or {}
        creator = user.get("username", "") if isinstance(user, dict) else ""
        like_count = item.get("like_count", 0)
        created_at = item.get("created_at", "")
        n_frames = item.get("n_frames", 0)
        model = item.get("model", "")
        quality = item.get("quality", "")
        flair = f"sora:{task_type}" if task_type else "sora"
        duration = None
        enc = item.get("encodings", {})
        if isinstance(enc, dict):
            src_enc = enc.get("source", {})
            if isinstance(src_enc, dict):
                duration = src_enc.get("duration_secs")

        self.downloaded_urls.add(source_url)
        self.downloaded_hashes.add(file_hash)
        self._downloaded_post_ids.add(gen_id)
        self.stats["downloaded"] += 1
        if is_video:
            self.stats["downloaded_videos"] += 1
        else:
            self.stats["downloaded_images"] += 1

        self._append_manifest({
            "filename": filename,
            "url": source_url,
            "content_hash": file_hash,
            "source": "sora",
            "subreddit": "",
            "post_id": gen_id,
            "post_title": (prompt or title)[:200],
            "flair": flair,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "downloaded",
            "width": width,
            "height": height,
            "format": ext.replace(".", "").upper(),
            "file_size": len(data),
            "message_content": "",
            "is_upscaled": "",
            "post_date": created_at,
        })

        self._append_sora_metadata({
            "id": gen_id, "filename": filename, "task_type": task_type,
            "prompt": prompt, "title": title, "creator": creator,
            "width": width, "height": height, "n_frames": n_frames,
            "duration": duration, "model": model, "quality": quality,
            "like_count": like_count, "created_at": created_at,
        })
        return True

    def _old_run_async_fallback(self):
        """Placeholder for removed sequential code."""
        pass

    # Old sequential download code removed — replaced by _download_item + consumer pattern

    def _fetch_public_feed(self) -> list[dict]:
        """Fetch all items from the public curated feed.

        Returns a deduplicated list of generation dicts.
        The public feed currently returns ~46 curated items and does not
        support pagination (after= cursor is ignored).
        """
        items: dict[str, dict] = {}  # id -> item (dedup)

        # Main public feed (returns list in data field)
        try:
            resp = self._session.get(
                "https://sora.chatgpt.com/backend/public/feed?limit=100",
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                feed_items = data.get("data", [])
                if isinstance(feed_items, list):
                    for item in feed_items:
                        gen_id = item.get("id", "")
                        if gen_id:
                            items[gen_id] = item
                    print(f"  /public/feed: {len(feed_items)} items", flush=True)
                elif isinstance(feed_items, dict) and feed_items.get("id"):
                    # Single item response
                    items[feed_items["id"]] = feed_items
            else:
                print(f"  /public/feed: HTTP {resp.status_code}", flush=True)
        except Exception as e:
            print(f"  /public/feed failed: {e}", flush=True)

        # Also try variant unfurl endpoints for extra items
        for variant in ["home", "recent"]:
            try:
                await_delay = random.uniform(*self.api_delay)
                time.sleep(await_delay)
                resp = self._session.get(
                    f"https://sora.chatgpt.com/backend/public/feed/{variant}?limit=100",
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # These return a single item dict (unfurl)
                    if isinstance(data, dict) and data.get("id"):
                        gen_id = data["id"]
                        if gen_id not in items:
                            items[gen_id] = data
                            print(f"  /public/feed/{variant}: +1 new item", flush=True)
            except Exception as e:
                print(f"  /public/feed/{variant} failed: {e}", flush=True)

        return list(items.values())

    def _get_download_url(self, gen_id: str, headers: dict) -> str | None:
        """Get the download URL for a generation via the download endpoint.

        This returns the original source file (PNG for images, MP4 for videos)
        which is higher quality than the WebP encoding in the feed.
        """
        if not headers:
            return None

        try:
            resp = self._session.get(
                f"https://sora.chatgpt.com/backend/generations/{gen_id}/download",
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("url")
        except Exception:
            pass

        return None

    @staticmethod
    def _get_source_url(item: dict) -> str | None:
        """Extract the source media URL from a feed item's encodings."""
        enc = item.get("encodings", {})
        if isinstance(enc, dict):
            # Prefer source encoding (highest quality)
            source = enc.get("source", {})
            if isinstance(source, dict) and source.get("path"):
                return source["path"]
            # Fall back to md (medium) encoding for videos
            md = enc.get("md", {})
            if isinstance(md, dict) and md.get("path"):
                return md["path"]

        # Direct URL field
        url = item.get("url", "")
        if url and "videos.openai.com" in url:
            return url

        return None

    def _download_media(self, url: str) -> bytes | None:
        """Download media from a URL using the curl_cffi session."""
        try:
            resp = self._session.get(url, timeout=120)
            if resp.status_code == 200:
                data = resp.content
                if len(data) < 100:
                    print(f"  Download too small ({len(data)} bytes), skipping", flush=True)
                    return None
                return data
            else:
                print(f"  Download HTTP {resp.status_code}", flush=True)
                return None
        except Exception as e:
            print(f"  Download failed: {e}", flush=True)
            return None

    @staticmethod
    def _detect_extension_from_data(data: bytes, url: str) -> str:
        """Detect file extension from magic bytes and URL."""
        if len(data) >= 12:
            if data[:4] == b'\x89PNG':
                return ".png"
            if data[:2] == b'\xff\xd8':
                return ".jpg"
            if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                return ".webp"
            if data[4:8] == b'ftyp':
                return ".mp4"

        # Fallback to URL
        url_lower = url.lower().split("?")[0]
        if url_lower.endswith(".png"):
            return ".png"
        if url_lower.endswith(".webp"):
            return ".webp"
        if url_lower.endswith(".mp4"):
            return ".mp4"

        return ".jpg"


def main():
    parser = argparse.ArgumentParser(description="Scrape Sora (sora.chatgpt.com) videos and images")
    parser.add_argument("--config", "-c", help="Config file path (default: configs/sora.py)")
    parser.add_argument("--max-videos", "-n", type=int, default=5000,
                        help="Max items to download (videos + images)")
    parser.add_argument("--feed", "-f", choices=[*FEED_VARIANTS, "all"], default="all",
                        help="Feed variant to scrape, or 'all' for all variants (default: all)")
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest (fresh start)")
    args = parser.parse_args()

    config = None
    if args.config:
        from configs import load_config
        config = load_config(args.config)
    else:
        from configs import load_config
        default_config = Path(__file__).parent.parent / "configs" / "sora.py"
        if default_config.exists():
            config = load_config(str(default_config))

    scraper = SoraScraper(
        config=config,
        max_items=args.max_videos,
        force=args.force,
        feed_variant=args.feed,
    )
    scraper.run()


if __name__ == "__main__":
    main()
