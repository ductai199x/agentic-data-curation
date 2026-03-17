"""OpenArt.ai scraper for FLUX.1 on-site generations.

OpenArt has a public search API that returns on-site generations filtered by
ai_model. All images tagged "Flux" were generated on OpenArt's own infrastructure
using Black Forest Labs FLUX models — good provenance.

API: GET /api/search?query=&cursor=&method=similarity&ai_model=Flux&apply_filter=true&duration=300
Pagination: cursor-based (nextCursor field, ~50-70 items per page)
Image CDN: cdn.openart.ai/published/... (raw JPG) or cdn.openart.ai/uploads/... (raw JPG)

No authentication required — public API + CDN.

Usage:
    uv run python -m scrapers.openart --config configs/flux1.py --max-images 500
    uv run python -m scrapers.openart --config configs/flux1.py --max-images 100 --force
"""

import argparse
import asyncio
import random
import sys
import time

from tqdm import tqdm

from scrapers.base import BaseScraper, _DONE


API_URL = "https://openart.ai/api/search"

# All FLUX variants on OpenArt use ai_model="Flux"
DEFAULT_AI_MODEL = "Flux"


class OpenArtScraper(BaseScraper):
    """Scrapes FLUX.1 on-site generations from OpenArt.ai."""

    source_name = "openart"

    def __init__(self, config, max_images: int = 500, force: bool = False):
        output_dir = f"data/{config.NAME}"
        super().__init__(
            output_dir, max_images,
            min_pixels=getattr(config, "MIN_PIXELS", 200_000),
            force=force,
        )
        self.config = config
        self.api_delay = getattr(config, "OPENART_API_DELAY", (3.0, 6.0))
        self.download_delay = getattr(config, "OPENART_DOWNLOAD_DELAY", (0.5, 1.5))
        self.download_workers = getattr(config, "OPENART_DOWNLOAD_WORKERS", 4)
        self.ai_model = getattr(config, "OPENART_AI_MODEL", DEFAULT_AI_MODEL)

        self.session.headers.update({
            "Referer": "https://openart.ai/",
            "Accept": "application/json",
        })

        self.stats.update({
            "pages_fetched": 0,
            "urls_found": 0,
        })

    # ── Async producer/consumer ───────────────────────────────────

    async def run_async(self):
        """Run the full OpenArt scraping pipeline with async producer/consumer."""
        self._setup_signals()

        tqdm.write(f"Starting OpenArt scraper (target: {self.max_images}, workers: {self.download_workers})")
        tqdm.write(f"  AI model filter: {self.ai_model}")
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")
        self._pbar = tqdm(desc="OpenArt", unit="img", file=sys.stderr)
        self._processed = 0

        item_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        producer = asyncio.create_task(self._produce_items(item_queue))
        consumers = [
            asyncio.create_task(self._consume_items(item_queue, worker_id=i))
            for i in range(self.download_workers)
        ]
        await producer
        await asyncio.gather(*consumers)
        self._pbar.close()
        self.print_stats()

    async def _produce_items(self, item_queue: asyncio.Queue):
        """Paginate through the OpenArt search API and enqueue items."""
        cursor = ""
        empty_pages = 0

        while not self._should_stop:
            items, next_cursor = await asyncio.to_thread(
                self._fetch_page, cursor,
            )
            self.stats["pages_fetched"] += 1

            if not items:
                empty_pages += 1
                if empty_pages >= 3:
                    tqdm.write("  3 consecutive empty pages — exhausted")
                    break
                await asyncio.sleep(random.uniform(*self.api_delay))
                continue

            empty_pages = 0
            self.stats["urls_found"] += len(items)
            tqdm.write(
                f"  Page {self.stats['pages_fetched']}: "
                f"{len(items)} items (cursor={cursor[:12]}...)"
            )

            for item in items:
                if self._should_stop:
                    break
                await item_queue.put(item)

            if not next_cursor:
                tqdm.write("  No more pages (nextCursor is null)")
                break

            cursor = next_cursor
            await asyncio.sleep(random.uniform(*self.api_delay))

        # Signal consumers to stop
        for _ in range(self.download_workers):
            await item_queue.put(_DONE)

    async def _consume_items(self, item_queue: asyncio.Queue, worker_id: int = 0):
        """Pull items from queue and download each."""
        while True:
            item = await item_queue.get()
            if item is _DONE:
                item_queue.task_done()
                break

            success = await asyncio.to_thread(self._download_item, item)
            self._processed += 1
            self._pbar.n = self._processed
            self._pbar.set_postfix(
                dl=self.stats["downloaded"],
                fail=self.stats["failed"],
                skip=self.stats["skipped_duplicate_url"] + self.stats["skipped_duplicate_hash"],
            )
            self._pbar.refresh()
            item_queue.task_done()

            if self._should_stop:
                break

            if success:
                await asyncio.sleep(random.uniform(*self.download_delay))

        # Worker 0 drains remaining items
        if worker_id == 0:
            while not item_queue.empty():
                try:
                    item_queue.get_nowait()
                    item_queue.task_done()
                except asyncio.QueueEmpty:
                    break

    # ── Sync helpers (called via asyncio.to_thread) ───────────────

    def _fetch_page(self, cursor: str = "") -> tuple[list[dict], str | None]:
        """Fetch a page of items from the OpenArt search API."""
        params = {
            "query": "",
            "cursor": cursor,
            "method": "similarity",
            "ai_model": self.ai_model,
            "ai_tool": "",
            "flow_app": "",
            "apply_filter": "true",
            "duration": "300",
        }

        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.get(API_URL, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"  Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                next_cursor = data.get("nextCursor")
                return items, next_cursor
            except Exception as e:
                wait = (attempt + 1) * 10
                tqdm.write(f"  Error fetching page: {e}, retrying in {wait}s...")
                time.sleep(wait)

        return [], None

    def _get_image_url(self, item: dict) -> str | None:
        """Extract the best (full-resolution) image URL from an item.

        Priority:
        1. image.raw — full-res published image on CDN
        2. image_url — original upload URL
        """
        image = item.get("image", {})
        if isinstance(image, dict):
            raw = image.get("raw")
            if raw:
                return raw
        return item.get("image_url")

    def _download_item(self, item: dict) -> bool:
        """Download a single OpenArt image item."""
        url = self._get_image_url(item)
        if not url:
            self.stats["failed"] += 1
            return False

        # Verify model matches (defensive — API should filter already)
        ai_model = item.get("ai_model", "")
        if ai_model.lower() != self.ai_model.lower():
            return False

        # Extract dimensions from image dict or top-level
        image = item.get("image", {})
        width = item.get("image_width") or (image.get("raw_width") if isinstance(image, dict) else None) or 0
        height = item.get("image_height") or (image.get("raw_height") if isinstance(image, dict) else None) or 0

        metadata = {
            "post_id": item.get("id", ""),
            "post_title": str(item.get("prompt", ""))[:200],
            "flair": f"openart:{ai_model}",
            "subreddit": "",
        }

        return self.download_image(url, source="openart", metadata=metadata)


def main():
    parser = argparse.ArgumentParser(description="Scrape OpenArt.ai FLUX galleries")
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--max-images", "-n", type=int, default=500)
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest")
    args = parser.parse_args()

    from configs import load_config
    config = load_config(args.config)

    scraper = OpenArtScraper(config, max_images=args.max_images, force=args.force)
    scraper.run()


if __name__ == "__main__":
    main()
