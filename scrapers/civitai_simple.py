"""Simple synchronous Civitai scraper — no async, no deadlocks.

Paginates through model version gallery and downloads images sequentially.
Slower than async but never hangs.

Usage:
    uv run python -m scrapers.civitai_simple -c configs/flux1.py -v 691639 -n 50000
"""

import random
import time

import click
from tqdm import tqdm

from configs import load_config
from scrapers.base import BaseScraper
from scrapers.civitai import build_trpc_url, CDN_BASE


class SimpleCivitaiScraper(BaseScraper):
    source_name = "civitai"

    def __init__(self, config, output_dir, max_images, model_version_id, force=False):
        super().__init__(output_dir, max_images,
                         min_pixels=getattr(config, "MIN_PIXELS", 200_000),
                         force=force)
        self.config = config
        self.model_version_id = model_version_id
        self.api_delay = getattr(config, "CIVITAI_API_DELAY", (3.0, 6.0))
        self.download_delay = getattr(config, "CIVITAI_DOWNLOAD_DELAY", (0.5, 1.5))

    def run_sync(self):
        """Simple synchronous scrape loop."""
        label = f"model_version:{self.model_version_id}"
        tqdm.write(f"Starting simple Civitai scraper: {label}")
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")

        cursor = None
        empty_pages = 0
        pbar = tqdm(desc=f"Civitai:{self.model_version_id}", unit="img")
        new_downloads = 0

        while not self.done:
            # Fetch page
            try:
                items, next_cursor = self._fetch_page(cursor)
            except Exception as e:
                tqdm.write(f"  Fetch error: {e}, waiting 30s...")
                time.sleep(30)
                continue

            if not items:
                empty_pages += 1
                if empty_pages >= 3:
                    tqdm.write("  3 empty pages, stopping")
                    break
                time.sleep(5)
                continue
            empty_pages = 0

            tqdm.write(f"  Page (cursor={cursor}): {len(items)} items")

            # Process each item
            for item in items:
                if self.done:
                    break

                if item.get("type") == "video" or (item.get("mimeType") or "").startswith("video/"):
                    continue

                url = self._image_url(item)

                metadata = {
                    "post_id": str(item.get("id", "")),
                    "post_title": item.get("postTitle") or "",
                    "flair": f"onsite:{label}",
                }

                success = self.download_image(url, metadata=metadata)
                pbar.update(1)
                pbar.set_postfix(
                    dl=self.stats["downloaded"],
                    fail=self.stats["failed"],
                    skip=self.stats["skipped_duplicate_url"] + self.stats["skipped_duplicate_hash"],
                )

                if success:
                    new_downloads += 1
                    time.sleep(random.uniform(*self.download_delay))

            if next_cursor is None:
                tqdm.write("  No more pages")
                break
            cursor = next_cursor
            time.sleep(random.uniform(*self.api_delay))

        pbar.close()
        tqdm.write(f"\nNew downloads this run: {new_downloads}")
        self.print_stats()

    def _fetch_page(self, cursor=None):
        url = build_trpc_url(cursor=cursor, model_version_id=self.model_version_id)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, timeout=(10, 30))  # connect, read
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"  429, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                result = data.get("result", {}).get("data", {}).get("json", {})
                return result.get("items", []), result.get("nextCursor")
            except Exception as e:
                wait = (attempt + 1) * 10
                tqdm.write(f"  Error: {e}, retry in {wait}s...")
                time.sleep(wait)
        return [], None

    def _image_url(self, item):
        uuid = item["url"]
        name = item.get("name", f"{uuid}.jpg")
        return f"{CDN_BASE}/{uuid}/original=true/{name}"

    def run(self):
        self.run_sync()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--model-version", "-v", type=int, required=True)
@click.option("--max-images", "-n", type=int, default=50000)
@click.option("--output", "-o", default=None)
@click.option("--force", is_flag=True, default=False)
def main(config, model_version, max_images, output, force):
    cfg = load_config(config)
    output = output or f"data/{cfg.NAME}"
    scraper = SimpleCivitaiScraper(
        cfg, output, max_images, model_version, force=force,
    )
    scraper.run_sync()


if __name__ == "__main__":
    main()
