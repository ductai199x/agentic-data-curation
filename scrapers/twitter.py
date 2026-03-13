"""X.com/Twitter scraper — async producer/consumer pipeline.

Architecture:
  Producers push work into asyncio.Queues, consumers pull and process.
  All stages run concurrently — no phase waits for another to complete.

  media_timeline_producer ──URLs──┐
                                  ├──→ url_queue ──→ download_consumer
  search_producer ──IDs──→ thread_fetcher ──URLs──┘

  Thread fetching uses Playwright to intercept TweetDetail GraphQL responses.
  Media timeline uses gallery-dl (single bulk call, no concurrency issue).

Usage:
    uv run python -m scrapers.twitter -c configs/grok.py -n 500
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


def _extract_bot_images_from_tweet_detail(
    data: dict, bot_username: str,
) -> list[tuple[str, dict]]:
    """Extract bot's photo URLs from a TweetDetail GraphQL response.

    Recursively walks the response JSON looking for tweets by bot_username
    that contain photo media. Returns (url, metadata) tuples.
    """
    results = []
    bot_lower = bot_username.lower()

    def _walk(obj):
        if isinstance(obj, dict):
            # Check if this dict contains a tweet_results with the bot's media
            tr = obj.get("tweet_results", {}).get("result", {})
            if tr and isinstance(tr, dict):
                core = tr.get("core", {}).get("user_results", {}).get("result", {})
                sn = (
                    core.get("core", {}).get("screen_name", "")
                    or core.get("legacy", {}).get("screen_name", "")
                )
                if sn.lower() == bot_lower:
                    legacy = tr.get("legacy", {})
                    media_list = legacy.get("extended_entities", {}).get("media", [])
                    for m in media_list:
                        if m.get("type") == "photo":
                            murl = m.get("media_url_https", "")
                            if murl:
                                # Build orig-quality URL
                                url = murl + "?format=jpg&name=orig"
                                conv_id = legacy.get("conversation_id_str", "")
                                reply_to = legacy.get("in_reply_to_screen_name", "")
                                tweet_id = legacy.get("id_str", "")
                                results.append((url, {
                                    "tweet_id": tweet_id,
                                    "conversation_id": conv_id,
                                    "reply_to": reply_to,
                                }))
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)

    _walk(data)
    return results


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
        search_queries: list[str] | None = None,
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

        self.search_queries = (
            search_queries
            or getattr(config, "TWITTER_SEARCH_QUERIES", [])
            or [f"@{self.bot_username} generate"]
        )
        self.seen_tweets: set[str] = set()
        self.stats.update({
            "phase0_urls": 0,
            "search_ids": 0,
            "threads_checked": 0,
            "bot_replies_found": 0,
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

        # Producer pipeline: search → tweet_id_queue → thread_fetch → url_queue
        if self.search_queries and not self._should_stop:
            n_url_producers += 1
            tweet_id_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=100)
            tasks.append(asyncio.create_task(
                self._search_and_fetch(tweet_id_queue, url_queue),
                name="search_and_fetch",
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

    # ── Search + thread fetch (shared browser) ──────────────────────

    async def _search_and_fetch(self, tweet_id_queue, url_queue):
        """Search for tweets and fetch threads using a single shared browser.

        Launches one Playwright browser with two contexts:
        - Search context: scrolls search results, pushes tweet IDs
        - Thread context: workers fetch tweet pages, extract bot images

        Both run concurrently so thread fetching starts immediately as
        search finds IDs.
        """
        from playwright.async_api import async_playwright

        try:
            _log(f"\n--- Search + fetch (shared browser) ---")
            cookies = _parse_cookies_txt(self.cookies_path)

            async with async_playwright() as p:
                _log("  Launching Playwright browser...")
                browser = await p.chromium.launch(headless=True)

                ua = (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                )
                vp = {"width": 1920, "height": 1080}

                # Two contexts from one browser
                search_ctx = await browser.new_context(user_agent=ua, viewport=vp)
                await search_ctx.add_cookies(cookies)
                thread_ctx = await browser.new_context(user_agent=ua, viewport=vp)
                await thread_ctx.add_cookies(cookies)

                # Warm up both contexts in parallel
                _log("  Warming up sessions...")

                async def _warmup(ctx, label):
                    page = await ctx.new_page()
                    await page.goto(
                        "https://x.com/home",
                        wait_until="domcontentloaded", timeout=20000,
                    )
                    await asyncio.sleep(random.uniform(2, 4))
                    await page.close()
                    _log(f"    {label} ready")

                await asyncio.gather(
                    _warmup(search_ctx, "search"),
                    _warmup(thread_ctx, "threads"),
                )

                # Run search producer + thread workers concurrently
                _log("  Starting search + thread workers")
                await asyncio.gather(
                    self._produce_search_ids(search_ctx, tweet_id_queue),
                    self._fetch_threads(thread_ctx, tweet_id_queue, url_queue),
                )

                await browser.close()
        finally:
            await url_queue.put(_DONE)

    async def _produce_search_ids(self, context, tweet_id_queue):
        """Search Twitter via Playwright, push tweet IDs as they're found."""
        try:
            _log(
                f"  Searching {len(self.search_queries)} queries..."
            )
            all_ids: set[str] = set()

            for qi, query in enumerate(self.search_queries):
                if self._should_stop:
                    break
                _log(
                    f"  [{qi + 1}/{len(self.search_queries)}] \"{query}\""
                )

                pushed = await self._search_single_query(
                    context, query, tweet_id_queue, all_ids,
                    max_scrolls=40,
                )

                _log(
                    f"    query done: {pushed} new IDs pushed, "
                    f"{len(all_ids)} total unique"
                )

                # Long pause between queries to avoid detection
                if qi < len(self.search_queries) - 1:
                    await asyncio.sleep(random.uniform(15, 30))

            self.stats["search_ids"] = len(all_ids)
            _log(f"  Search complete: {len(all_ids)} unique tweet IDs")
        finally:
            await tweet_id_queue.put(_DONE)

    async def _search_single_query(
        self, context, query: str, tweet_id_queue, all_ids: set[str],
        max_scrolls: int = 40,
    ) -> int:
        """Search one query, push new tweet IDs to queue as found.

        Returns number of new IDs pushed.
        """
        page = await context.new_page()
        url = f"https://x.com/search?q={quote(query)}&f=live"
        pushed = 0

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(random.uniform(3, 5))

            content = await page.content()
            if "something went wrong" in content.lower():
                logger.warning(f"Search blocked for query: {query}")
                return 0

            try:
                await page.wait_for_selector(
                    'article[data-testid="tweet"]', timeout=10000,
                )
            except Exception:
                return 0

            query_ids: set[str] = set()
            stale_count = 0

            _log(f"  Search '{query}': starting (max {max_scrolls} scrolls)")

            for scroll_num in range(max_scrolls):
                # Human-like pause before extracting
                await asyncio.sleep(random.uniform(5, 10))

                async def _extract_ids():
                    links = await page.query_selector_all('a[href*="/status/"]')
                    for link in links:
                        href = await link.get_attribute("href") or ""
                        m = re.search(r"/status/(\d+)", href)
                        if m:
                            query_ids.add(m.group(1))

                await _extract_ids()
                prev = len(query_ids)

                # Smooth scroll instead of jumping to bottom
                await page.evaluate(
                    "window.scrollBy(0, window.innerHeight * (1.5 + Math.random()))"
                )
                await asyncio.sleep(random.uniform(5, 10))

                # Re-extract after scroll
                await _extract_ids()

                new_this_scroll = len(query_ids) - prev

                # Push new IDs to queue immediately
                for tid in query_ids:
                    if tid not in all_ids:
                        all_ids.add(tid)
                        await tweet_id_queue.put(tid)
                        pushed += 1

                _log(
                    f"  Search scroll {scroll_num + 1}/{max_scrolls}: "
                    f"+{new_this_scroll} IDs, {pushed} pushed, "
                    f"{len(query_ids)} total"
                )

                if new_this_scroll == 0:
                    stale_count += 1
                    if stale_count >= 3:
                        _log(f"  Search '{query}': 3 stale scrolls, stopping")
                        break
                else:
                    stale_count = 0

                # Occasional longer pause to mimic reading
                if scroll_num > 0 and scroll_num % 10 == 0:
                    await asyncio.sleep(random.uniform(10, 20))

            _log(f"  Search '{query}': done — {len(query_ids)} IDs, {pushed} pushed")
            return pushed

        finally:
            await page.close()

    # ── Transformer: tweet IDs → thread fetch → URLs ────────────────

    async def _fetch_threads(self, context, tweet_id_queue, url_queue):
        """Consume tweet IDs, fetch conversation threads via Playwright.

        Opens tweet pages in Playwright, intercepts TweetDetail GraphQL
        responses, and extracts bot image URLs. Uses N concurrent workers
        with rate-limit delays between requests.
        """
        n_workers = 3
        max_scrolls = 5
        producer_done = asyncio.Event()

        async def _worker(ctx, worker_id: int):
            """Single worker: pull tweet IDs, load pages, extract images."""
            logger.debug(f"Worker {worker_id}: started")
            try:
                while not (producer_done.is_set() and tweet_id_queue.empty()):
                    if self._should_stop:
                        break

                    try:
                        tid = await asyncio.wait_for(
                            tweet_id_queue.get(), timeout=2.0,
                        )
                    except asyncio.TimeoutError:
                        continue

                    if tid is _DONE:
                        producer_done.set()
                        break

                    if tid in self.seen_tweets:
                        continue
                    self.seen_tweets.add(tid)
                    self.stats["threads_checked"] += 1

                    # Fetch this thread
                    found_images: list[tuple[str, dict]] = []

                    async def handle_response(response):
                        if "TweetDetail" not in response.url:
                            return
                        try:
                            body = await response.json()
                            imgs = _extract_bot_images_from_tweet_detail(
                                body, self.bot_username,
                            )
                            found_images.extend(imgs)
                        except Exception:
                            pass

                    page = await ctx.new_page()
                    page.on("response", handle_response)
                    try:
                        await page.goto(
                            f"https://x.com/i/status/{tid}",
                            wait_until="domcontentloaded",
                            timeout=20000,
                        )
                        await asyncio.sleep(random.uniform(2, 4))

                        # Scroll to trigger more TweetDetail loads if needed
                        for _ in range(max_scrolls):
                            if found_images or self._should_stop:
                                break
                            await page.evaluate(
                                "window.scrollBy(0, window.innerHeight * 1.5)"
                            )
                            await asyncio.sleep(random.uniform(1.5, 3))
                    except Exception as e:
                        _log(f"    Worker {worker_id} thread {tid}: ERROR {e}")
                    finally:
                        await page.close()

                    # Push found images to url_queue
                    for url_str, meta in found_images:
                        self.stats["bot_replies_found"] += 1
                        await url_queue.put((url_str, {
                            "post_id": meta.get("tweet_id", ""),
                            "post_title": f"conv:{meta.get('conversation_id', '')}",
                            "flair": f"reply_to:{meta.get('reply_to', '')}",
                        }))

                    # Per-thread logging
                    checked = self.stats["threads_checked"]
                    found = self.stats["bot_replies_found"]
                    hit = f"+{len(found_images)} img" if found_images else "no reply"
                    _log(
                        f"  [{checked}] thread {tid}: {hit} "
                        f"(total: {found} replies)"
                    )

                    # Rate-limit delay between requests
                    await asyncio.sleep(random.uniform(2, 5))

            except Exception as e:
                _log(f"    Worker {worker_id}: CRASHED — {e}")

        _log(f"  Thread workers: {n_workers} workers ready")
        workers = [
            asyncio.create_task(_worker(context, i), name=f"worker-{i}")
            for i in range(n_workers)
        ]
        await asyncio.gather(*workers)

        _log(
            f"  Threads done: {self.stats['threads_checked']} checked, "
            f"{self.stats['bot_replies_found']} bot replies found"
        )

    # ── Consumer: download images ────────────────────────────────────

    async def _download_urls(self, url_queue, n_producers):
        """Consume URLs from queue, download images.

        Single consumer — download_image is sync (HTTP GET + manifest write).
        Runs in thread but only one at a time, so shared state is safe.
        """
        done_count = 0

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
                pbar.set_postfix(
                    dl=self.stats["downloaded"],
                    replies=self.stats["bot_replies_found"],
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
@click.option("--queries", "-q", multiple=True, help="Override search queries")
@click.option(
    "--skip-media", is_flag=True, default=False, help="Skip media timeline",
)
@click.option(
    "--skip-search", is_flag=True, default=False, help="Skip search + threads",
)
def main(config, output, max_images, cookies, force, queries, skip_media, skip_search):
    """Scrape bot images from Twitter via media timeline + conversation threads."""
    cfg = load_config(config)
    output = output or f"data/{cfg.NAME}"

    scraper = TwitterScraper(
        cfg,
        output_dir=output,
        max_images=max_images,
        cookies_path=cookies,
        force=force,
        search_queries=list(queries) if queries else None,
    )

    if skip_media:
        scraper.media_url = None
    if skip_search:
        scraper.search_queries = []

    scraper.run()


if __name__ == "__main__":
    main()
