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
        max_retries = 50  # Restart browser up to 50 times on crash

        for attempt in range(max_retries):
            if self.total_downloaded >= self.max_videos:
                break

            try:
                await self._run_session(pbar)
                break  # Clean exit
            except Exception as e:
                print(f"\n!!! Browser crashed (attempt {attempt+1}): {e}", flush=True)
                print(f"    Restarting in 10s... ({self.total_downloaded} videos saved so far)", flush=True)
                # Reload manifest to pick up any downloads from crashed session
                self._load_manifest()
                await asyncio.sleep(10)

        pbar.close()
        print(f"\nDone: {self.total_downloaded} videos downloaded")

    def _save_progress(self, last_account_idx: int):
        """Save the index of the last processed account for resume."""
        progress_path = self.output_dir / "progress.json"
        import json
        with open(progress_path, "w") as f:
            json.dump({"last_account_idx": last_account_idx}, f)

    def _load_progress(self) -> int:
        """Load the last processed account index."""
        import json
        progress_path = self.output_dir / "progress.json"
        if progress_path.exists():
            with open(progress_path) as f:
                return json.load(f).get("last_account_idx", 0)
        return 0

    async def _run_session(self, pbar):
        """Run one browser session. Processes accounts in batches of 30 tabs."""
        from playwright.async_api import async_playwright

        BATCH_SIZE = 30
        videos_per_visit = 20

        # Get accounts to process, starting from where we left off
        all_active = [u for u in self.usernames if u not in self.completed_accounts]
        start_idx = self._load_progress()
        if start_idx >= len(all_active):
            start_idx = 0  # Wrap around for next round

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

            # Process accounts in batches of BATCH_SIZE
            batch_start = start_idx
            while batch_start < len(all_active):
                if self.total_downloaded >= self.max_videos:
                    break

                batch = all_active[batch_start:batch_start + BATCH_SIZE]
                batch = [u for u in batch if u not in self.completed_accounts]
                if not batch:
                    batch_start += BATCH_SIZE
                    continue

                print(f"\n=== Batch {batch_start//BATCH_SIZE + 1}: "
                      f"accounts {batch_start+1}-{batch_start+len(batch)} "
                      f"({len(batch)} tabs) ===", flush=True)

                # Open tabs for this batch
                tabs: dict[str, object] = {}
                for username in batch:
                    try:
                        tab = await ctx.new_page()
                        await tab.goto(
                            f"https://www.instagram.com/{username}/",
                            wait_until="domcontentloaded", timeout=30000,
                        )
                        tabs[username] = tab
                    except Exception as e:
                        print(f"  Failed to open @{username}: {e}", flush=True)
                        try:
                            await tab.close()
                        except Exception:
                            pass
                        continue
                    await asyncio.sleep(0.5)

                print(f"  Opened {len(tabs)} tabs", flush=True)
                await asyncio.sleep(3)

                # Round-robin within this batch
                seen_links: dict[str, set] = {u: set() for u in tabs}
                stale_count: dict[str, int] = {u: 0 for u in tabs}
                round_num = 0

                while self.total_downloaded < self.max_videos:
                    active = [u for u in tabs if stale_count.get(u, 0) < 6]
                    if not active:
                        break

                    round_num += 1
                    print(f"\n  Round {round_num}: {len(active)} active", flush=True)

                    for username in active:
                        if self.total_downloaded >= self.max_videos:
                            break

                        tab = tabs[username]
                        try:
                            downloaded = await asyncio.wait_for(
                                self._download_from_tab(
                                    tab, username, pbar, seen_links[username],
                                    max_downloads=videos_per_visit,
                                ),
                                timeout=600,  # 10 min max per account per visit
                            )
                        except asyncio.TimeoutError:
                            print(f"  @{username}: TIMEOUT, skipping", flush=True)
                            downloaded = 0
                            stale_count[username] = 6  # Force exhaust
                        except Exception as e:
                            print(f"  @{username}: error {e}", flush=True)
                            downloaded = 0

                        if downloaded == 0:
                            stale_count[username] = stale_count.get(username, 0) + 1
                        else:
                            stale_count[username] = 0

                        if stale_count[username] >= 6:
                            self._mark_completed(username)
                            try:
                                await tab.close()
                            except Exception:
                                pass
                            print(f"  @{username}: exhausted", flush=True)

                        print(f"  @{username}: +{downloaded} (total {self.total_downloaded})", flush=True)

                        # Save progress after each account
                        account_idx = all_active.index(username) if username in all_active else batch_start
                        self._save_progress(account_idx)

                        await asyncio.sleep(random.uniform(2, 4))

                # Close batch tabs
                for tab in tabs.values():
                    try:
                        await tab.close()
                    except Exception:
                        pass

                batch_start += BATCH_SIZE
                self._save_progress(batch_start)

            try:
                await browser.close()
            except Exception:
                pass

    async def _download_from_tab(
        self, tab, username: str, pbar, seen_links: set,
        max_downloads: int = 20,
    ) -> int:
        """Scroll a tab and download videos. Tab preserves scroll position.

        Args:
            tab: Playwright page (already at the profile, scroll preserved).
            username: Instagram username.
            pbar: tqdm progress bar.
            seen_links: Set of link paths already seen (mutated in place).
            max_downloads: Max videos to download this visit.

        Returns:
            Number of videos downloaded.
        """
        downloaded = 0

        # Scroll and download loop — same as _scroll_and_download but simpler
        for scroll in range(50):  # Max 50 scrolls per visit
            if downloaded >= max_downloads:
                break
            if self.total_downloaded >= self.max_videos:
                break

            # Extract links from current DOM
            try:
                dom_links = await asyncio.wait_for(
                    tab.eval_on_selector_all("a[href]",
                        """els => els.map(a => a.getAttribute('href'))
                                  .filter(h => h && (h.includes('/reel/') || h.includes('/p/')))"""),
                    timeout=10,
                )
            except Exception:
                dom_links = []

            # Find fresh links
            fresh = [l for l in set(dom_links) if l not in seen_links
                     and self._shortcode(l) not in self.downloaded_shortcodes]

            for link in fresh:
                seen_links.add(link)
                if downloaded >= max_downloads:
                    break

                shortcode = self._shortcode(link)
                post_url = f"https://www.instagram.com{link}"
                post_type = "reel" if "/reel/" in link else "post"

                try:
                    dl_page = await tab.context.new_page()
                except Exception:
                    break  # Browser crashed, stop this tab
                try:
                    ok = await self._extract_and_download_video(
                        dl_page, post_url, username, shortcode, post_type,
                    )
                    if ok:
                        downloaded += 1
                        self.total_downloaded += 1
                        pbar.update(1)
                        pbar.set_postfix(user=username, total=self.total_downloaded)
                finally:
                    try:
                        await dl_page.close()
                    except Exception:
                        pass  # Browser connection may have dropped

                await asyncio.sleep(random.uniform(1, 2))

            # Mark all DOM links as seen (even ones we didn't download)
            seen_links.update(dom_links)

            # Scroll for more content
            await tab.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2, 4))

        return downloaded

    async def _scrape_user(self, page, username: str, pbar,
                           max_this_visit: int = 999999):
        """Scrape videos from a single user's profile.

        Interleaves scrolling and downloading like the image scraper:
        scroll to find links, download videos from new links, scroll more.
        Also scrapes the reels tab after the main grid.

        Args:
            max_this_visit: Max videos to download this visit (for round-robin).
        """
        user_downloaded = 0
        profile_url = f"https://www.instagram.com/{username}/"

        print(f"\nScraping @{username}", flush=True)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  Failed to load @{username}: {e}", flush=True)
            return

        await asyncio.sleep(5)

        # Check for login wall or 404
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

        # Scrape main grid: scroll + download interleaved
        user_downloaded += await self._scroll_and_download(
            page, username, pbar, user_downloaded,
            max_downloads=max_this_visit,
        )

        # Scrape reels tab for additional reels (if we still have budget)
        if user_downloaded < max_this_visit and self.total_downloaded < self.max_videos:
            reels_url = f"https://www.instagram.com/{username}/reels/"
            try:
                await page.goto(reels_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)
                user_downloaded += await self._scroll_and_download(
                    page, username, pbar, user_downloaded, reels_only=True,
                    max_downloads=max_this_visit - user_downloaded,
                )
            except Exception as e:
                print(f"  Reels tab failed: {e}", flush=True)

        # Only mark completed if we found NO new videos (account exhausted)
        # Don't mark completed if we just hit max_this_visit — come back later
        if user_downloaded == 0:
            self._mark_completed(username)
        print(f"  @{username}: {user_downloaded} videos this visit", flush=True)

    async def _scroll_and_download(
        self, page, username: str, pbar, user_downloaded: int,
        reels_only: bool = False, max_downloads: int = 999999,
    ) -> int:
        """Scroll page and download videos as links are discovered.

        Interleaves scrolling and downloading: each scroll finds new links,
        visits them to extract video, then scrolls more.

        Returns number of videos downloaded in this pass.
        """
        if reels_only:
            js_filter = """els => els.map(a => a.getAttribute('href'))
                              .filter(h => h && h.includes('/reel/'))"""
        else:
            js_filter = """els => els.map(a => a.getAttribute('href'))
                              .filter(h => h && (h.includes('/reel/') || h.includes('/p/')))"""

        seen_links: set[str] = set()
        downloaded_this_pass = 0
        stale = 0
        max_stale = 6
        max_scrolls = 1000
        last_height = 0
        last_link_count = 0  # Track DOM link count to detect new content
        aggressive_phase = False
        scroll_count = 0

        while stale < max_stale and scroll_count < max_scrolls:
            if downloaded_this_pass >= max_downloads:
                break
            if self.total_downloaded >= self.max_videos:
                break

            # Extract links from current DOM
            try:
                dom_links = await asyncio.wait_for(
                    page.eval_on_selector_all("a[href]", js_filter),
                    timeout=10,
                )
            except Exception:
                dom_links = []

            dom_links_set = set(dom_links)

            # Find links we haven't tried downloading yet
            fresh_links = [l for l in dom_links_set if l not in seen_links
                           and self._shortcode(l) not in self.downloaded_shortcodes]

            # Download videos from fresh links in a new tab
            for link in fresh_links:
                seen_links.add(link)

                if user_downloaded + downloaded_this_pass >= self.max_per_user:
                    break
                if self.total_downloaded >= self.max_videos:
                    break

                shortcode = self._shortcode(link)
                post_url = f"https://www.instagram.com{link}"
                post_type = "reel" if "/reel/" in link else "post"

                dl_page = await page.context.new_page()
                try:
                    ok = await self._extract_and_download_video(
                        dl_page, post_url, username, shortcode, post_type,
                    )
                    if ok:
                        downloaded_this_pass += 1
                        self.total_downloaded += 1
                        pbar.update(1)
                        pbar.set_postfix(user=username, total=self.total_downloaded, scroll=scroll_count)
                finally:
                    await dl_page.close()

                await asyncio.sleep(random.uniform(1, 2))

            # Scroll and check for new content
            current_height = await page.evaluate("document.body.scrollHeight")
            current_link_count = len(dom_links_set)

            if current_height == last_height and current_link_count == last_link_count:
                stale += 1
            else:
                stale = 0
                aggressive_phase = False

            last_height = current_height
            last_link_count = current_link_count

            # Aggressive mode after 3 stale scrolls
            if stale >= 3 and not aggressive_phase:
                aggressive_phase = True

            if aggressive_phase:
                await page.evaluate("window.scrollBy(0, -500)")
                await asyncio.sleep(0.3)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight + 100)")
                await asyncio.sleep(random.uniform(2, 3))
            else:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(random.uniform(2, 4))

            scroll_count += 1

        label = "reels tab" if reels_only else "main grid"
        print(f"    {label}: {downloaded_this_pass} videos, {len(seen_links)} links, {scroll_count} scrolls", flush=True)
        return downloaded_this_pass

    async def _scroll_and_collect(self, page, reels_only: bool = False) -> set[str]:
        """Scroll current page and collect post/reel links.

        Matches the image scraper behavior: 1000 max scrolls, 6 stale
        threshold, aggressive scroll mode after 3 stale scrolls.

        Args:
            page: Playwright page (already navigated to grid or reels tab).
            reels_only: If True, only collect /reel/ links (for reels tab).

        Returns:
            Set of unique link paths.
        """
        if reels_only:
            js_filter = """els => els.map(a => a.getAttribute('href'))
                              .filter(h => h && h.includes('/reel/'))"""
        else:
            js_filter = """els => els.map(a => a.getAttribute('href'))
                              .filter(h => h && (h.includes('/reel/') || h.includes('/p/')))"""

        all_links: set[str] = set()
        stale = 0
        max_stale = 6
        max_scrolls = 1000
        last_height = 0
        aggressive_phase = False

        for scroll in range(max_scrolls):
            try:
                new_links = await asyncio.wait_for(
                    page.eval_on_selector_all("a[href]", js_filter),
                    timeout=10,
                )
            except Exception:
                new_links = []

            new_count = sum(1 for l in new_links if l not in all_links)
            all_links.update(new_links)

            # Check scroll position
            current_height = await page.evaluate("document.body.scrollHeight")
            if current_height == last_height and new_count == 0:
                stale += 1
            else:
                stale = 0
                aggressive_phase = False
            last_height = current_height

            if stale >= max_stale:
                break

            # Aggressive mode after 3 stale scrolls
            if stale >= 3 and not aggressive_phase:
                aggressive_phase = True

            if aggressive_phase:
                await page.evaluate("window.scrollBy(0, -500)")
                await asyncio.sleep(0.5)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight + 100)")
                await asyncio.sleep(random.uniform(3, 5))
            else:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(random.uniform(4, 7))

        return all_links

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
            await asyncio.sleep(1)  # Quick initial load

            # Fast check: is there a video element in the DOM?
            has_video = await page.evaluate("() => document.querySelectorAll('video').length > 0")
            if not has_video:
                # No video element = image post, bail fast
                page.remove_listener("response", on_response)
                return False

            # Video exists — wait for chunks to stream
            await asyncio.sleep(4)
        except Exception as e:
            page.remove_listener("response", on_response)
            return False

        page.remove_listener("response", on_response)

        if not chunks:
            return False  # Video element existed but no chunks captured

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
