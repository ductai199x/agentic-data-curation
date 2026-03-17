"""AIGCArena (ByteDance MagicArena) scraper for arena-generated images.

All images are server-side arena battle generations — excellent provenance.
Uses Playwright to bypass a_bogus anti-bot, then paginates via direct API calls.

Usage:
    uv run python -m scrapers.aigcarena --config configs/seedream4.py --max-images 1000
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

from tqdm import tqdm

from scrapers.base import BaseScraper

# Models to collect (case-insensitive substring match)
SEEDREAM_SUBSTRINGS = ["seedream"]

PAGE_SIZE = 30  # API page size


class AIGCArenaScraper(BaseScraper):
    source_name = "aigcarena"

    def __init__(self, config, max_images: int = 1000, force: bool = False,
                 target_substrings: list[str] | None = None):
        output_dir = f"data/{config.NAME}"
        super().__init__(output_dir, max_images, min_pixels=getattr(config, "MIN_PIXELS", 200_000), force=force)
        self.config = config
        self.target_substrings = target_substrings or SEEDREAM_SUBSTRINGS
        self.cookies_path = Path("data/cookies-aigcarena.txt")

    def _is_target_model(self, model_name: str) -> bool:
        mn = model_name.lower()
        return any(s in mn for s in self.target_substrings)

    async def run_async(self):
        """Use Playwright to bypass anti-bot, then paginate API directly."""
        self._setup_signals()

        from playwright.async_api import async_playwright

        pbar = tqdm(desc="AIGCArena", unit="img", file=sys.stderr)
        all_resources = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            )

            if self.cookies_path.exists():
                await self._load_cookies(ctx)

            page = await ctx.new_page()
            await page.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )

            # Load page to initialize session + a_bogus
            print("Loading AIGCArena explore page...", flush=True)
            await page.goto(
                "https://aigcarena.com/explore?modality=image_gen&mode=prompt",
                wait_until="load",
                timeout=30000,
            )
            await asyncio.sleep(5)

            # Paginate through all resources via direct API calls from browser context
            page_no = 1
            total = None

            while not self._should_stop:
                result = await page.evaluate(f"""
                    async () => {{
                        const resp = await fetch("/api/evaluate/v1/arena/list_evaluate_resources", {{
                            method: "POST",
                            headers: {{"Content-Type": "application/json"}},
                            body: JSON.stringify({{
                                "RankType": 1,
                                "Scene": "T2I",
                                "OnlyMyCommented": false,
                                "Modality": "image_gen",
                                "Page": {{"PageNo": {page_no}, "PageSize": {PAGE_SIZE}}},
                                "OrderBy": {{"OrderByField": "comment_count", "Order": 2}}
                            }}),
                            credentials: "include"
                        }});
                        return await resp.json();
                    }}
                """)

                data = result.get("data", {})
                page_info = data.get("Page", {})
                if total is None:
                    total = page_info.get("Total", 0)
                    print(f"Total arena resources: {total}", flush=True)

                resources = data.get("Resources", [])
                if not resources:
                    print(f"  No more resources at page {page_no}", flush=True)
                    break

                # Filter for target models
                for res in resources:
                    model_name = res.get("ModelName", "")
                    if self._is_target_model(model_name):
                        all_resources.append(res)

                if page_no % 10 == 0:
                    print(f"  Page {page_no}: {len(all_resources)} Seedream collected", flush=True)

                page_no += 1
                max_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 100
                if page_no > max_pages:
                    print(f"  Reached last page ({max_pages})", flush=True)
                    break

                await asyncio.sleep(random.uniform(1.0, 2.0))

            await browser.close()

        print(f"\nCollected {len(all_resources)} Seedream resources. Downloading...", flush=True)

        # Download images
        for res in all_resources:
            if self.done or (hasattr(self, "_shutdown") and self._shutdown.is_set()):
                break

            model_name = res.get("ModelName", "unknown")
            model_version_id = res.get("ModelVersionId", "")

            model_images = res.get("ModelImages", [])
            if not model_images:
                continue

            img_info = model_images[0]
            url = img_info.get("ImageUri") or img_info.get("CompressionImageUri", "")
            if not url:
                continue

            if url in self.downloaded_urls:
                pbar.update(1)
                continue

            metadata = {
                "post_id": res.get("EvalResourceId", ""),
                "post_title": res.get("PromptEn", "")[:200],
                "flair": f"aigcarena:{model_name}:{model_version_id}",
                "subreddit": "",
            }

            success = self.download_image(
                url,
                source=f"aigcarena_{model_name.lower().replace(' ', '_').replace('.', '')}",
                metadata=metadata,
            )
            pbar.update(1)
            pbar.set_postfix(
                dl=self.stats["downloaded"],
                fail=self.stats["failed"],
                model=model_name[:20],
            )

            if success:
                await asyncio.sleep(random.uniform(0.3, 0.8))

        pbar.close()
        self.print_stats()

    async def _load_cookies(self, context):
        cookies = []
        with open(self.cookies_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookie = {
                        "name": parts[5],
                        "value": parts[6],
                        "domain": parts[0],
                        "path": parts[2],
                        "secure": parts[3].upper() == "TRUE",
                    }
                    if parts[4] != "0":
                        cookie["expires"] = int(parts[4])
                    cookies.append(cookie)
        if cookies:
            await context.add_cookies(cookies)
            print(f"  Loaded {len(cookies)} cookies", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Scrape AIGCArena explore page")
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--max-images", "-n", type=int, default=1000)
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest")
    args = parser.parse_args()

    from configs import load_config
    config = load_config(args.config)

    scraper = AIGCArenaScraper(config, max_images=args.max_images, force=args.force)
    asyncio.run(scraper.run_async())


if __name__ == "__main__":
    main()
