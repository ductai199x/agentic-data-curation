"""Civitai scraper — downloads images from Civitai's TRPC API.

Supports two scraping modes:
1. **Model version gallery** (--model-version): Images generated on-site via Civitai's
   own generation API. Very trustworthy — no multi-tool contamination. Filenames often
   match `generator_import_*` pattern.
2. **Tool ID** (--tool-id or config CIVITAI_TOOL_ID): Images tagged with a specific tool.
   Includes user uploads and multi-tool workflows — less trustworthy.

Config-driven: reads from generator config file (e.g. configs/grok.py).

Usage:
    # On-site generation (most trustworthy)
    uv run python -m scrapers.civitai --config configs/grok.py --model-version 2738377

    # Tool ID (user-tagged, may include multi-tool workflows)
    uv run python -m scrapers.civitai --config configs/grok.py --max-images 1000

    # Multiple model versions
    uv run python -m scrapers.civitai --config configs/grok.py --model-version 2738377 --model-version 1234567
"""

import asyncio
import json
import random
import time
import urllib.parse
from pathlib import Path

import click
from tqdm import tqdm

from configs import load_config
from scrapers.base import BaseScraper, _DONE

CDN_BASE = "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA"
TRPC_BASE = "https://civitai.com/api/trpc/image.getInfinite"


def build_trpc_url(
    cursor: int | None = None,
    limit: int = 100,
    tool_id: int | None = None,
    model_version_id: int | None = None,
) -> str:
    """Build TRPC URL for image.getInfinite.

    Exactly one of tool_id or model_version_id should be provided.
    """
    params = {
        "limit": limit,
        "period": "AllTime",
        "sort": "Newest",
        "types": ["image"],
    }
    if tool_id is not None:
        params["tools"] = [tool_id]
    if model_version_id is not None:
        params["modelVersionId"] = model_version_id
    if cursor is not None:
        params["cursor"] = cursor
    input_json = json.dumps({"json": params})
    return f"{TRPC_BASE}?input={urllib.parse.quote(input_json)}"


