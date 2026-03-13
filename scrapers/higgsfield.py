"""Higgsfield community gallery scraper for Nano Banana images.

Scrapes the public community API at fnf.higgsfield.ai.
Cursor-based pagination, full-res PNGs on CloudFront CDN.

Usage:
    uv run python -m scrapers.higgsfield --config configs/nano_banana.py --max-images 5000
"""

import argparse
import http.cookiejar
import random
import sys
import time

from tqdm import tqdm

from scrapers.base import BaseScraper


class HiggsFieldScraper(BaseScraper):
    source_name = "higgsfield"

    def __init__(self, config, max_images: int = 500, force: bool = False):
        output_dir = f"data/{config.NAME}"
        super().__init__(output_dir, max_images, min_pixels=getattr(config, "MIN_PIXELS", 200_000), force=force)
        self.config = config
        self.api_base = getattr(config, "HIGGSFIELD_API_BASE", "https://fnf.higgsfield.ai/publications/community")
        self.models = getattr(config, "HIGGSFIELD_MODELS", [])
        self.page_size = getattr(config, "HIGGSFIELD_PAGE_SIZE", 50)
        self.delay = getattr(config, "HIGGSFIELD_DELAY", (3.0, 7.0))

        # Load cookies
        cookies_path = getattr(config, "HIGGSFIELD_COOKIES_PATH", None)
        if cookies_path:
            cj = http.cookiejar.MozillaCookieJar(cookies_path)
            cj.load(ignore_discard=True, ignore_expires=True)
            self.session.cookies.update(cj)

        # Required headers for CORS
        self.session.headers.update({
            "Origin": "https://higgsfield.ai",
            "Referer": "https://higgsfield.ai/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 Edg/145.0.0.0",
        })

    def run(self):
        """Synchronous scraper — no async needed for sequential pagination."""
        pbar = tqdm(total=self.max_images, desc="Higgsfield", unit="img", file=sys.stderr)

        for model in self.models:
            if self.done:
                break

            # First page
            params = {"size": self.page_size, "model": model}
            try:
                resp = self.session.get(self.api_base, params=params, timeout=(5, 15))
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  API error for {model}: {e}", flush=True)
                continue

            total = data.get("total", "?")
            items = data.get("items", [])
            has_more = data.get("has_more", False)
            cursor = data.get("cursor")

            print(f"\n📦 {model}: {total} total posts", flush=True)

            # Process first page
            self._process_items(model, items, pbar)

            page = 1
            while has_more and cursor and not self.done:
                # Short delay for skip pages, full delay for pages with new content
                all_seen = self._page_all_seen(items)
                delay = random.uniform(0.3, 0.8) if all_seen else random.uniform(*self.delay)
                time.sleep(delay)

                params = {"size": self.page_size, "model": model, "cursor": cursor}
                try:
                    resp = self.session.get(self.api_base, params=params, timeout=(5, 15))
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as e:
                    print(f"  API error page {page+1}: {e}", flush=True)
                    break

                items = data.get("items", [])
                has_more = data.get("has_more", False)
                cursor = data.get("cursor")
                page += 1

                if all_seen and self._page_all_seen(items):
                    if page % 10 == 0:
                        print(f"  Page {page}: skipping (already downloaded)", flush=True)
                else:
                    self._process_items(model, items, pbar)
                    if page % 10 == 0:
                        print(f"  Page {page}: {self.stats['downloaded']} downloaded so far", flush=True)

                if not items:
                    break

        pbar.close()
        self.print_stats()

    def _process_items(self, model: str, items: list, pbar):
        """Download images from a page of API results."""
        for entry in items:
            if self.done:
                break

            # Extract image URL — prefer raw result
            results = entry.get("results", {})
            raw = results.get("raw", {})
            result = entry.get("result", {})

            url = raw.get("url") or (result.get("url", "") if result else "")
            result_type = (result.get("type") if result else None) or (raw.get("type") if raw else None)
            if not url or result_type != "image":
                continue

            # Skip already-downloaded URLs
            if url in self.downloaded_urls:
                continue

            # Extract metadata
            entry_params = entry.get("params", {})
            metadata = {
                "post_id": entry.get("id", ""),
                "post_title": (entry_params.get("prompt") or "")[:200],
                "flair": model,
                "subreddit": "",
            }

            success = self.download_image(url, source=f"higgsfield_{model}", metadata=metadata)
            if success:
                pbar.update(1)
                pbar.set_postfix(dl=self.stats["downloaded"], model=model)

                # Rate limit between downloads (CDN, not API)
                time.sleep(random.uniform(1.0, 2.0))

    def _page_all_seen(self, items: list) -> bool:
        """Check if all image URLs on a page are already downloaded."""
        for item in items:
            results = item.get("results", {})
            raw = results.get("raw", {})
            result = item.get("result", {})
            url = raw.get("url") or (result.get("url", "") if result else "")
            if url and url not in self.downloaded_urls:
                return False
        return True

    async def run_async(self):
        """Compat — just calls sync run()."""
        self.run()


def main():
    parser = argparse.ArgumentParser(description="Scrape Higgsfield community galleries")
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--max-images", "-n", type=int, default=500)
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest")
    args = parser.parse_args()

    from configs import load_config
    config = load_config(args.config)

    scraper = HiggsFieldScraper(config, max_images=args.max_images, force=args.force)
    scraper.run()


if __name__ == "__main__":
    main()
