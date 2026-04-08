"""Instagram video scraper for real video dataset.

Scrapes Reels and video posts from Instagram profiles using Playwright.
Video URLs are captured via network interception (Instagram uses blob URLs
in the DOM, but the actual mp4 CDN URLs appear in network responses).

Usage:
    uv run python -m video.instagram --usernames natgeo,bbcearth --max-videos 100
    uv run python -m video.instagram --account-file configs/video_sources/instagram_video.txt

Requires fresh Instagram cookies at data/cookies/cookies-instagram.txt
"""

import argparse
import asyncio
import csv
import hashlib
import http.cookiejar
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm


COOKIES_PATH = "data/cookies/cookies-instagram.txt"
OUTPUT_DIR = "data/videos/real/instagram"

MANIFEST_FIELDS = [
    "filename", "url", "content_hash", "source", "username",
    "post_shortcode", "post_type", "timestamp", "status",
    "file_size",
]


def _load_cookies(cookies_path: str) -> list[dict]:
    """Load Netscape-format cookies and convert to Playwright format."""
    cj = http.cookiejar.MozillaCookieJar(cookies_path)
    cj.load(ignore_discard=True, ignore_expires=True)
    pw_cookies = []
    for cookie in cj:
        c = {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": cookie.secure,
        }
        if cookie.expires:
            c["expires"] = cookie.expires
        pw_cookies.append(c)
    return pw_cookies


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InstagramVideoScraper:
    """Scrape videos from Instagram profiles."""

    def __init__(
        self,
        usernames: list[str],
        max_videos: int = 500,
        max_per_user: int = 100,
        output_dir: str = OUTPUT_DIR,
        cookies_path: str = COOKIES_PATH,
        force: bool = False,
    ):
        self.usernames = usernames
        self.max_videos = max_videos
        self.max_per_user = max_per_user
        self.output_dir = Path(output_dir)
        self.staging_dir = self.output_dir / "staging"
        self.cookies_path = cookies_path
        self.total_downloaded = 0

        self.staging_dir.mkdir(parents=True, exist_ok=True)

        # Manifest for resume
        self.manifest_path = self.output_dir / "manifest.csv"
        self.downloaded_urls: set[str] = set()
        self.downloaded_hashes: set[str] = set()
        self.downloaded_shortcodes: set[str] = set()

        if not force:
            self._load_manifest()

        # Completed accounts
        self.completed_accounts: set[str] = set()
        completed_path = self.output_dir / "completed_accounts.txt"
        if completed_path.exists() and not force:
            with open(completed_path) as f:
                self.completed_accounts = {l.strip() for l in f if l.strip()}
            if self.completed_accounts:
                print(f"Loaded {len(self.completed_accounts)} completed accounts")

    def _load_manifest(self):
        if not self.manifest_path.exists():
            return
        with open(self.manifest_path) as f:
            for row in csv.DictReader(f):
                self.downloaded_urls.add(row.get("url", ""))
                h = row.get("content_hash", "")
                if h:
                    self.downloaded_hashes.add(h)
                sc = row.get("post_shortcode", "")
                if sc:
                    self.downloaded_shortcodes.add(sc)
        print(f"Resume: {len(self.downloaded_shortcodes)} posts already downloaded")

    def _append_manifest(self, row: dict):
        write_header = not self.manifest_path.exists()
        with open(self.manifest_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

    def _mark_completed(self, username: str):
        self.completed_accounts.add(username)
        with open(self.output_dir / "completed_accounts.txt", "a") as f:
            f.write(f"{username}\n")

    async def run(self):
        from playwright.async_api import async_playwright

        pbar = tqdm(desc="Instagram videos", unit="vid", file=sys.stderr)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
            )
            await ctx.add_init_script(
                'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
            )

            try:
                pw_cookies = _load_cookies(self.cookies_path)
                await ctx.add_cookies(pw_cookies)
                print(f"Loaded {len(pw_cookies)} cookies")
            except Exception as e:
                print(f"Cookie load failed: {e}")
                return

            page = await ctx.new_page()

            for i, username in enumerate(self.usernames):
                if self.total_downloaded >= self.max_videos:
                    break
                if username in self.completed_accounts:
                    continue

                if i > 0:
                    pause = random.uniform(20, 30)
                    print(f"\nPausing {pause:.0f}s between users...", flush=True)
                    await asyncio.sleep(pause)

                await self._scrape_user(page, username, pbar)

            await browser.close()

        pbar.close()
        print(f"\nDone: {self.total_downloaded} videos downloaded")

    async def _scrape_user(self, page, username: str, pbar):
        """Scrape videos from a single user's profile."""
        user_downloaded = 0
        profile_url = f"https://www.instagram.com/{username}/"

        print(f"\nScraping @{username}", flush=True)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  Failed to load @{username}: {e}", flush=True)
            return

        await asyncio.sleep(5)
        print(f"  Page loaded: {page.url}", flush=True)

        # Check for login wall or 404 (use evaluate for speed, not text_content)
        page_check = await page.evaluate(
            "() => ({ len: document.body.innerText.length, "
            "has_login: document.body.innerText.includes('Log in'), "
            "has_404: document.body.innerText.includes('this page') && "
            "document.body.innerText.includes('available') })"
        )
        if page_check["has_login"] and page_check["len"] < 2000:
            print(f"  Login wall — skipping", flush=True)
            return
        if page_check["has_404"]:
            print(f"  404 — skipping", flush=True)
            return

        # Collect post/reel links from grid
        print(f"  Collecting links...", flush=True)
        post_links = await self._collect_links(page, username)
        reels = sum(1 for l in post_links if "/reel/" in l)
        posts = len(post_links) - reels
        print(f"  Found {len(post_links)} links ({reels} reels, {posts} posts)", flush=True)

        # Filter to unprocessed
        post_links = [l for l in post_links if self._shortcode(l) not in self.downloaded_shortcodes]
        print(f"  {len(post_links)} new (after resume filter)", flush=True)

        # Visit each post and try to extract video
        for j, link in enumerate(post_links):
            if user_downloaded >= self.max_per_user or self.total_downloaded >= self.max_videos:
                break

            shortcode = self._shortcode(link)
            post_url = f"https://www.instagram.com{link}"
            post_type = "reel" if "/reel/" in link else "post"

            # Rate limit between posts
            await asyncio.sleep(random.uniform(3, 6))

            # Navigate to post, capture video chunks, download
            ok = await self._extract_and_download_video(
                page, post_url, username, shortcode, post_type,
            )
            if ok:
                user_downloaded += 1
                self.total_downloaded += 1
                pbar.update(1)
                pbar.set_postfix(user=username, total=self.total_downloaded)

        if user_downloaded > 0 or len(post_links) == 0:
            self._mark_completed(username)
            print(f"  @{username}: {user_downloaded} videos downloaded", flush=True)

    async def _collect_links(self, page, username: str, max_links: int = 0) -> list[str]:
        """Scroll profile grid and collect post/reel links."""
        all_links: set[str] = set()
        stale = 0
        max_stale = 6
        # Don't scroll forever — collect enough candidates then stop
        # Need ~3x max_per_user since not all posts are video
        target = max_links if max_links > 0 else self.max_per_user * 3

        for scroll in range(200):
            new_links = await asyncio.wait_for(
                page.eval_on_selector_all(
                    "a[href]",
                    """els => els.map(a => a.getAttribute('href'))
                              .filter(h => h && (h.includes('/reel/') || h.includes('/p/')))"""
                ),
                timeout=10,
            )
            new_count = sum(1 for l in new_links if l not in all_links)
            all_links.update(new_links)
            print(f"    Scroll {scroll}: +{new_count} new, {len(all_links)} total", flush=True)

            if len(all_links) >= target:
                break

            if new_count == 0:
                stale += 1
                if stale >= max_stale:
                    break
            else:
                stale = 0

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2, 4))

        return list(all_links)

    async def _extract_and_download_video(
        self, page, post_url: str, username: str, shortcode: str, post_type: str,
    ) -> bool:
        """Navigate to a post/reel, capture video chunks, and save.

        Instagram streams video in fragmented chunks via MSE.
        We intercept all video/mp4 responses, group by base URL,
        and concatenate the chunks of the largest stream (= the target video).
        """
        from collections import defaultdict

        chunks = defaultdict(list)  # base_url -> [(order, bytes)]
        order = [0]

        async def on_response(response):
            ct = response.headers.get("content-type", "")
            if "video/mp4" in ct:
                url = response.url
                if "cdninstagram.com" in url or "fbcdn.net" in url:
                    try:
                        body = await response.body()
                        base = url.split("?")[0]
                        chunks[base].append((order[0], body))
                        order[0] += 1
                    except Exception:
                        pass

        page.on("response", on_response)

        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(8)  # Wait for video to stream
        except Exception as e:
            page.remove_listener("response", on_response)
            return False

        page.remove_listener("response", on_response)

        if not chunks:
            return False  # No video on this post (image-only)

        # Find the base URL with the most data (= the target video)
        best_base = max(chunks, key=lambda k: sum(len(b) for _, b in chunks[k]))
        best_chunks = sorted(chunks[best_base], key=lambda x: x[0])
        total_size = sum(len(b) for _, b in best_chunks)

        if total_size < 10000:  # Skip tiny stub videos
            return False

        # Concatenate chunks in order
        video_data = b"".join(b for _, b in best_chunks)

        vid_hash = _content_hash(video_data)
        if vid_hash in self.downloaded_hashes:
            return False

        filename = f"{vid_hash[:16]}.mp4"
        filepath = self.staging_dir / filename
        filepath.write_bytes(video_data)

        self.downloaded_hashes.add(vid_hash)
        self.downloaded_shortcodes.add(shortcode)

        self._append_manifest({
            "filename": filename,
            "url": best_base[:500],
            "content_hash": vid_hash,
            "source": "instagram",
            "username": username,
            "post_shortcode": shortcode,
            "post_type": post_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "downloaded",
            "file_size": total_size,
        })

        return True

    @staticmethod
    def _shortcode(link: str) -> str:
        """Extract shortcode from /p/XXX/ or /reel/XXX/ link."""
        m = re.search(r"/(p|reel)/([A-Za-z0-9_-]+)", link)
        return m.group(2) if m else link


def main():
    parser = argparse.ArgumentParser(description="Instagram video scraper")
    parser.add_argument("--usernames", "-u", help="Comma-separated usernames")
    parser.add_argument("--account-file", help="File with usernames (one per line)")
    parser.add_argument("--max-videos", "-n", type=int, default=500)
    parser.add_argument("--max-per-user", type=int, default=100)
    parser.add_argument("--output", "-o", default=OUTPUT_DIR)
    parser.add_argument("--cookies", default=COOKIES_PATH)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    usernames = []
    if args.usernames:
        usernames = [u.strip() for u in args.usernames.split(",") if u.strip()]
    elif args.account_file:
        with open(args.account_file) as f:
            usernames = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    if not usernames:
        print("No usernames specified.")
        sys.exit(1)

    scraper = InstagramVideoScraper(
        usernames=usernames,
        max_videos=args.max_videos,
        max_per_user=args.max_per_user,
        output_dir=args.output,
        cookies_path=args.cookies,
        force=args.force,
    )
    asyncio.run(scraper.run())


if __name__ == "__main__":
    main()
