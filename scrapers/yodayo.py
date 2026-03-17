"""Yodayo on-site generation scraper.

Scrapes the API at api.yodayo.com via Playwright (Cloudflare-protected).
Uses browser context to bypass Cloudflare, then paginates via page.evaluate().

Model version UUIDs are read from the config's YODAYO_MODELS dict.
Optional LoRA filtering via config's YODAYO_REJECT_LORA flag.

Usage:
    uv run python -m scrapers.yodayo --config configs/seedream4.py --max-images 500
    uv run python -m scrapers.yodayo --config configs/flux1.py --max-images 5000
"""

import argparse
import asyncio
import json
import random
import sys
import time

from tqdm import tqdm

from scrapers.base import BaseScraper


# Default model version UUIDs (Seedream) — used when config has no YODAYO_MODELS
DEFAULT_YODAYO_MODELS = {
    "seedream_4.0": "83b84285-5786-46f0-9b76-6fbcedd82fb0",
    "seedream_4.5": "7bf33183-e549-4349-b971-9ab6954a707b",
}

# Default Cloudflare seed page (Seedream model page)
DEFAULT_SEED_URL = "https://yodayo.com/models/987444bd-84a7-48f2-a1eb-fddcd4631364?index=4&modelversion=83b84285-5786-46f0-9b76-6fbcedd82fb0"


class YodayoScraper(BaseScraper):
    source_name = "yodayo"

    def __init__(self, config, max_images: int = 500, force: bool = False):
        output_dir = f"data/{config.NAME}"
        super().__init__(output_dir, max_images, min_pixels=getattr(config, "MIN_PIXELS", 200_000), force=force)
        self.config = config
        self.models = getattr(config, "YODAYO_MODELS", DEFAULT_YODAYO_MODELS)
        self.reject_lora = getattr(config, "YODAYO_REJECT_LORA", False)
        self.lora_skipped = 0
        self.model_skipped = 0

    def _build_seed_url(self) -> str:
        """Build a Cloudflare seed URL from the first model version UUID."""
        first_uuid = next(iter(self.models.values()))
        return f"https://yodayo.com/models/{first_uuid}"

    async def run_async(self):
        """Use Playwright to bypass Cloudflare and paginate API."""
        self._setup_signals()

        from playwright.async_api import async_playwright

        pbar = tqdm(desc="Yodayo", unit="img", file=sys.stderr)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )
            page = await ctx.new_page()
            await page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )

            # Navigate to a Yodayo page to pass Cloudflare + initialize API context
            seed_url = self._build_seed_url()
            print(f"Passing Cloudflare challenge via {seed_url}...", flush=True)
            await page.goto(seed_url, wait_until="load", timeout=30000)
            await asyncio.sleep(5)

            title = await page.title()
            if "Just a moment" in title:
                print("BLOCKED by Cloudflare — cannot proceed", flush=True)
                await browser.close()
                return

            print(f"Cloudflare passed. Page: {title}", flush=True)

            for model_label, version_uuid in self.models.items():
                if self._should_stop or self.done:
                    break

                print(f"\n  Scraping {model_label} ({version_uuid})", flush=True)

                offset = 0
                limit = 200
                empty_pages = 0

                while not self._should_stop and not self.done:
                    # Fetch posts via browser's fetch (has Cloudflare context)
                    api_url = f"https://api.yodayo.com/v1/model_versions/{version_uuid}/posts?limit={limit}&offset={offset}&sort=newest"

                    try:
                        result = await page.evaluate(f"""
                            async () => {{
                                const resp = await fetch("{api_url}", {{credentials: "omit"}});
                                return {{ status: resp.status, text: await resp.text() }};
                            }}
                        """)
                    except Exception as e:
                        print(f"  Fetch error at offset {offset}: {e}", flush=True)
                        break

                    if result["status"] != 200:
                        print(f"  API returned {result['status']} at offset {offset}", flush=True)
                        break

                    try:
                        data = json.loads(result["text"])
                    except json.JSONDecodeError:
                        print(f"  Invalid JSON at offset {offset}", flush=True)
                        break

                    posts = data.get("posts", [])
                    if not posts:
                        empty_pages += 1
                        if empty_pages >= 2:
                            print(f"  Exhausted {model_label} at offset {offset}", flush=True)
                            break
                        offset += limit
                        continue

                    empty_pages = 0

                    for post in posts:
                        if self._should_stop or self.done:
                            break

                        # Images are in photo_media[], each with text_to_image metadata
                        photos = post.get("photo_media", [])
                        for photo in photos:
                            if self._should_stop or self.done:
                                break

                            t2i = photo.get("text_to_image", {})
                            model_name = t2i.get("model", "")

                            # LoRA filtering: reject posts with non-empty extra_networks
                            if self.reject_lora:
                                extra_networks = t2i.get("extra_networks")
                                if extra_networks:  # non-empty list/dict = LoRA applied
                                    self.lora_skipped += 1
                                    continue

                            img_uuid = photo.get("uuid", "")
                            if not img_uuid:
                                continue

                            img_url = f"https://photos.yodayo.com/{img_uuid}.jpg"
                            if img_url in self.downloaded_urls:
                                continue

                            metadata = {
                                "post_id": post.get("uuid", ""),
                                "post_title": t2i.get("prompt", "")[:200],
                                "flair": f"yodayo:{model_label}",
                                "subreddit": "",
                            }

                            success = self.download_image(
                                img_url, source=f"yodayo_{model_label}", metadata=metadata
                            )
                            pbar.update(1)
                            pbar.set_postfix(
                                dl=self.stats["downloaded"],
                                fail=self.stats["failed"],
                                skip=self.stats["skipped_duplicate_url"]
                                + self.stats["skipped_duplicate_hash"],
                                lora=self.lora_skipped,
                                model=model_label,
                            )

                            if success:
                                await asyncio.sleep(random.uniform(0.5, 1.5))

                    offset += limit
                    await asyncio.sleep(random.uniform(2.0, 4.0))

            await browser.close()

        pbar.close()
        if self.lora_skipped:
            print(f"\n  LoRA-filtered: {self.lora_skipped} images skipped", flush=True)
        self.print_stats()


def main():
    parser = argparse.ArgumentParser(description="Scrape Yodayo model galleries")
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--max-images", "-n", type=int, default=500)
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest")
    args = parser.parse_args()

    from configs import load_config

    config = load_config(args.config)

    scraper = YodayoScraper(config, max_images=args.max_images, force=args.force)
    asyncio.run(scraper.run_async())


if __name__ == "__main__":
    main()
