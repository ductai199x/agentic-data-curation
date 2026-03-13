"""Grok Imagine scraper — downloads images from grok.com/imagine public gallery.

Uses `POST /rest/media/post/list` with auth cookies for paginated gallery listing.
Returns direct CDN URLs — fast and complete.

Provenance: images on grok.com/imagine are 100% Grok-generated (xAI's own platform).
CDN patterns:
  - images-public.x.ai/xai-images-public/imagine/images/{UUID}.{ext}
  - images-public.x.ai/xai-images-public/mj/images/{UUID}.{ext}

Video posts are skipped — we only want still images.

Usage:
    uv run python -m scrapers.grok_imagine --config configs/grok.py --cookies data/cookies-grok.txt -n 3000
"""

import asyncio
import http.cookiejar
import random
import re
import time
from pathlib import Path

import click
from tqdm import tqdm

from configs import load_config
from scrapers.base import BaseScraper, _DONE

# grok.com REST API for paginated gallery listing
GROK_API_URL = "https://grok.com/rest/media/post/list"

# UUID regex for parsing UUIDs from text files / URLs
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


class GrokImagineScraper(BaseScraper):
    """Scrapes images from grok.com/imagine via REST API."""

    source_name = "grok_imagine"

    def __init__(
        self,
        config,
        output_dir: str | Path,
        max_images: int,
        force: bool = False,
    ):
        self.config = config
        min_pixels = getattr(config, "MIN_PIXELS", 200_000)

        super().__init__(output_dir, max_images, min_pixels=min_pixels, force=force)

        self.stats.update({
            "skipped_video": 0,
            "skipped_no_image": 0,
            "api_pages_fetched": 0,
        })

    def load_cookies(self, cookies_path: str):
        """Load Netscape-format cookies into session."""
        jar = http.cookiejar.MozillaCookieJar(cookies_path)
        jar.load(ignore_discard=True, ignore_expires=True)
        self.session.cookies.update(jar)
        tqdm.write(f"Loaded {len(jar)} cookies from {cookies_path}")

    def _fetch_api_page(self, cursor: str | None = None) -> tuple[list[dict], str | None]:
        """Fetch a page from the grok.com gallery REST API.

        Returns:
            (posts, next_cursor) — posts is a list of dicts, next_cursor is None when exhausted.
        """
        payload = {
            "limit": 40,
            "filter": {
                "source": "MEDIA_POST_SOURCE_PUBLIC",
                "safeForWork": False,
            },
        }
        if cursor:
            payload["cursor"] = cursor

        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.post(
                    GROK_API_URL,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Origin": "https://grok.com",
                        "Referer": "https://grok.com/imagine",
                    },
                    timeout=30,
                )
                if resp.status_code == 429:
                    wait = (attempt + 1) * 30
                    tqdm.write(f"  Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue
                if resp.status_code == 401:
                    tqdm.write("  Auth failed (401) — cookies may be expired")
                    return [], None
                resp.raise_for_status()
                data = resp.json()
                self.stats["api_pages_fetched"] += 1
                return data.get("posts", []), data.get("nextCursor")
            except Exception as e:
                wait = (attempt + 1) * 15
                tqdm.write(f"  API error: {e}, retrying in {wait}s...")
                time.sleep(wait)
        return [], None

    def _download_api_post(self, post: dict) -> bool:
        """Download image from an API post object."""
        media_type = post.get("mediaType", "")
        if media_type != "MEDIA_POST_TYPE_IMAGE":
            self.stats["skipped_video"] += 1
            return False

        url = post.get("mediaUrl", "")
        if not url:
            self.stats["skipped_no_image"] += 1
            return False

        post_id = post.get("id", "")
        prompt = post.get("prompt", "")[:200]
        model = post.get("modelName", "")
        r_rated = post.get("rRated", False)

        return self.download_image(
            url,
            metadata={
                "post_id": post_id,
                "post_title": prompt,
                "flair": f"grok_imagine:api:{model}" + (":nsfw" if r_rated else ""),
            },
        )

    # ── Async producer/consumer ───────────────────────────────────

    async def _produce_posts(self, post_queue: asyncio.Queue):
        """Paginated REST API producer — fetches pages and enqueues posts."""
        cursor = None
        page_num = 0
        stale_pages = 0
        api_delay = getattr(self.config, "GROK_IMAGINE_POST_DELAY", (1.0, 3.0))

        while not self._should_stop:
            posts, next_cursor = await asyncio.to_thread(self._fetch_api_page, cursor)
            page_num += 1

            if not posts:
                stale_pages += 1
                if stale_pages >= 3:
                    tqdm.write("  3 consecutive empty pages, stopping producer")
                    break
                await asyncio.sleep(random.uniform(*api_delay))
                continue

            image_posts = [p for p in posts if p.get("mediaType") == "MEDIA_POST_TYPE_IMAGE"]
            tqdm.write(f"  Page {page_num}: {len(posts)} posts ({len(image_posts)} images)")

            new_before = self.stats["downloaded"]
            for post in posts:
                if self._should_stop:
                    break
                await post_queue.put(post)

            # Track stale pages (no new downloads) after consumer processes them
            # We check based on URL dedup — if all URLs were already seen, page is stale
            url_dupes = sum(
                1 for p in posts
                if p.get("mediaUrl", "") in self.downloaded_urls
            )
            if url_dupes == len(posts):
                stale_pages += 1
                if stale_pages >= 5:
                    tqdm.write("  5 consecutive pages with no new images, stopping producer")
                    break
            else:
                stale_pages = 0

            if next_cursor is None:
                tqdm.write("  No more pages (gallery exhausted)")
                break
            cursor = next_cursor
            await asyncio.sleep(random.uniform(*api_delay))

        await post_queue.put(_DONE)

    async def _consume_posts(self, post_queue: asyncio.Queue):
        """Consumer — downloads images from queued posts with progress bar."""
        pbar = tqdm(
            total=self.max_images,
            initial=self.stats["downloaded"],
            desc="Downloading",
            unit="img",
        )

        while True:
            post = await post_queue.get()
            if post is _DONE:
                post_queue.task_done()
                break

            if self._should_stop:
                post_queue.task_done()
                continue  # drain queue without downloading

            success = await asyncio.to_thread(self._download_api_post, post)
            if success:
                pbar.update(1)
            post_queue.task_done()

        pbar.close()

    async def run_async(self, cookies_path: str):
        """Async entry point — producer/consumer pipeline."""
        self._setup_signals()
        self.load_cookies(cookies_path)

        tqdm.write(f"\nStarting Grok Imagine API scraper (target: {self.max_images} images)")
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")

        post_queue = asyncio.Queue(maxsize=200)

        producer = asyncio.create_task(self._produce_posts(post_queue))
        consumer = asyncio.create_task(self._consume_posts(post_queue))

        await asyncio.gather(producer, consumer)
        self.print_stats()

    def run(self, cookies_path: str):
        """Sync entry point — wraps run_async()."""
        asyncio.run(self.run_async(cookies_path))


@click.command()
@click.option(
    "--config", "-c", required=True, type=click.Path(exists=True),
    help="Generator config file (e.g. configs/grok.py)",
)
@click.option(
    "--output", "-o", default=None,
    help="Output directory (default: data/<generator>)",
)
@click.option(
    "--max-images", "-n", type=int, default=3000,
    help="Max images to download",
)
@click.option(
    "--cookies", required=True, type=click.Path(exists=True),
    help="Netscape cookie file for grok.com API auth",
)
@click.option("--force", is_flag=True, default=False, help="Ignore manifest, re-download everything")
def main(config, output, max_images, cookies, force):
    """Scrape images from grok.com/imagine via REST API.

    Resumes by default — skips URLs already in the manifest.
    Use --force to re-download everything.

    Examples:

        uv run python -m scrapers.grok_imagine -c configs/grok.py --cookies data/cookies-grok.txt -n 3000
    """
    cfg = load_config(config)
    output = output or f"data/{cfg.NAME}"

    scraper = GrokImagineScraper(cfg, output_dir=output, max_images=max_images, force=force)
    scraper.run(cookies)


if __name__ == "__main__":
    main()