class CivitaiScraper(BaseScraper):
    """Scrapes images from Civitai by tool ID or model version."""

    source_name = "civitai"

    def __init__(
        self,
        config,
        output_dir: str | Path,
        max_images: int,
        tool_id: int | None = None,
        model_version_ids: list[int] | None = None,
        api_key: str | None = None,
        force: bool = False,
    ):
        self.config = config
        self.tool_id = tool_id or getattr(config, "CIVITAI_TOOL_ID", None)
        # CIVITAI_MODEL_VERSIONS is list of (model_id, model_version_id) tuples
        if model_version_ids:
            self.model_version_ids = model_version_ids
        else:
            mv_tuples = getattr(config, "CIVITAI_MODEL_VERSIONS", [])
            self.model_version_ids = [mv_id for _, mv_id in mv_tuples]
        self.api_delay = getattr(config, "CIVITAI_API_DELAY", (5.0, 12.0))
        self.download_delay = getattr(config, "CIVITAI_DOWNLOAD_DELAY", (1.0, 3.0))
        min_pixels = getattr(config, "MIN_PIXELS", 200_000)

        super().__init__(output_dir, max_images, min_pixels=min_pixels, force=force)

        self.session.headers.update({"Referer": "https://civitai.com/"})
        self.session.max_redirects = 5
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"

        self.stats.update({
            "pages_fetched": 0,
            "urls_found": 0,
            "onsite_generations": 0,
        })

    # ── Async producer/consumer ───────────────────────────────────

    async def run_async(self):
        """Run the full Civitai scraping pipeline with async producer/consumer."""
        self._setup_signals()

        tqdm.write(f"Starting Civitai scraper (target: {self.max_images} images)")
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")

        item_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        producer = asyncio.create_task(self._produce_items(item_queue))
        consumer = asyncio.create_task(self._consume_items(item_queue))
        await asyncio.gather(producer, consumer)
        self.print_stats()

    async def _produce_items(self, item_queue: asyncio.Queue):
        """Iterate through model_version_ids then tool_id, paginating each."""
        # Priority 1: model version galleries (on-site generation, most trustworthy)
        for mv_id in self.model_version_ids:
            if self._should_stop:
                break
            await self._paginate_source(
                item_queue, label=f"model_version:{mv_id}",
                model_version_id=mv_id, is_onsite=True,
            )

        # Priority 2: tool ID — only if no model versions configured
        if not self._should_stop and self.tool_id and not self.model_version_ids:
            await self._paginate_source(
                item_queue, label=f"tool:{self.tool_id}",
                tool_id=self.tool_id, is_onsite=False,
            )

        await item_queue.put(_DONE)

    async def _paginate_source(
        self,
        item_queue: asyncio.Queue,
        label: str,
        tool_id: int | None = None,
        model_version_id: int | None = None,
        is_onsite: bool = False,
    ):
        """Paginate a single source, putting (item, label, is_onsite) tuples on queue."""
        tqdm.write(f"\n=== Civitai: {label} ===")
        cursor = None
        empty_pages = 0

        while not self._should_stop:
            items, next_cursor = await asyncio.to_thread(
                self._fetch_page, cursor, tool_id, model_version_id,
            )
            self.stats["pages_fetched"] += 1
            self.stats["urls_found"] += len(items)

            if not items:
                empty_pages += 1
                if empty_pages >= 3:
                    tqdm.write("  3 consecutive empty pages, stopping")
                    break
                continue
            empty_pages = 0

            tqdm.write(
                f"  Page {self.stats['pages_fetched']} "
                f"({len(items)} items, cursor={cursor})"
            )

            for item in items:
                if self._should_stop:
                    break
                await item_queue.put((item, label, is_onsite))

            if next_cursor is None:
                tqdm.write("  No more pages")
                break
            cursor = next_cursor
            await asyncio.sleep(random.uniform(*self.api_delay))

    async def _consume_items(self, item_queue: asyncio.Queue):
        """Pull items from queue, download each, show tqdm progress."""
        pbar = tqdm(total=self.max_images, desc="Civitai downloads", unit="img")
        pbar.update(0)

        while True:
            item = await item_queue.get()
            if item is _DONE:
                item_queue.task_done()
                break

            raw_item, label, is_onsite = item
            await asyncio.to_thread(
                self._download_item, raw_item, label, is_onsite,
            )
            pbar.n = self.stats["downloaded"]
            pbar.refresh()
            item_queue.task_done()

            if self._should_stop:
                break

            await asyncio.sleep(random.uniform(*self.download_delay))

        # Drain remaining items so producer isn't stuck on a full queue
        while not item_queue.empty():
            try:
                item_queue.get_nowait()
                item_queue.task_done()
            except asyncio.QueueEmpty:
                break

        pbar.close()

    # ── Sync helpers (called via asyncio.to_thread) ───────────────

    def _fetch_page(
        self, cursor: int | None = None,
        tool_id: int | None = None,
        model_version_id: int | None = None,
    ) -> tuple[list[dict], int | None]:
        """Fetch a page of images from the TRPC API."""
        url = build_trpc_url(
            cursor=cursor, tool_id=tool_id, model_version_id=model_version_id,
        )
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"  Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                result = data.get("result", {}).get("data", {}).get("json", {})
                return result.get("items", []), result.get("nextCursor")
            except Exception as e:
                wait = (attempt + 1) * 15
                tqdm.write(f"  Error fetching page: {e}, retrying in {wait}s...")
                time.sleep(wait)
        return [], None

    def _image_url(self, item: dict) -> str:
        """Build full-resolution image URL from item."""
        uuid = item["url"]
        name = item.get("name", f"{uuid}.jpg")
        return f"{CDN_BASE}/{uuid}/original=true/{name}"

    def _is_onsite_generation(self, item: dict) -> bool:
        """Check if image was generated on-site (not user upload)."""
        name = item.get("name", "")
        return name.startswith("generator_import_")

    def _download_item(self, item: dict, source_tag: str = "",
                       is_onsite: bool = False) -> bool:
        """Download a single Civitai image item."""
        if item.get("type") == "video" or item.get("mimeType", "").startswith("video/"):
            self.stats["skipped_video"] += 1
            return False

        url = self._image_url(item)
        # On-site if: scraped via model_version (always on-site) or filename matches
        is_onsite = is_onsite or self._is_onsite_generation(item)
        if is_onsite:
            self.stats["onsite_generations"] += 1

        return self.download_image(url, metadata={
            "post_id": str(item.get("id", "")),
            "post_title": item.get("postTitle") or "",
            "flair": f"onsite:{source_tag}" if is_onsite else source_tag,
        })


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True), help="Generator config file")
@click.option("--output", "-o", default=None, help="Output directory (default: data/<generator>)")
@click.option("--max-images", "-n", type=int, default=1000, help="Max images to download")
@click.option("--model-version", "model_versions", type=int, multiple=True,
              help="Civitai model version ID (repeatable, highest priority)")
@click.option("--tool-id", type=int, default=None, help="Civitai tool ID (overrides config)")
@click.option("--api-key", default=None, help="Civitai API key (optional)")
@click.option("--force", is_flag=True, default=False, help="Ignore manifest, re-download everything")
def main(config, output, max_images, model_versions, tool_id, api_key, force):
    """Scrape images from Civitai by model version or tool ID.

    Model version galleries contain on-site generations (very trustworthy).
    Tool ID returns user-tagged images (may include multi-tool workflows).
    """
    cfg = load_config(config)
    if model_versions:
        mv_ids = list(model_versions)
    else:
        mv_tuples = getattr(cfg, "CIVITAI_MODEL_VERSIONS", [])
        mv_ids = [mv_id for _, mv_id in mv_tuples]
    tid = tool_id or getattr(cfg, "CIVITAI_TOOL_ID", None)

    if not mv_ids and not tid:
        raise click.UsageError(
            "Provide --model-version or --tool-id, or set CIVITAI_MODEL_VERSIONS / CIVITAI_TOOL_ID in config"
        )

    output = output or f"data/{cfg.NAME}"
    scraper = CivitaiScraper(
        cfg, output_dir=output, max_images=max_images,
        tool_id=tid, model_version_ids=mv_ids, api_key=api_key, force=force,
    )
    scraper.run()


if __name__ == "__main__":
    main()
