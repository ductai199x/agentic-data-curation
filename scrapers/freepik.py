"""Freepik scraper — downloads AI-generated images from Freepik's Stock Content API.

Uses GET /v1/resources with filters[ai-generated][only]=1 to retrieve only
AI-generated stock photos. Cannot filter by specific model (FLUX vs Imagen vs Mystic),
so all AI-generated images are downloaded and tagged with available metadata for
post-download filtering by resolution/aspect-ratio heuristics.

Two-step process:
1. Search: GET /v1/resources — paginated listing with AI-generated filter
2. Download: GET /v1/resources/{id}/download — full-resolution image

Authentication: requires x-freepik-api-key header (free tier: 5 USD credits).
Get key at: https://www.freepik.com/developers/dashboard

Rate limits (free tier):
- 50 hits/second burst (5s window)
- 10 hits/second sustained (2min window)
- Daily limits vary by endpoint

Usage:
    # Basic (all AI-generated photos)
    uv run python -m scrapers.freepik --config configs/flux1.py --api-key YOUR_KEY --max-images 500

    # Search term + orientation filter
    uv run python -m scrapers.freepik --config configs/flux1.py --api-key YOUR_KEY \\
        --term "portrait photography" --orientation portrait --max-images 200

    # Photos only (no vectors/PSDs), recent first
    uv run python -m scrapers.freepik --config configs/flux1.py --api-key YOUR_KEY \\
        --content-type photo --order recent --max-images 1000
"""

import asyncio
import random
import time
from pathlib import Path

import click
from tqdm import tqdm

from configs import load_config
from scrapers.base import BaseScraper, _DONE

API_BASE = "https://api.freepik.com/v1"


