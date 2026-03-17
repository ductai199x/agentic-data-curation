"""X.com/Twitter scraper — async producer/consumer pipeline.

Architecture:
  Producers push work into asyncio.Queues, consumers pull and process.
  All stages run concurrently — no phase waits for another to complete.

  media_timeline_producer ─────────URLs──┐
                                         ├──→ url_queue ──→ download_consumer
  direct_search_producer (from:bot) ─────┘

  Media timeline uses gallery-dl (single bulk call).
  Direct search uses Playwright to search `from:bot filter:images` with daily
  date windows (until:YYYY-MM-DD), extracting image URLs directly from results.
  Every result is a bot image — no thread checking needed.

Usage:
    uv run python -m scrapers.twitter -c configs/grok.py -n 5000
    uv run python -m scrapers.twitter -c configs/grok.py -n 5000 --skip-media
"""

import asyncio
import io
import json
import logging
import random
import re
from pathlib import Path
from urllib.parse import quote

import sys

import click
from gallery_dl import config as gdl_config, job as gdl_job
from tqdm import tqdm


def _log(msg: str) -> None:
    """Write a log line that's visible even when output is piped."""
    tqdm.write(msg)
    sys.stdout.flush()
    sys.stderr.flush()

from configs import load_config
from scrapers.base import BaseScraper, _DONE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync building blocks (run via asyncio.to_thread behind gdl_lock)
# ---------------------------------------------------------------------------

def _scrape_media_timeline(
    media_url: str, cookies_path: str, limit: int = 2000,
) -> list[str]:
    """Scrape a bot's media timeline via gallery-dl. Returns image URLs."""
    gdl_config.clear()
    gdl_config.set((), "cookies", cookies_path)
    gdl_config.set(("extractor",), "input", False)
    gdl_config.set(("extractor", "twitter"), "ratelimit", "wait")
    gdl_config.set(("extractor",), "range", f"1-{limit}")

    datajob = gdl_job.DataJob(media_url, file=io.StringIO())
    datajob.run()

    urls = []
    for url in getattr(datajob, "data_urls", []):
        if "name=orig" in url:
            urls.append(url)
        elif url.startswith("http") and any(
            url.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")
        ):
            urls.append(url)
    return urls


