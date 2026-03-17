"""Tensor.Art scraper — downloads FLUX.1 images from Tensor.Art's post API.

Tensor.Art is Cloudflare-protected with HMAC request signing. Strategy:
1. Use Playwright to load the tag page once (passes Cloudflare + initializes session)
2. Capture signing headers from the initial API call
3. Use plain requests for all subsequent API pagination (fast, reliable)

All posts on the FLUX tag page include full generation metadata (base model, LoRAs,
prompt, dimensions). We filter for FLUX.1 base model only (not FLUX.2, not SD 3.5, etc.)
and optionally reject LoRA-contaminated images.

Usage:
    # Default: scrape FLUX.1 images from the FLUX tag
    uv run python -m scrapers.tensorart --config configs/flux1.py --max-images 2000

    # Skip LoRA-contaminated images
    uv run python -m scrapers.tensorart --config configs/flux1.py --max-images 2000 --reject-lora

    # Force fresh start
    uv run python -m scrapers.tensorart --config configs/flux1.py --max-images 500 --force
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

from tqdm import tqdm

from scrapers.base import BaseScraper, _DONE

# Tensor.Art API
API_BASE = "https://api.tensor.art/community-web/v1/post/list"
FLUX_TAG_ID = "757298563872127859"

# FLUX.1 base model identifiers observed on Tensor.Art
# baseModel field is "FLUX.1" for all FLUX.1 variants (dev, schnell, pro)
FLUX1_BASE_MODEL = "FLUX.1"

# Known FLUX.1 Schnell model variants (separate base model string)
FLUX1_SCHNELL_BASE = "FLUX.1 Schnell"

# Variants to EXCLUDE (separate generation families)
EXCLUDED_BASE_MODELS = {
    "FLUX.2",
}


class TensorArtScraper(BaseScraper):
    """Scrapes FLUX.1 images from Tensor.Art's post API."""

    source_name = "tensorart"

    def __init__(
        self,
        config,
        max_images: int = 1000,
        reject_lora: bool = False,
        force: bool = False,
        page_size: int = 20,
    ):
        output_dir = f"data/{config.NAME}"
        super().__init__(
            output_dir,
            max_images,
            min_pixels=getattr(config, "MIN_PIXELS", 200_000),
            force=force,
        )
        self.config = config
        self.reject_lora = reject_lora
        self.page_size = page_size

        # Delays
        self.api_delay = getattr(config, "TENSORART_API_DELAY", (2.0, 5.0))
        self.download_delay = getattr(config, "TENSORART_DOWNLOAD_DELAY", (0.5, 1.5))
        self.download_workers = getattr(config, "TENSORART_DOWNLOAD_WORKERS", 4)

        # Signing headers captured from Playwright session
        self._sign_headers: dict[str, str] = {}

        # Multiple sort orders to get past pagination limits
        self._sort_orders = [
            "NEWEST",
            "MOST_LIKED",
            "HOT",
            "FRESH_FINDS_LONG_TERM",
        ]
        self._current_sort = self._sort_orders[0]

        self.stats.update({
            "pages_fetched": 0,
            "urls_found": 0,
            "skipped_not_flux1": 0,
            "skipped_lora": 0,
            "skipped_no_gendata": 0,
        })

    # ── Playwright bootstrap ─────────────────────────────────────

    async def _capture_signing_headers(self) -> bool:
        """Load the tag page in Playwright and capture API signing headers.

        Returns True if headers were captured successfully.
        """
        from playwright.async_api import async_playwright

        captured = {}

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()
            await page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )

            async def on_request(request):
                if "post/list" in request.url and not captured:
                    captured["headers"] = dict(request.headers)

            page.on("request", on_request)

            tqdm.write("Launching Playwright to capture signing headers...")
            try:
                await page.goto(
                    f"https://tensor.art/tag/{FLUX_TAG_ID}",
                    wait_until="networkidle",
                    timeout=60000,
                )
                await asyncio.sleep(3)
            except Exception as e:
                tqdm.write(f"Failed to load tag page: {e}")
                await browser.close()
                return False

            title = await page.title()
            if "Just a moment" in title:
                tqdm.write("BLOCKED by Cloudflare challenge — cannot proceed")
                await browser.close()
                return False

            tqdm.write(f"Page loaded: {title}")
            await browser.close()

        if not captured:
            tqdm.write("No API calls intercepted — signing headers not captured")
            return False

        # Extract signing headers
        h = captured["headers"]
        self._sign_headers = {
            "X-Request-Sign": h.get("x-request-sign", ""),
            "X-Request-Timestamp": h.get("x-request-timestamp", ""),
            "X-Request-Sign-Type": h.get("x-request-sign-type", "HMAC_SHA256"),
            "X-Request-Sign-Version": h.get("x-request-sign-version", "v1"),
            "X-Request-Package-Sign-Version": h.get("x-request-package-sign-version", "0.0.1"),
            "X-Request-Package-Id": h.get("x-request-package-id", "3000"),
            "X-Request-Lang": h.get("x-request-lang", "en-US"),
        }

        # Update the requests session with these headers
        self.session.headers.update(self._sign_headers)
        self.session.headers.update({
            "Content-Type": "application/json",
            "Referer": f"https://tensor.art/tag/{FLUX_TAG_ID}",
            "Origin": "https://tensor.art",
        })

        tqdm.write("Signing headers captured successfully")
        return True

    # ── Async producer/consumer ──────────────────────────────────

    async def run_async(self):
        """Run the full scraping pipeline."""
        self._setup_signals()

        # Step 1: capture signing headers via Playwright
        if not await self._capture_signing_headers():
            tqdm.write("FATAL: Could not capture signing headers. Aborting.")
            return

        tqdm.write(
            f"Starting Tensor.Art scraper (target: {self.max_images}, "
            f"workers: {self.download_workers}, reject_lora: {self.reject_lora})"
        )
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")

        self._pbar = tqdm(desc="TensorArt", unit="img", file=sys.stderr)
        self._processed = 0

        item_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        producer = asyncio.create_task(self._produce_items(item_queue))
        consumers = [
            asyncio.create_task(self._consume_items(item_queue, worker_id=i))
            for i in range(self.download_workers)
        ]
        # Run all concurrently; consumers exit when done or _DONE received
        await asyncio.gather(producer, *consumers)
        self._pbar.close()
        self.print_stats()

    async def _produce_items(self, item_queue: asyncio.Queue):
        """Paginate the tag API and enqueue image items.

        Cycles through multiple sort orders to bypass per-sort pagination limits.
        """
        for sort_order in self._sort_orders:
            if self._should_stop:
                break

            self._current_sort = sort_order
            tqdm.write(f"\n=== Sort order: {sort_order} ===")
            cursor = None
            empty_pages = 0

            while not self._should_stop:
                items, next_cursor, has_more = await asyncio.to_thread(
                    self._fetch_page, cursor
                )
                self.stats["pages_fetched"] += 1

                if self._should_stop:
                    break

                if not items:
                    empty_pages += 1
                    if empty_pages >= 3:
                        tqdm.write(f"  3 empty pages on {sort_order}, moving to next sort")
                        break
                    await asyncio.sleep(random.uniform(*self.api_delay))
                    continue

                empty_pages = 0
                tqdm.write(
                    f"  Page {self.stats['pages_fetched']}: "
                    f"{len(items)} posts (cursor={str(cursor)[:30]})"
                )

            # Extract individual images from posts
            for post in items:
                if self._should_stop:
                    break

                post_id = post.get("id", "")
                post_title = post.get("title", "") or post.get("content", "")
                images = post.get("images", [])

                for img in images:
                    if self._should_stop:
                        break

                    parsed = self._parse_image(img)
                    if parsed is None:
                        continue

                    img_url, base_model_label, has_lora = parsed
                    self.stats["urls_found"] += 1

                    # Use put_nowait with a fallback to avoid blocking forever
                    # when queue is full and consumers are done
                    try:
                        item_queue.put_nowait({
                            "url": img_url,
                            "post_id": post_id,
                            "post_title": str(post_title)[:200],
                            "base_model_label": base_model_label,
                            "has_lora": has_lora,
                            "width": img.get("width", 0),
                            "height": img.get("height", 0),
                        })
                    except asyncio.QueueFull:
                        if self._should_stop:
                            break
                        await item_queue.put({
                            "url": img_url,
                            "post_id": post_id,
                            "post_title": str(post_title)[:200],
                            "base_model_label": base_model_label,
                            "has_lora": has_lora,
                            "width": img.get("width", 0),
                            "height": img.get("height", 0),
                        })

            if not has_more or next_cursor is None:
                tqdm.write("No more pages available")
                break

            cursor = next_cursor
            await asyncio.sleep(random.uniform(*self.api_delay))

        # Signal consumers to stop
        for _ in range(self.download_workers):
            await item_queue.put(_DONE)

    async def _consume_items(self, item_queue: asyncio.Queue, worker_id: int = 0):
        """Download images from the queue."""
        while True:
            # Use wait_for to avoid blocking forever when producer is still paginating
            try:
                item = await asyncio.wait_for(item_queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                if self._should_stop:
                    break
                continue

            if item is _DONE:
                item_queue.task_done()
                break

            if self._should_stop:
                item_queue.task_done()
                break

            success = await asyncio.to_thread(self._download_item, item)
            self._processed += 1
            self._pbar.n = self._processed
            self._pbar.set_postfix(
                dl=self.stats["downloaded"],
                fail=self.stats["failed"],
                skip_model=self.stats["skipped_not_flux1"],
                skip_lora=self.stats["skipped_lora"],
            )
            self._pbar.refresh()
            item_queue.task_done()

            if self._should_stop:
                break

            if success:
                await asyncio.sleep(random.uniform(*self.download_delay))

    # ── Sync helpers (called via asyncio.to_thread) ──────────────

    def _fetch_page(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None, bool]:
        """Fetch a page of posts from the Tensor.Art API.

        Returns (items, next_cursor, has_more).
        """
        body = {
            "filter": {"orTagIds": [FLUX_TAG_ID]},
            "size": str(self.page_size),
            "sort": self._current_sort,
            "visibility": "NORMAL",
        }
        if cursor is not None:
            body["cursor"] = cursor

        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.post(API_BASE, json=body, timeout=30)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"  Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 403:
                    tqdm.write(f"  Forbidden (403) — signing headers may have expired")
                    return [], None, False
                resp.raise_for_status()

                data = resp.json()
                if data.get("code") != "0":
                    tqdm.write(f"  API error: {data.get('message', 'unknown')}")
                    return [], None, False

                result = data.get("data", {})
                return (
                    result.get("items", []),
                    result.get("cursor"),
                    result.get("hasMore", False),
                )
            except Exception as e:
                wait = (attempt + 1) * 10
                tqdm.write(f"  Error fetching page: {e}, retrying in {wait}s...")
                time.sleep(wait)

        return [], None, False

    def _parse_image(self, img: dict) -> tuple[str, str, bool] | None:
        """Parse a single image entry from the API response.

        Returns (url, base_model_label, has_lora) or None to skip.
        """
        gen_data = img.get("generationData", {})
        gen_type = gen_data.get("type", "")

        # Must have generation data (proves it was generated on Tensor.Art)
        if gen_type not in ("TENSOR_ART_V1", "SD_WEB_V1"):
            self.stats["skipped_no_gendata"] += 1
            return None

        # Extract base model info
        if gen_type == "TENSOR_ART_V1":
            ta_v1 = gen_data.get("tensorArtV1", {})
            base_model = ta_v1.get("baseModel", {})
            base_model_name = base_model.get("baseModel", "")
            base_model_label = base_model.get("label", "")
            loras = ta_v1.get("models", [])
            has_lora = any(m.get("type") == "LORA" for m in loras)
        elif gen_type == "SD_WEB_V1":
            sd_v1 = gen_data.get("sdWebV1", {})
            # sdWebV1 doesn't have structured model info the same way
            # Skip these — less reliable provenance
            self.stats["skipped_no_gendata"] += 1
            return None
        else:
            self.stats["skipped_no_gendata"] += 1
            return None

        # Filter: must match accepted base models from config (or defaults)
        accepted = getattr(self.config, "TENSORART_ACCEPTED_BASE_MODELS", None)
        if accepted is None:
            accepted = {FLUX1_BASE_MODEL, FLUX1_SCHNELL_BASE}
        if base_model_name not in accepted:
            self.stats["skipped_not_flux1"] += 1
            return None

        # Optional: reject LoRA-contaminated images
        if self.reject_lora and has_lora:
            self.stats["skipped_lora"] += 1
            return None

        url = img.get("url", "")
        if not url:
            return None

        return url, f"{base_model_name}:{base_model_label}", has_lora

    def _download_item(self, item: dict) -> bool:
        """Download a single image item."""
        url = item["url"]

        metadata = {
            "post_id": item["post_id"],
            "post_title": item["post_title"],
            "flair": f"tensorart:{item['base_model_label']}",
            "subreddit": "",
        }

        return self.download_image(url, source="tensorart", metadata=metadata)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape FLUX.1 images from Tensor.Art"
    )
    parser.add_argument("--config", "-c", required=True, help="Generator config file path")
    parser.add_argument("--max-images", "-n", type=int, default=1000, help="Max images to download")
    parser.add_argument(
        "--reject-lora",
        action="store_true",
        default=False,
        help="Skip images that have LoRA models applied",
    )
    parser.add_argument("--force", action="store_true", default=False, help="Ignore existing manifest")
    parser.add_argument("--page-size", type=int, default=20, help="API page size (default: 20)")
    args = parser.parse_args()

    from configs import load_config

    config = load_config(args.config)

    scraper = TensorArtScraper(
        config,
        max_images=args.max_images,
        reject_lora=args.reject_lora,
        force=args.force,
        page_size=args.page_size,
    )
    asyncio.run(scraper.run_async())


if __name__ == "__main__":
    main()
