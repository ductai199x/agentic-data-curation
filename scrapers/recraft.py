"""Recraft.ai community gallery scraper for Recraft V3 / V4 on-site generations.

Recraft has a public community gallery API that returns on-site generations
filtered by transform_model and image_types. All images were generated on
Recraft's own infrastructure — good provenance.

API: GET https://api.recraft.ai/images/community
  Params: limit (max 50), offset (0-based), image_types, transform_model
  No auth required.
  1,000 item cap per query combo — must iterate over all model + image_type combos.

CDN: HMAC-signed imgproxy at img.recraft.ai.
  Images are content-addressed by image_id.
  Request with Accept: image/jpeg for JPEG output.

Usage:
    uv run python -m scrapers.recraft --config configs/recraft_3_4.py --max-images 500
    uv run python -m scrapers.recraft --config configs/recraft_3_4.py --max-images 100 --force
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import random
import sys
import time

from tqdm import tqdm

from scrapers.base import BaseScraper, _DONE


API_URL = "https://api.recraft.ai/images/community"

# HMAC signing keys for imgproxy CDN
_IMGPROXY_KEY = bytes.fromhex(
    "19924c4e84eecbd667dd1caad00eb857523c17dbb71df1913869f74c6384d0b2"
    "00a384f54bb294e977f5377077e1f8b4716812013336713a8d5336e5aac79951"
)
_IMGPROXY_SALT = bytes.fromhex(
    "0238ed2dff25fa9c57178b408eb97d707e7ce63a12a9170a896e87d980ddde91"
    "286dd94cf3c343563b5d3fe59908721ef135be651fc01892685757f3c0f06b02"
)

# Models to scrape (V3 and V4 variants)
MODELS = ["recraftv3", "recraftv4", "recraftv4_raster", "recraftv4_pro_raster"]

# V3 realistic sub-types (16 total)
V3_REALISTIC_TYPES = [
    "realistic_image", "realistic_image_b_and_w", "realistic_image_enterprise",
    "realistic_image_evening_light", "realistic_image_faded_nostalgia",
    "realistic_image_forest_life", "realistic_image_hard_flash", "realistic_image_hdr",
    "realistic_image_motion_blur", "realistic_image_mystic_naturalism",
    "realistic_image_natural_light", "realistic_image_natural_tones",
    "realistic_image_organic_calm", "realistic_image_real_life_glow",
    "realistic_image_retro_realism", "realistic_image_retro_snapshot",
]


def make_image_url(image_id: str) -> str:
    """Build HMAC-signed imgproxy URL for a Recraft image ID."""
    path = f"/rs:fit:0:0:0/q:100/plain/abs://prod/images/{image_id}@jpg"
    digest = hmac.new(_IMGPROXY_KEY, _IMGPROXY_SALT + path.encode(), hashlib.sha256).digest()
    sig = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"https://img.recraft.ai/{sig}{path}"


def _build_query_combos() -> list[tuple[str, str]]:
    """Build all (model, image_type) combos to iterate over.

    V3 uses granular realistic sub-types.
    V4 models use 'any' (no granular types).
    """
    combos = []
    for model in MODELS:
        if model == "recraftv3":
            for img_type in V3_REALISTIC_TYPES:
                combos.append((model, img_type))
        else:
            combos.append((model, "any"))
    return combos


class RecraftScraper(BaseScraper):
    """Scrapes Recraft V3/V4 on-site generations from the community gallery."""

    source_name = "recraft"

    def __init__(self, config, max_images: int = 500, force: bool = False):
        output_dir = f"data/{config.NAME}"
        super().__init__(
            output_dir, max_images,
            min_pixels=getattr(config, "MIN_PIXELS", 500_000),
            force=force,
        )
        self.config = config
        self.api_delay = getattr(config, "RECRAFT_API_DELAY", (1.0, 2.0))
        self.download_delay = getattr(config, "RECRAFT_DOWNLOAD_DELAY", (0.5, 1.0))
        self.download_workers = getattr(config, "RECRAFT_DOWNLOAD_WORKERS", 4)

        self.session.headers.update({
            "Accept": "application/json",
            "Referer": "https://www.recraft.ai/",
        })

        self.stats.update({
            "pages_fetched": 0,
            "urls_found": 0,
            "combos_exhausted": 0,
        })

    # ── Async producer/consumer ───────────────────────────────────

    async def run_async(self):
        """Run the full Recraft scraping pipeline with async producer/consumer."""
        self._setup_signals()
        combos = _build_query_combos()

        tqdm.write(f"Starting Recraft scraper (target: {self.max_images}, workers: {self.download_workers})")
        tqdm.write(f"  Query combos: {len(combos)} (models x image_types)")
        tqdm.write(f"  Already downloaded: {len(self.downloaded_urls)} URLs")
        self._pbar = tqdm(desc="Recraft", unit="img", file=sys.stderr)
        self._processed = 0

        item_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        producer = asyncio.create_task(self._produce_items(item_queue, combos))
        consumers = [
            asyncio.create_task(self._consume_items(item_queue, worker_id=i))
            for i in range(self.download_workers)
        ]
        await producer
        await asyncio.gather(*consumers)
        self._pbar.close()
        self.print_stats()

    async def _produce_items(self, item_queue: asyncio.Queue, combos: list[tuple[str, str]]):
        """Iterate over all model+image_type combos, paginate each, enqueue items."""
        for combo_idx, (model, image_type) in enumerate(combos):
            if self._should_stop:
                break

            combo_label = f"{model}:{image_type}"
            tqdm.write(f"\n  [{combo_idx + 1}/{len(combos)}] Querying {combo_label}")
            combo_count = 0

            # Paginate offset 0 to 1000 step 50
            for offset in range(0, 1000, 50):
                if self._should_stop:
                    break

                items = await asyncio.to_thread(
                    self._fetch_page, model, image_type, offset,
                )
                self.stats["pages_fetched"] += 1

                if not items:
                    tqdm.write(f"    {combo_label} offset={offset}: 0 items — exhausted")
                    break

                self.stats["urls_found"] += len(items)
                combo_count += len(items)

                # Tag each item with model/image_type for flair
                for item in items:
                    item["_model"] = model
                    item["_image_type"] = image_type

                for item in items:
                    if self._should_stop:
                        break
                    await item_queue.put(item)

                await asyncio.sleep(random.uniform(*self.api_delay))

            tqdm.write(f"    {combo_label}: {combo_count} items total")
            self.stats["combos_exhausted"] += 1

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

    def _fetch_page(self, model: str, image_type: str, offset: int) -> list[dict]:
        """Fetch one page of community images for a given model + image_type."""
        params = {
            "limit": 50,
            "offset": offset,
            "transform_model": model,
        }
        # Only pass image_types if not "any"
        if image_type != "any":
            params["image_types"] = image_type

        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.get(API_URL, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"    Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 403:
                    wait = (attempt + 1) * 15
                    tqdm.write(f"    Forbidden (403), backing off {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                # API wraps results in "recraft_images" key
                if isinstance(data, dict):
                    return data.get("recraft_images", data.get("images", []))
                if isinstance(data, list):
                    return data
                return []
            except Exception as e:
                wait = (attempt + 1) * 10
                tqdm.write(f"    Error fetching page: {e}, retrying in {wait}s...")
                time.sleep(wait)

        return []

    def _download_item(self, item: dict) -> bool:
        """Download a single Recraft community image."""
        image_id = item.get("image_id") or item.get("id")
        if not image_id:
            self.stats["failed"] += 1
            return False

        url = make_image_url(image_id)
        model = item.get("_model", "unknown")
        image_type = item.get("_image_type", "unknown")

        # Build flair: recraft:recraftv3:realistic_image
        flair = f"recraft:{model}:{image_type}"

        prompt = item.get("prompt", "") or ""

        metadata = {
            "post_id": str(image_id),
            "post_title": str(prompt)[:200],
            "flair": flair,
            "subreddit": "",
        }

        # Use Accept header to get JPEG
        old_accept = self.session.headers.get("Accept", "")
        self.session.headers["Accept"] = "image/jpeg"
        try:
            result = self.download_image(url, source="recraft", metadata=metadata)
        finally:
            self.session.headers["Accept"] = old_accept

        return result


def main():
    parser = argparse.ArgumentParser(description="Scrape Recraft.ai community gallery")
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--max-images", "-n", type=int, default=500)
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest")
    args = parser.parse_args()

    from configs import load_config
    config = load_config(args.config)

    scraper = RecraftScraper(config, max_images=args.max_images, force=args.force)
    scraper.run()


if __name__ == "__main__":
    main()