def _parse_cookies_txt(cookies_path: str) -> list[dict]:
    """Parse Netscape cookies.txt into Playwright cookie dicts."""
    cookies = []
    for line in Path(cookies_path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            cookies.append({
                "name": parts[5],
                "value": parts[6],
                "domain": parts[0].lstrip("."),
                "path": parts[2],
                "secure": parts[3].upper() == "TRUE",
                "httpOnly": False,
            })
    return cookies


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class TwitterScraper(BaseScraper):
    """Async producer/consumer Twitter scraper.

    Producers:
      - media_timeline: gallery-dl @bot/media → url_queue
      - search → thread_fetch: Playwright TweetDetail interception → url_queue

    Consumer:
      - downloader: url_queue → download_image

    All stages run concurrently via asyncio tasks and queues.
    Thread fetching uses Playwright with controlled concurrency (semaphore).
    """

    source_name = "twitter"

    def __init__(
        self,
        config,
        output_dir: str | Path,
        max_images: int,
        cookies_path: str | Path | None = None,
        force: bool = False,
    ):
        self.config = config
        self.bot_username = getattr(config, "TWITTER_BOT_USERNAME", config.NAME)
        self.media_url = getattr(config, "TWITTER_MEDIA_URL", None)
        self.cookies_path = str(Path(
            cookies_path
            or getattr(config, "TWITTER_COOKIES_PATH", "data/cookies-x.txt")
        ).resolve())
        min_pixels = getattr(config, "MIN_PIXELS", 200_000)
        super().__init__(output_dir, max_images, min_pixels=min_pixels, force=force)

        self.stats.update({
            "phase0_urls": 0,
            "direct_search_images": 0,
        })

    # ── Main entry ───────────────────────────────────────────────────

    async def run_async(self):
        if not Path(self.cookies_path).exists():
            raise click.ClickException(f"Cookies not found: {self.cookies_path}")

        print(f"Twitter scraper — target: {self.max_images} images")
        print(f"  Bot: @{self.bot_username}")
        print(f"  Cookies: {self.cookies_path}")
        print(f"  Already downloaded: {len(self.downloaded_urls)} URLs")

        self._setup_signals()

        url_queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(maxsize=200)
        gdl_lock = asyncio.Lock()  # gallery-dl global config not thread-safe
        n_url_producers = 0
        tasks = []

        # Producer: media timeline → url_queue
        if self.media_url and not self._should_stop:
            n_url_producers += 1
            tasks.append(asyncio.create_task(
                self._produce_media_urls(url_queue, gdl_lock),
                name="media_timeline",
            ))

        # Producer: direct image search (from:bot filter:images → url_queue)
        if not getattr(self, 'skip_direct_search', False) and not self._should_stop:
            n_url_producers += 1
            tasks.append(asyncio.create_task(
                self._produce_direct_search_images(url_queue),
                name="direct_image_search",
            ))

        if not tasks:
            print("Nothing to do")
            return

        # Consumer: url_queue → download
        tasks.append(asyncio.create_task(
            self._download_urls(url_queue, n_url_producers),
            name="downloader",
        ))

        await asyncio.gather(*tasks)
        self.print_stats()

    # ── Producer: media timeline ─────────────────────────────────────

    async def _produce_media_urls(self, url_queue, gdl_lock):
        """Scrape @bot/media timeline and push URLs into url_queue."""
        try:
            _log(f"\n--- Producer: @{self.bot_username}/media timeline ---")
            async with gdl_lock:
                urls = await asyncio.to_thread(
                    _scrape_media_timeline,
                    self.media_url, self.cookies_path,
                    limit=self.max_images * 2,
                )
            self.stats["phase0_urls"] = len(urls)
            _log(f"  Media timeline: {len(urls)} URLs found")

            for url in urls:
                if self._should_stop:
                    break
                await url_queue.put(
                    (url, {"post_title": f"media:@{self.bot_username}"}),
                )
        finally:
            await url_queue.put(_DONE)

    # ── Producer: direct image search (from:bot filter:images) ──────

    async def _produce_direct_search_images(self, url_queue):
        """Search for bot's own image tweets and extract URLs directly.

        Uses `from:{bot} filter:images` which returns only tweets by the bot
        that contain images — 100% provenance, no thread checking needed.
        Scrolls conservatively and uses date windows to paginate through time.
        """
        from playwright.async_api import async_playwright

        # Build date-windowed queries: daily windows going back N days
        # Twitter caps results per query (~30-70), so daily = never hit scroll cap
        direct_queries = getattr(self.config, "TWITTER_DIRECT_IMAGE_QUERIES", None)
        if direct_queries is None:
            from datetime import datetime, timedelta
            base_query = f"from:{self.bot_username} filter:images"
            days_back = getattr(self.config, "TWITTER_DIRECT_SEARCH_DAYS", 365)
            today = datetime.now()
            direct_queries = [base_query]  # no date = latest
            for d in range(1, days_back + 1):
                date_str = (today - timedelta(days=d)).strftime("%Y-%m-%d")
                direct_queries.append(f"{base_query} until:{date_str}")

        search_delay = getattr(self.config, "TWITTER_SEARCH_DELAY", (3.0, 8.0))
        max_scrolls = 3  # Minimal scrolling — daily windows are narrow enough

        try:
            _log(f"\n--- Direct image search: from:{self.bot_username} filter:images ---")
            cookies = _parse_cookies_txt(self.cookies_path)

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                ctx = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                )
                await ctx.add_cookies(cookies)

                # Warm up
                warmup = await ctx.new_page()
                await warmup.goto(
                    "https://x.com/home",
                    wait_until="domcontentloaded", timeout=20000,
                )
                await asyncio.sleep(random.uniform(2, 4))
                await warmup.close()

                all_image_urls: set[str] = set()
                total_pushed = 0

                # Resume support: load last completed query index
                progress_file = Path(self.output_dir) / ".direct_search_progress"
                start_qi = 0
                if progress_file.exists() and not getattr(self, '_force', False):
                    try:
                        start_qi = int(progress_file.read_text().strip())
                        _log(f"  Resuming from query {start_qi + 1}/{len(direct_queries)}")
                    except (ValueError, OSError):
                        pass

                zero_yield_streak = 0

                for qi, query in enumerate(direct_queries):
                    if self._should_stop:
                        break

                    # Skip already-completed queries
                    if qi < start_qi:
                        continue

                    _log(f"  [{qi + 1}/{len(direct_queries)}] \"{query}\"")
                    page = await ctx.new_page()

                    try:
                        await page.goto(
                            f"https://x.com/search?q={quote(query)}&f=live",
                            wait_until="domcontentloaded", timeout=20000,
                        )
                        await asyncio.sleep(random.uniform(4, 7))

                        content = await page.content()
                        if "something went wrong" in content.lower():
                            _log(f"    BLOCKED — stopping direct search")
                            break

                        stale = 0
                        for scroll_num in range(max_scrolls):
                            await asyncio.sleep(random.uniform(*search_delay))

                            # Extract all media image URLs from the page
                            img_urls = await page.evaluate('''() => {
                                return Array.from(document.querySelectorAll('img'))
                                    .map(i => i.src)
                                    .filter(s => s.includes('pbs.twimg.com/media'))
                            }''')

                            new_count = 0
                            for img_url in img_urls:
                                # Convert to full-res orig URL
                                if "name=" in img_url:
                                    full_url = re.sub(r'name=\w+', 'name=orig', img_url)
                                else:
                                    full_url = img_url + "?format=jpg&name=orig"

                                if full_url not in all_image_urls:
                                    all_image_urls.add(full_url)
                                    new_count += 1
                                    await url_queue.put((full_url, {
                                        "post_title": f"direct_search:from:{self.bot_username}",
                                        "flair": "direct_search",
                                    }))
                                    total_pushed += 1

                            _log(
                                f"    Scroll {scroll_num + 1}/{max_scrolls}: "
                                f"+{new_count} images, {len(all_image_urls)} total"
                            )

                            if new_count == 0:
                                stale += 1
                                if stale >= 2:
                                    # Try one refresh before giving up
                                    if stale == 2:
                                        _log(f"    Refreshing page...")
                                        await page.reload(
                                            wait_until="domcontentloaded", timeout=15000,
                                        )
                                        await asyncio.sleep(random.uniform(3, 6))
                                        continue
                                    _log(f"    No new images after refresh, next query")
                                    break
                            else:
                                stale = 0

                            # Scroll down
                            await page.evaluate(
                                "window.scrollBy(0, window.innerHeight * (1.5 + Math.random()))"
                            )

                    except Exception as e:
                        _log(f"    Error: {e}")
                    finally:
                        await page.close()

                    # Save progress
                    try:
                        progress_file.write_text(str(qi + 1))
                    except OSError:
                        pass

                    # Track zero-yield queries (all images already in manifest)
                    query_new = sum(1 for u in all_image_urls
                                    if u not in self.downloaded_urls)
                    if total_pushed == 0 or query_new == 0:
                        zero_yield_streak += 1
                    else:
                        zero_yield_streak = 0

                    # If 30+ consecutive dates yield nothing new, we've caught up
                    if zero_yield_streak >= 30:
                        _log(f"  30 consecutive zero-yield dates — caught up, stopping")
                        break

                    # Pause between queries
                    if qi < len(direct_queries) - 1:
                        await asyncio.sleep(random.uniform(20, 40))

                await browser.close()

            _log(
                f"  Direct search done: {len(all_image_urls)} unique images, "
                f"{total_pushed} pushed"
            )
            self.stats["direct_search_images"] = len(all_image_urls)

        except Exception as e:
            _log(f"  Direct search error: {e}")
        finally:
            await url_queue.put(_DONE)

    # ── Consumer: download images ────────────────────────────────────

    async def _download_urls(self, url_queue, n_producers):
        """Consume URLs from queue, download images.

        Single consumer — download_image is sync (HTTP GET + manifest write).
        Runs in thread but only one at a time, so shared state is safe.
        """
        done_count = 0
        media_dl = 0
        direct_dl = 0
        thread_dl = 0

        with tqdm(desc="Downloading", unit=" img") as pbar:
            while done_count < n_producers:
                item = await url_queue.get()
                if item is _DONE:
                    done_count += 1
                    continue
                if self._should_stop:
                    continue  # drain remaining items
                url, meta = item
                result = await asyncio.to_thread(
                    self.download_image, url, metadata=meta,
                )
                if result:
                    pbar.update(1)
                    # Track source
                    flair = meta.get("flair", "")
                    title = meta.get("post_title", "")
                    if flair == "direct_search" or "direct_search" in title:
                        direct_dl += 1
                    elif "media:" in title:
                        media_dl += 1
                    else:
                        thread_dl += 1
                pbar.set_postfix(
                    dl=self.stats["downloaded"],
                    media=media_dl,
                    direct=direct_dl,
                    thread=thread_dl,
                )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--output", "-o", default=None)
@click.option("--max-images", "-n", type=int, default=500)
@click.option("--cookies", default=None)
@click.option("--force", is_flag=True, default=False)
@click.option("--skip-media", is_flag=True, default=False, help="Skip /media timeline")
@click.option("--skip-direct", is_flag=True, default=False, help="Skip direct image search")
def main(config, output, max_images, cookies, force, skip_media, skip_direct):
    """Scrape bot images from Twitter via media timeline + direct image search.

    Two producers run concurrently:
    1. Media timeline: gallery-dl @bot/media (all bot posts with images)
    2. Direct search: from:bot filter:images with daily date windows going back N days

    Both feed into a single download consumer.
    """
    cfg = load_config(config)
    output = output or f"data/{cfg.NAME}"

    scraper = TwitterScraper(
        cfg,
        output_dir=output,
        max_images=max_images,
        cookies_path=cookies,
        force=force,
    )

    if skip_media:
        scraper.media_url = None
    if skip_direct:
        scraper.skip_direct_search = True

    scraper.run()


if __name__ == "__main__":
    main()
