"""Reddit scraper — downloads images from subreddits and search results.

Config-driven: reads REDDIT_SUBREDDITS, REDDIT_SEARCH_QUERIES, and MIN_PIXELS
from the generator config file (e.g. configs/grok.py).

Uses async producer/consumer pattern:
- Producer: iterates subreddits x sort x time_filter, then search queries,
  fetching pages via threads and putting posts on an asyncio.Queue.
- Consumer: pulls posts, extracts image URLs, downloads via threads.

Post-level filtering (before download):
- Flair rejection: skip posts with discussion/meme/comparison flairs
- Title keyword rejection: skip posts whose titles match known meme/advocacy patterns
- Self-post skipping: skip text-only posts (discussion threads)
- Domain filtering: only download from known image hosts (i.redd.it, imgur)

Usage:
    uv run python -m scrapers.reddit --config configs/grok.py --max-images 500
"""

import asyncio
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import click
from tqdm import tqdm

from configs import load_config
from scrapers.base import BaseScraper, _DONE


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def is_image_url(url: str) -> bool:
    url_lower = url.lower().split("?")[0]
    return any(url_lower.endswith(ext) for ext in IMAGE_EXTENSIONS)


class RedditScraper(BaseScraper):
    """Scrapes images from Reddit using the public JSON API."""

    source_name = "reddit"

    def __init__(self, config, output_dir: str | Path, max_images: int, force: bool = False):
        self.config = config
        self.subreddits = getattr(config, "REDDIT_SUBREDDITS", [])
        self.search_queries = getattr(config, "REDDIT_SEARCH_QUERIES", [])
        self.request_delay = getattr(config, "REQUEST_DELAY", (1.0, 3.0))
        min_pixels = getattr(config, "MIN_PIXELS", 200_000)

        # Post filtering config
        self.reject_flairs = {f.lower() for f in getattr(config, "REDDIT_REJECT_FLAIRS", set())}
        self.require_flairs = {f.lower() for f in getattr(config, "REDDIT_REQUIRE_FLAIRS", set())}
        self.reject_title_keywords = [
            kw.lower() for kw in getattr(config, "REDDIT_REJECT_TITLE_KEYWORDS", [])
        ]
        self.allowed_image_domains = getattr(config, "REDDIT_ALLOWED_IMAGE_DOMAINS", set())
        self.skip_self_posts = getattr(config, "REDDIT_SKIP_SELF_POSTS", True)
        self.min_created_utc = getattr(config, "REDDIT_MIN_CREATED_UTC", 0)

        super().__init__(output_dir, max_images, min_pixels=min_pixels, force=force)

        self.session.headers.update({
            "Accept": "application/json",
        })
        self.stats.update({
            "fetched_posts": 0,
            "skipped_flair": 0,
            "skipped_flair_not_required": 0,
            "skipped_title": 0,
            "skipped_self_post": 0,
            "skipped_domain": 0,
            "skipped_too_old": 0,
        })

    # ── Sync helpers (run in threads) ─────────────────────────────

    def _fetch_json(self, url: str, params: dict | None = None) -> dict | None:
        """Fetch JSON from Reddit API with rate limiting and error handling.

        Runs in a thread via asyncio.to_thread() — time.sleep is fine here.
        """
        try:
            time.sleep(random.uniform(*self.request_delay))
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                tqdm.write(f"  Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            tqdm.write(f"  Error fetching {url}: {e}")
            return None

    def _extract_image_urls(self, post: dict) -> list[str]:
        """Extract all image URLs from a Reddit post."""
        urls = []
        data = post.get("data", post)

        # Direct image link (i.redd.it)
        url = data.get("url", "")
        if is_image_url(url):
            urls.append(url)

        # Reddit gallery (multiple images)
        if data.get("is_gallery") and "media_metadata" in data:
            for media_id, media in data["media_metadata"].items():
                if media.get("status") == "valid" and media.get("e") == "Image":
                    img_url = media.get("s", {}).get("u", "")
                    if img_url:
                        urls.append(img_url.replace("&amp;", "&"))

        # Preview images (fallback)
        if not urls and "preview" in data:
            for img_data in data["preview"].get("images", []):
                img_url = img_data.get("source", {}).get("url", "")
                if img_url:
                    urls.append(img_url.replace("&amp;", "&"))

        return urls

    # ── Post filtering ────────────────────────────────────────────

    def _should_skip_post(self, post_data: dict) -> str | None:
        """Check if a post should be skipped based on config filters.

        Returns rejection reason string, or None if post is acceptable.
        """
        # Date gate — skip posts before cutoff (e.g. DALL-E 3 era)
        created = post_data.get("created_utc", 0)
        if self.min_created_utc and created < self.min_created_utc:
            return "too_old"

        # Self-post check (text-only discussion threads)
        if self.skip_self_posts and post_data.get("is_self", False):
            return "self_post"

        # Flair check — require specific flairs if configured
        flair = (post_data.get("link_flair_text") or "").strip().lower()
        if self.require_flairs:
            if not flair or flair not in self.require_flairs:
                return f"flair_not_required:{flair or 'none'}"

        # Flair rejection
        if flair and self.reject_flairs and flair in self.reject_flairs:
            return f"flair:{flair}"

        # Title keyword check
        title = (post_data.get("title") or "").lower()
        for kw in self.reject_title_keywords:
            if kw in title:
                return f"title_keyword:{kw.strip()}"

        return None

    def _filter_urls_by_domain(self, urls: list[str]) -> list[str]:
        """Filter image URLs to only allowed domains.

        Returns filtered list. If no domain allowlist is configured, returns all URLs.
        """
        if not self.allowed_image_domains:
            return urls
        filtered = []
        for url in urls:
            domain = urlparse(url).hostname or ""
            if domain in self.allowed_image_domains:
                filtered.append(url)
        return filtered

    # ── Async producer/consumer ───────────────────────────────────

    async def run_async(self):
        """Async entry point — producer/consumer with graceful shutdown."""
        self._setup_signals()

        tqdm.write(f"Starting Reddit scraper (target: {self.max_images} images)")
        tqdm.write(f"Subreddits: {', '.join(self.subreddits)}")
        tqdm.write(f"Search queries: {len(self.search_queries)}")
        tqdm.write(f"Already downloaded: {len(self.downloaded_urls)} URLs")
        tqdm.write(f"Filters: {len(self.reject_flairs)} rejected flairs, "
                   f"{len(self.reject_title_keywords)} title keywords, "
                   f"self-post skip={self.skip_self_posts}, "
                   f"{len(self.allowed_image_domains)} allowed domains")

        post_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        producer = asyncio.create_task(self._produce_posts(post_queue))
        consumer = asyncio.create_task(self._consume_posts(post_queue))

        await asyncio.gather(producer, consumer)
        self.print_stats()

    async def _produce_posts(self, post_queue: asyncio.Queue):
        """Iterate subreddits and search queries, fetching pages and enqueuing posts.

        Each item on the queue is a (post_dict, metadata_context) tuple.
        Puts _DONE sentinel when finished.
        """
        try:
            # Phase 1: Subreddit listings
            for sub in self.subreddits:
                if self._should_stop:
                    break
                for sort in ["new", "hot", "top", "rising"]:
                    if self._should_stop:
                        break
                    for tf in ["all", "year", "month", "week"]:
                        if self._should_stop:
                            break
                        await self._produce_listing(
                            post_queue,
                            url=f"https://www.reddit.com/r/{sub}/{sort}.json",
                            label=f"r/{sub} ({sort}/{tf})",
                            base_params={"t": tf},
                            page_limit=500,
                        )

            # Phase 2: Search queries
            for query in self.search_queries:
                if self._should_stop:
                    break
                for sort in ["relevance", "new", "top"]:
                    if self._should_stop:
                        break
                    for tf in ["all", "year", "month"]:
                        if self._should_stop:
                            break
                        await self._produce_listing(
                            post_queue,
                            url="https://www.reddit.com/search.json",
                            label=f"Search: '{query}' ({sort}/{tf})",
                            base_params={"q": query, "sort": sort, "type": "link", "t": tf},
                            page_limit=500,
                        )
        finally:
            await post_queue.put(_DONE)

    async def _produce_listing(
        self,
        post_queue: asyncio.Queue,
        url: str,
        label: str,
        base_params: dict,
        page_limit: int,
    ):
        """Paginate a single Reddit listing (subreddit or search), enqueuing posts."""
        tqdm.write(f"\n--- {label} ---")
        after = None
        fetched = 0

        while fetched < page_limit and not self._should_stop:
            params = {**base_params, "limit": min(100, page_limit - fetched)}
            if after:
                params["after"] = after

            data = await asyncio.to_thread(self._fetch_json, url, params)
            if not data:
                break

            posts = data.get("data", {}).get("children", [])
            if not posts:
                break

            self.stats["fetched_posts"] += len(posts)
            fetched += len(posts)

            for post in posts:
                if self._should_stop:
                    break
                post_data = post.get("data", post)
                metadata = {
                    "post_id": post_data.get("id", ""),
                    "post_title": post_data.get("title", ""),
                    "subreddit": post_data.get("subreddit", ""),
                    "flair": post_data.get("link_flair_text", ""),
                }
                await post_queue.put((post, metadata))

            after = data.get("data", {}).get("after")
            if not after:
                break

    async def _consume_posts(self, post_queue: asyncio.Queue):
        """Pull posts from queue, filter, extract image URLs, download images."""
        pbar = tqdm(total=self.max_images, desc="Reddit", unit="img",
                    initial=self.stats["downloaded"])

        while True:
            item = await post_queue.get()
            if item is _DONE:
                break

            post, metadata = item

            if self._should_stop:
                # Drain remaining items to unblock producer
                post_queue.task_done()
                continue

            data = post.get("data", post)
            if data.get("is_video", False):
                self.stats["skipped_video"] += 1
                post_queue.task_done()
                continue

            # Post-level filtering (flair, title keywords, self-posts)
            skip_reason = self._should_skip_post(data)
            if skip_reason:
                if skip_reason == "self_post":
                    self.stats["skipped_self_post"] += 1
                elif skip_reason == "too_old":
                    self.stats["skipped_too_old"] += 1
                elif skip_reason.startswith("flair_not_required:"):
                    self.stats["skipped_flair_not_required"] += 1
                elif skip_reason.startswith("flair:"):
                    self.stats["skipped_flair"] += 1
                elif skip_reason.startswith("title_keyword:"):
                    self.stats["skipped_title"] += 1
                post_queue.task_done()
                continue

            urls = self._extract_image_urls(post)

            # Domain filtering
            pre_filter_count = len(urls)
            urls = self._filter_urls_by_domain(urls)
            self.stats["skipped_domain"] += pre_filter_count - len(urls)

            for url in urls:
                if self._should_stop:
                    break
                ok = await asyncio.to_thread(self.download_image, url, "", metadata)
                if ok:
                    pbar.update(1)

            post_queue.task_done()

        pbar.close()


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True), help="Generator config file")
@click.option("--output", "-o", default=None, help="Output directory (default: data/<generator>)")
@click.option("--max-images", "-n", type=int, default=1000, help="Max images to download")
@click.option("--force", is_flag=True, default=False, help="Ignore manifest, re-download everything")
def main(config, output, max_images, force):
    """Scrape images from Reddit based on generator config."""
    cfg = load_config(config)
    output = output or f"data/{cfg.NAME}"
    scraper = RedditScraper(cfg, output_dir=output, max_images=max_images, force=force)
    scraper.run()


if __name__ == "__main__":
    main()
