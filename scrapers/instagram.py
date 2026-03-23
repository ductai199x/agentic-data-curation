"""Instagram profile scraper for AI influencer images.

Uses Playwright with stealth mode to browse Instagram profiles, collect post
links from the grid, then visit each post to extract full-res image URLs.
CDN URLs expire quickly so images are downloaded immediately on extraction.

Requires Netscape-format cookies (logged-in Instagram session).

VERY conservative rate limiting — Instagram bans aggressively.

Usage:
    uv run python -m scrapers.instagram --config configs/instagram_ai_influencer.py --max-images 1000
    uv run python -m scrapers.instagram --usernames fit_aitana,millasofiaa --max-images 200
"""

import argparse
import asyncio
import http.cookiejar
import random
import re
import sys

from tqdm import tqdm

from scrapers.base import BaseScraper


class InstagramScraper(BaseScraper):
    source_name = "instagram"

    def __init__(
        self,
        config=None,
        usernames: list[str] | None = None,
        cookies_path: str | None = None,
        max_images: int = 500,
        max_per_user: int = 500,
        output_dir: str | None = None,
        force: bool = False,
    ):
        out = output_dir or (f"data/{config.NAME}" if config else "data/instagram_ai_influencer")
        min_px = getattr(config, "MIN_PIXELS", 200_000) if config else 200_000
        super().__init__(out, max_images, min_pixels=min_px, force=force)

        self.config = config
        self.max_per_user = max_per_user

        # Build set of already-downloaded post_ids for fast skipping
        self._downloaded_post_ids: set[str] = set()
        manifest_path = self.output_dir / "manifest.csv"
        if manifest_path.exists() and not force:
            import csv
            with open(manifest_path) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    pid = row.get("post_id", "")
                    if pid:
                        self._downloaded_post_ids.add(pid)
            if self._downloaded_post_ids:
                print(f"Loaded {len(self._downloaded_post_ids)} post_ids for fast-skip")

        # Build username → tier mapping (if config has tiers)
        self._user_tier: dict[str, str] = {}
        if config and hasattr(config, "INSTAGRAM_TIERS"):
            for tier, accounts in config.INSTAGRAM_TIERS.items():
                for acct in accounts:
                    self._user_tier[acct] = tier

        # Resolve usernames
        if usernames:
            self.usernames = usernames
        elif config and hasattr(config, "INSTAGRAM_USERNAMES"):
            self.usernames = config.INSTAGRAM_USERNAMES
        else:
            self.usernames = []

        # Resolve cookies path
        if cookies_path:
            self.cookies_path = cookies_path
        elif config and hasattr(config, "INSTAGRAM_COOKIES_PATH"):
            self.cookies_path = config.INSTAGRAM_COOKIES_PATH
        else:
            self.cookies_path = "data/cookies-instagram.txt"

    def _load_cookies(self) -> list[dict]:
        """Load Netscape-format cookies and convert to Playwright format."""
        cj = http.cookiejar.MozillaCookieJar(self.cookies_path)
        cj.load(ignore_discard=True, ignore_expires=True)

        pw_cookies = []
        for cookie in cj:
            pw_cookie = {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
            }
            if cookie.expires:
                pw_cookie["expires"] = cookie.expires
            pw_cookie["secure"] = cookie.secure
            pw_cookie["httpOnly"] = bool(cookie.get_nonstandard_attr("HttpOnly"))
            pw_cookies.append(pw_cookie)
        return pw_cookies

    async def run_async(self):
        """Scrape Instagram profiles using Playwright."""
        self._setup_signals()

        if not self.usernames:
            print("No usernames specified — nothing to scrape.", flush=True)
            return

        from playwright.async_api import async_playwright

        pbar = tqdm(desc="Instagram", unit="img", file=sys.stderr)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )

            # Stealth: override navigator.webdriver
            await ctx.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )

            # Load cookies into browser context
            try:
                pw_cookies = self._load_cookies()
                await ctx.add_cookies(pw_cookies)
                print(f"Loaded {len(pw_cookies)} cookies from {self.cookies_path}", flush=True)
            except Exception as e:
                print(f"Failed to load cookies: {e}", flush=True)
                print("Proceeding without cookies (may hit login wall)", flush=True)

            page = await ctx.new_page()

            for i, username in enumerate(self.usernames):
                if self._should_stop or self.done:
                    break

                if i > 0:
                    pause = random.uniform(25, 35)
                    print(f"\nPausing {pause:.0f}s between usernames...", flush=True)
                    await asyncio.sleep(pause)

                await self._scrape_user(page, username, pbar)

            await browser.close()

        pbar.close()
        self.print_stats()

    async def _scrape_user(self, page, username: str, pbar):
        """Scrape a single Instagram user profile by scrolling and extracting grid images."""
        user_downloaded = 0
        profile_url = f"https://www.instagram.com/{username}/"

        # If tiers exist, save to staging/<tier>/ instead of staging/
        tier = self._user_tier.get(username)
        if tier:
            tier_dir = self.output_dir / "staging" / tier
            tier_dir.mkdir(parents=True, exist_ok=True)
            self._original_staging = self.staging_dir
            self.staging_dir = tier_dir

        print(f"\nScraping @{username}: {profile_url}" +
              (f" [tier={tier}]" if tier else ""), flush=True)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  Failed to load profile @{username}: {e}", flush=True)
            return

        # Wait for images to render
        await asyncio.sleep(10)

        # Check for login wall or 404
        page_text = await page.text_content("body") or ""
        if "Log in" in page_text and "Sign up" in page_text and len(page_text) < 2000:
            print(f"  Login wall detected for @{username} — skipping", flush=True)
            return
        if "Sorry, this page isn't available" in page_text:
            print(f"  Profile @{username} not found (404) — skipping", flush=True)
            return

        # Scroll and collect images directly from the grid
        # Instagram loads full-res images in the DOM as you scroll
        seen_urls: set[str] = set()
        stale_scrolls = 0
        max_stale = 6
        scroll_count = 0
        max_scrolls = 300
        last_height = 0
        aggressive_phase = False

        while stale_scrolls < max_stale and scroll_count < max_scrolls:
            if self._should_stop or self.done or user_downloaded >= self.max_per_user:
                break

            # Extract all CDN images > 200px currently in DOM
            new_imgs = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('img')).filter(i => {
                    const s = i.src || '';
                    return (s.includes('cdninstagram.com') || s.includes('fbcdn.net'))
                        && (i.naturalWidth > 200 || i.width > 200);
                }).map(i => {
                    // Prefer largest srcset entry
                    let bestUrl = i.src;
                    let bestW = i.naturalWidth || i.width || 0;
                    const srcset = i.srcset || '';
                    if (srcset) {
                        const parts = srcset.split(',').map(s => s.trim());
                        for (const part of parts) {
                            const tokens = part.split(/\\s+/);
                            const url = tokens[0];
                            const w = parseInt(tokens[1]) || 0;
                            if (w > bestW) { bestW = w; bestUrl = url; }
                        }
                    }
                    return {url: bestUrl, w: i.naturalWidth, h: i.naturalHeight};
                });
            }""")

            new_count = 0
            for img in new_imgs:
                url = img["url"]
                if url in seen_urls or url in self.downloaded_urls:
                    continue
                # Skip profile pics and tiny images
                if img["w"] < 300 and img["h"] < 300:
                    continue
                seen_urls.add(url)
                new_count += 1

                # Download immediately
                flair = f"instagram:{username}:{tier}" if tier else f"instagram:{username}"
                metadata = {
                    "post_id": "",
                    "post_title": "",
                    "flair": flair,
                    "subreddit": "",
                    "post_date": "",
                }

                success = self.download_image(
                    url, source=f"instagram:{username}", metadata=metadata
                )
                pbar.update(1)
                pbar.set_postfix(
                    dl=self.stats["downloaded"],
                    fail=self.stats["failed"],
                    user=username,
                    scroll=scroll_count,
                )

                if success:
                    user_downloaded += 1

                if self.done or user_downloaded >= self.max_per_user:
                    break

            # Check scroll position
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == last_height and new_count == 0:
                stale_scrolls += 1
            else:
                stale_scrolls = 0
                aggressive_phase = False
            last_height = current_height

            # After 3 stale scrolls, switch to aggressive mode
            if stale_scrolls >= 3 and not aggressive_phase:
                aggressive_phase = True

            if aggressive_phase:
                await page.evaluate("window.scrollBy(0, -500)")
                await asyncio.sleep(0.5)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight + 100)")
                scroll_delay = random.uniform(3, 5)
            else:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_delay = random.uniform(4, 7)

            scroll_count += 1
            await asyncio.sleep(scroll_delay)

        print(f"  @{username}: {user_downloaded} images downloaded, {scroll_count} scrolls", flush=True)

        # Restore original staging dir if we swapped for tier
        if tier and hasattr(self, '_original_staging'):
            self.staging_dir = self._original_staging

    async def _collect_post_links(self, page, username: str) -> list[str]:
        """Scroll the profile grid and collect all unique post links."""
        post_links: list[str] = []
        seen_hrefs: set[str] = set()
        post_link_re = re.compile(r"(/p/[A-Za-z0-9_-]+/?)")
        reel_link_re = re.compile(r"^/reel/[A-Za-z0-9_-]+/?$")

        stale_scrolls = 0
        max_stale = 6
        last_height = 0
        aggressive_phase = False

        scroll_count = 0
        max_scrolls = 300  # Safety cap

        while stale_scrolls < max_stale and scroll_count < max_scrolls:
            if self._should_stop or self.done:
                break

            # Extract post links currently in DOM
            anchors = await page.query_selector_all("a[href]")
            new_this_round = 0
            for a in anchors:
                href = await a.get_attribute("href")
                if not href:
                    continue
                m = post_link_re.search(href)
                if m and m.group(1) not in seen_hrefs:
                    seen_hrefs.add(m.group(1))
                    post_links.append(m.group(1))
                    new_this_round += 1

            # Check scroll position
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == last_height and new_this_round == 0:
                stale_scrolls += 1
            else:
                stale_scrolls = 0
                aggressive_phase = False
            last_height = current_height

            # After 3 stale scrolls, switch to aggressive mode
            if stale_scrolls >= 3 and not aggressive_phase:
                aggressive_phase = True

            if aggressive_phase:
                # Scroll up a bit then back down to retrigger lazy loading
                await page.evaluate("window.scrollBy(0, -500)")
                await asyncio.sleep(0.5)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                # Click somewhere neutral to trigger intersection observer
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight + 100)")
                scroll_delay = random.uniform(3, 5)
            else:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                scroll_delay = random.uniform(4, 7)

            scroll_count += 1
            await asyncio.sleep(scroll_delay)

        print(f"  Scrolled {scroll_count} times, collected {len(post_links)} posts", flush=True)
        return post_links

    async def _extract_post_data(self, page, post_url: str) -> dict | None:
        """Navigate to a post page and extract image URL, caption, and date."""
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  Failed to load post {post_url}: {e}", flush=True)
            return None

        # Wait for full-res image to load
        await asyncio.sleep(random.uniform(1.5, 3))

        # Extract image URL, caption, and post date in one evaluate call
        try:
            data = await page.evaluate("""
                () => {
                    // --- Image URL ---
                    // Strategy: find largest srcset entry, then strip WebP format params
                    const imgs = [
                        ...document.querySelectorAll('article img'),
                        ...document.querySelectorAll('main img'),
                    ];

                    let bestUrl = null;
                    let bestSize = 0;

                    for (const img of imgs) {
                        const src = img.src || '';
                        if (!src.includes('cdninstagram.com') && !src.includes('fbcdn.net')) continue;

                        const srcset = img.srcset || '';
                        if (srcset) {
                            const parts = srcset.split(',').map(s => s.trim());
                            for (const part of parts) {
                                const tokens = part.split(/\\s+/);
                                const url = tokens[0];
                                const w = parseInt(tokens[1]) || 0;
                                if (w > bestSize) {
                                    bestSize = w;
                                    bestUrl = url;
                                }
                            }
                        }

                        // Fallback to src
                        const w = img.naturalWidth || img.width || 0;
                        if (w > bestSize && !srcset) {
                            bestSize = w;
                            bestUrl = src;
                        }
                    }

                    // Don't modify CDN URLs — accept whatever format is served

                    // --- Caption ---
                    let caption = '';
                    // Try meta description first (most reliable)
                    const metaDesc = document.querySelector('meta[property="og:description"]');
                    if (metaDesc) {
                        caption = metaDesc.getAttribute('content') || '';
                    }
                    // Fallback: look for caption span in article
                    if (!caption) {
                        const captionEl = document.querySelector('article h1');
                        if (captionEl) caption = captionEl.textContent || '';
                    }
                    if (!caption) {
                        const spans = document.querySelectorAll('article span');
                        for (const span of spans) {
                            const text = (span.textContent || '').trim();
                            if (text.length > 20 && text.length < 5000) {
                                caption = text;
                                break;
                            }
                        }
                    }

                    // --- Post date ---
                    let postDate = '';
                    const timeEl = document.querySelector('article time[datetime]');
                    if (timeEl) {
                        postDate = timeEl.getAttribute('datetime') || '';
                    }
                    // Fallback: try any time element on page
                    if (!postDate) {
                        const anyTime = document.querySelector('time[datetime]');
                        if (anyTime) postDate = anyTime.getAttribute('datetime') || '';
                    }

                    return { img_url: bestUrl, caption: caption, post_date: postDate };
                }
            """)
        except Exception as e:
            print(f"  Error extracting data from {post_url}: {e}", flush=True)
            return None

        return data

    def run(self):
        """Sync entry point."""
        asyncio.run(self.run_async())


def main():
    parser = argparse.ArgumentParser(description="Scrape Instagram AI influencer profiles")
    parser.add_argument("--config", "-c", help="Config file path")
    parser.add_argument(
        "--usernames", "-u",
        help="Comma-separated usernames (overrides config)",
    )
    parser.add_argument(
        "--cookies",
        help="Cookie file path (Netscape format, default from config)",
    )
    parser.add_argument("--max-images", "-n", type=int, default=500, help="Total image limit")
    parser.add_argument("--max-per-user", type=int, default=500, help="Per-user image limit")
    parser.add_argument(
        "--output", "-o",
        help="Output directory (default: data/<config.NAME> or data/instagram_ai_influencer)",
    )
    parser.add_argument("--force", action="store_true", help="Ignore existing manifest (clean run)")
    args = parser.parse_args()

    config = None
    if args.config:
        from configs import load_config
        config = load_config(args.config)

    usernames = None
    if args.usernames:
        usernames = [u.strip() for u in args.usernames.split(",") if u.strip()]

    scraper = InstagramScraper(
        config=config,
        usernames=usernames,
        cookies_path=args.cookies,
        max_images=args.max_images,
        max_per_user=args.max_per_user,
        output_dir=args.output,
        force=args.force,
    )
    scraper.run()


if __name__ == "__main__":
    main()