class FreepikScraper(BaseScraper):
    """Scrapes AI-generated images from Freepik's Stock Content API."""

    source_name = "freepik"

    def __init__(
        self,
        config,
        output_dir: str | Path,
        max_images: int,
        api_key: str,
        term: str | None = None,
        orientation: str | None = None,
        content_type: str | None = None,
        order: str = "recent",
        limit_per_page: int = 100,
        force: bool = False,
    ):
        self.config = config
        self.api_key = api_key
        self.term = term
        self.orientation = orientation
        self.content_type = content_type
        self.order = order
        self.limit_per_page = limit_per_page

        # Delays from config or defaults
        self.api_delay = getattr(config, "FREEPIK_API_DELAY", (2.0, 5.0))
        self.download_delay = getattr(config, "FREEPIK_DOWNLOAD_DELAY", (0.5, 2.0))
        min_pixels = getattr(config, "MIN_PIXELS", 200_000)

        super().__init__(output_dir, max_images, min_pixels=min_pixels, force=force)

        self.session.headers.update({
            "x-freepik-api-key": self.api_key,
            "Accept": "application/json",
        })

        self.download_workers = getattr(config, "FREEPIK_DOWNLOAD_WORKERS", 4)

        self.stats.update({
            "pages_fetched": 0,
            "resources_found": 0,
            "download_endpoint_failed": 0,
            "source_url_fallback": 0,
        })

    # ── Async producer/consumer ───────────────────────────────────

    async def run_async(self):
        """Run the full Freepik scraping pipeline with async producer/consumer."""
        self._setup_signals()

        tqdm.write(f"Starting Freepik scraper (target: {self.max_images}, workers: {self.download_workers})")
        tqdm.write(f"  AI-generated filter: only")
        if self.term:
            tqdm.write(f"  Search term: {self.term}")
        if self.orientation:
            tqdm.write(f"  Orientation: {self.orientation}")
        if self.content_type:
            tqdm.write(f"  Content type: {self.content_type}")
        tqdm.write(f"  Order: {self.order}")
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")

        self._pbar = tqdm(desc="Freepik", unit="img")
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
        """Paginate through search results, putting resource items on the queue."""
        page = 1
        max_page = 100  # Freepik API caps at page 100
        empty_pages = 0

        while page <= max_page and not self._should_stop:
            resources, meta = await asyncio.to_thread(self._fetch_page, page)
            self.stats["pages_fetched"] += 1
            self.stats["resources_found"] += len(resources)

            if not resources:
                empty_pages += 1
                if empty_pages >= 3:
                    tqdm.write("  3 consecutive empty pages, stopping pagination")
                    break
                page += 1
                continue
            empty_pages = 0

            total = meta.get("total", "?")
            last_page = meta.get("last_page", "?")
            tqdm.write(
                f"  Page {page}/{last_page} "
                f"({len(resources)} items, total={total})"
            )

            for resource in resources:
                if self._should_stop:
                    break
                await item_queue.put(resource)

            # Stop if we've reached the last page
            if isinstance(last_page, int) and page >= last_page:
                tqdm.write("  Reached last page")
                break

            page += 1
            await asyncio.sleep(random.uniform(*self.api_delay))

        # Signal workers to stop
        for _ in range(self.download_workers):
            await item_queue.put(_DONE)

    async def _consume_items(self, item_queue: asyncio.Queue, worker_id: int = 0):
        """Pull items from queue, download each."""
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
                skip=self.stats["skipped_duplicate_url"]
                + self.stats["skipped_duplicate_hash"],
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

    def _fetch_page(self, page: int) -> tuple[list[dict], dict]:
        """Fetch a page of AI-generated resources from the search endpoint.

        Returns:
            Tuple of (list of resource dicts, pagination meta dict).
        """
        params = {
            "page": page,
            "limit": self.limit_per_page,
            "order": self.order,
            "filters[ai-generated][only]": 1,
        }
        if self.term:
            params["term"] = self.term
        if self.orientation:
            params[f"filters[orientation][{self.orientation}]"] = 1
        if self.content_type:
            params[f"filters[content_type][{self.content_type}]"] = 1

        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.get(
                    f"{API_BASE}/resources", params=params, timeout=30
                )
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"  Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 401:
                    tqdm.write("  ERROR: Invalid API key (401). Check --api-key.")
                    return [], {}
                if resp.status_code == 403:
                    tqdm.write("  ERROR: Forbidden (403). Check API key permissions.")
                    return [], {}
                resp.raise_for_status()
                data = resp.json()
                return data.get("data", []), data.get("meta", {})
            except Exception as e:
                wait = (attempt + 1) * 15
                tqdm.write(f"  Error fetching page {page}: {e}, retrying in {wait}s...")
                time.sleep(wait)
        return [], {}

    def _get_download_url(self, resource_id: int) -> str | None:
        """Try the download endpoint to get a full-resolution download URL.

        GET /v1/resources/{id}/download returns JSON with a download URL.
        Falls back to None if the endpoint fails (e.g. premium-only resource).
        """
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.session.get(
                    f"{API_BASE}/resources/{resource_id}/download",
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait = (attempt + 1) * 20
                    time.sleep(wait)
                    continue
                if resp.status_code in (401, 403, 404):
                    return None
                resp.raise_for_status()
                data = resp.json()
                # Response format: {"data": {"url": "..."}} or similar
                if isinstance(data, dict):
                    # Try common response structures
                    if "data" in data and isinstance(data["data"], dict):
                        return data["data"].get("url")
                    if "url" in data:
                        return data["url"]
                return None
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep((attempt + 1) * 5)
                    continue
                return None
        return None

    def _download_item(self, resource: dict) -> bool:
        """Download a single Freepik resource."""
        resource_id = resource.get("id")
        if not resource_id:
            self.stats["failed"] += 1
            return False

        title = resource.get("title", "")
        image_info = resource.get("image", {})
        source_info = image_info.get("source", {})
        source_url = source_info.get("url", "")
        image_type = image_info.get("type", "unknown")
        orientation = image_info.get("orientation", "unknown")
        source_size = source_info.get("size", "")  # e.g. "740x640"

        # Extract author info
        author = resource.get("author", {})
        author_name = author.get("name", "")

        # Extract metadata
        meta = resource.get("meta", {})
        published_at = meta.get("published_at", "")
        available_formats = meta.get("available_formats", {})

        # Build metadata for manifest
        item_metadata = {
            "post_id": str(resource_id),
            "post_title": title[:200],
            "flair": f"freepik:{image_type}:{orientation}",
            "subreddit": "",  # not applicable
        }

        # Strategy 1: Try the download endpoint for full-resolution
        download_url = self._get_download_url(resource_id)
        if download_url:
            result = self.download_image(
                download_url, source="freepik", metadata=item_metadata
            )
            if result:
                return True

        # Strategy 2: Fall back to the source preview URL
        if source_url:
            self.stats["source_url_fallback"] += 1
            result = self.download_image(
                source_url, source="freepik", metadata=item_metadata
            )
            if result:
                return True
        else:
            self.stats["download_endpoint_failed"] += 1

        return False


@click.command()
@click.option(
    "--config", "-c", required=True, type=click.Path(exists=True),
    help="Generator config file (e.g. configs/flux1.py)",
)
@click.option(
    "--api-key", "-k", required=True, envvar="FREEPIK_API_KEY",
    help="Freepik API key (or set FREEPIK_API_KEY env var)",
)
@click.option("--output", "-o", default=None, help="Output directory (default: data/<generator>)")
@click.option("--max-images", "-n", type=int, default=1000, help="Max images to download")
@click.option("--term", "-t", default=None, help="Search term (e.g. 'portrait photography')")
@click.option(
    "--orientation", type=click.Choice(["landscape", "portrait", "square", "panoramic"]),
    default=None, help="Filter by orientation",
)
@click.option(
    "--content-type", type=click.Choice(["photo", "psd", "vector"]),
    default=None, help="Filter by content type",
)
@click.option(
    "--order", type=click.Choice(["relevance", "recent"]),
    default="recent", help="Sort order (default: recent)",
)
@click.option("--limit", type=int, default=100, help="Results per page (default: 100)")
@click.option("--force", is_flag=True, default=False, help="Ignore manifest, re-download everything")
def main(config, api_key, output, max_images, term, orientation, content_type, order, limit, force):
    """Scrape AI-generated images from Freepik's Stock Content API.

    Downloads all AI-generated stock photos. Cannot filter by specific AI model
    (FLUX vs Imagen vs Mystic), so post-download filtering by resolution and
    aspect ratio heuristics is needed.

    Requires a Freepik API key. Get one free at:
    https://www.freepik.com/developers/dashboard
    """
    cfg = load_config(config)
    output = output or f"data/{cfg.NAME}"

    scraper = FreepikScraper(
        cfg,
        output_dir=output,
        max_images=max_images,
        api_key=api_key,
        term=term,
        orientation=orientation,
        content_type=content_type,
        order=order,
        limit_per_page=limit,
        force=force,
    )
    scraper.run()


if __name__ == "__main__":
    main()
