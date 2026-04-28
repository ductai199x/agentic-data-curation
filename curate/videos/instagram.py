"""Instagram video scraper for real video dataset.

Scrapes videos from Instagram profiles using Playwright + GraphQL API interception.
Instead of navigating to individual post pages (which Instagram blocks in headless),
we intercept GraphQL responses during profile scrolling — they contain video_versions
with direct CDN URLs that we download via HTTP.

Usage:
    uv run python -m video.instagram --config configs/instagram_real_video.py
    uv run python -m video.instagram --config configs/instagram_real_video.py --max-videos 100

Requires fresh Instagram cookies (path set in config).
"""

import click
import asyncio
import csv
import hashlib
import http.cookiejar
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from tqdm import tqdm


FALLBACK_COOKIES_PATH = "data/cookies/cookies-instagram.txt"
FALLBACK_OUTPUT_DIR = "data/videos/real/instagram"

MANIFEST_FIELDS = [
    "filename", "url", "content_hash", "source", "username",
    "post_shortcode", "post_type", "timestamp", "status",
    "file_size", "width", "height",
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


def _load_cookies_for_httpx(cookies_path: str) -> dict[str, str]:
    """Load cookies as a simple dict for httpx."""
    cj = http.cookiejar.MozillaCookieJar(cookies_path)
    cj.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in cj}


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InstagramVideoScraper:
    """Scrape videos from Instagram profiles via GraphQL API interception."""

    def __init__(
        self,
        usernames: list[str],
        max_videos: int = 500,
        max_per_user: int = 99999,
        output_dir: str = FALLBACK_OUTPUT_DIR,
        cookies_path: str = FALLBACK_COOKIES_PATH,
        videos_per_visit: int = 20,
        stale_visits_to_exhaust: int = 3,
        force: bool = False,
    ):
        self.usernames = usernames
        self.max_videos = max_videos
        self.max_per_user = max_per_user
        self.output_dir = Path(output_dir)
        self.staging_dir = self.output_dir / "staging"
        self.cookies_path = cookies_path
        self.videos_per_visit = videos_per_visit
        self.stale_visits_to_exhaust = stale_visits_to_exhaust
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

        # HTTP client for downloading videos
        self.http_cookies = _load_cookies_for_httpx(cookies_path)

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
        max_retries = 50

        for attempt in range(max_retries):
            if self.total_downloaded >= self.max_videos:
                break

            try:
                await self._run_session(pbar)
                break  # Clean exit
            except Exception as e:
                print(f"\n!!! Browser crashed (attempt {attempt+1}): {e}", flush=True)
                print(f"    Restarting in 10s... ({self.total_downloaded} videos saved so far)", flush=True)
                self._load_manifest()
                await asyncio.sleep(10)

        pbar.close()
        print(f"\nDone: {self.total_downloaded} videos downloaded")

    def _save_progress(self, last_account_idx: int):
        progress_path = self.output_dir / "progress.json"
        with open(progress_path, "w") as f:
            json.dump({"last_account_idx": last_account_idx}, f)

    def _load_progress(self) -> int:
        progress_path = self.output_dir / "progress.json"
        if progress_path.exists():
            with open(progress_path) as f:
                return json.load(f).get("last_account_idx", 0)
        return 0

    async def _run_session(self, pbar):
        """Run one browser session. Scroll profiles, intercept GraphQL, download via HTTP."""
        from playwright.async_api import async_playwright

        videos_per_visit = self.videos_per_visit

        all_active = [u for u in self.usernames if u not in self.completed_accounts]
        start_idx = self._load_progress()
        if start_idx >= len(all_active):
            start_idx = 0

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

            # HTTP client for downloading video files
            async with httpx.AsyncClient(
                cookies=self.http_cookies,
                headers={
                    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                },
                follow_redirects=True,
                timeout=60,
            ) as http_client:

                stale_count: dict[str, int] = {}
                round_num = 0

                while self.total_downloaded < self.max_videos:
                    active = [u for u in all_active if u not in self.completed_accounts
                              and stale_count.get(u, 0) < self.stale_visits_to_exhaust]
                    if not active:
                        break

                    round_num += 1
                    if start_idx > 0 and round_num == 1:
                        active = active[start_idx:] + active[:start_idx]
                        start_idx = 0

                    print(f"\n=== Round {round_num}: {len(active)} accounts ===", flush=True)

                    for i, username in enumerate(active):
                        if self.total_downloaded >= self.max_videos:
                            break

                        if i > 0:
                            await asyncio.sleep(random.uniform(3, 6))

                        downloaded = await self._scrape_account(
                            page, http_client, username, pbar,
                            max_downloads=videos_per_visit,
                        )

                        if downloaded == 0:
                            stale_count[username] = stale_count.get(username, 0) + 1
                        else:
                            stale_count[username] = 0

                        if stale_count[username] >= self.stale_visits_to_exhaust:
                            self._mark_completed(username)
                            print(f"  @{username}: exhausted", flush=True)

                        print(f"  @{username}: +{downloaded} (total {self.total_downloaded})", flush=True)
                        self._save_progress(all_active.index(username) if username in all_active else 0)

            try:
                await browser.close()
            except Exception:
                pass

    async def _scrape_account(
        self, page, http_client: httpx.AsyncClient, username: str, pbar,
        max_downloads: int = 20,
    ) -> int:
        """Scroll a profile, intercept GraphQL for video data, download via HTTP.

        Returns number of videos downloaded.
        """
        # Collect video metadata from GraphQL responses during scrolling
        video_posts: dict[str, dict] = {}  # shortcode -> {url, width, height, type}

        async def on_response(response):
            url = response.url
            if "graphql" not in url:
                return
            try:
                text = await response.text()
                if "video_versions" not in text:
                    return
                data = json.loads(text)
                self._extract_videos(data, username, video_posts)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            await page.goto(
                f"https://www.instagram.com/{username}/",
                wait_until="domcontentloaded", timeout=30000,
            )
            await asyncio.sleep(3)
        except Exception as e:
            page.remove_listener("response", on_response)
            print(f"  @{username}: load failed: {e}", flush=True)
            return 0

        # Scroll to load more posts and trigger GraphQL calls
        downloaded = 0
        stale_scrolls = 0
        last_count = 0
        last_download_scroll = -1  # Track when we last downloaded something

        for scroll in range(200):  # Max 200 scrolls per visit
            if downloaded >= max_downloads or self.total_downloaded >= self.max_videos:
                break

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Check for new video posts
            new_videos = {sc: info for sc, info in video_posts.items()
                          if sc not in self.downloaded_shortcodes}

            if len(video_posts) == last_count:
                stale_scrolls += 1
                if stale_scrolls >= 6:
                    break
            else:
                stale_scrolls = 0
            last_count = len(video_posts)

            # If no new downloads in last 15 scrolls and we have video data, move on
            if scroll - last_download_scroll > 15 and len(video_posts) > 10:
                break

            # Download new videos immediately
            for shortcode, info in list(new_videos.items()):
                if downloaded >= max_downloads or self.total_downloaded >= self.max_videos:
                    break
                if shortcode in self.downloaded_shortcodes:
                    continue

                ok = await self._download_video(
                    http_client, info["url"], username, shortcode,
                    info["post_type"], info.get("width", 0), info.get("height", 0),
                )
                if ok:
                    downloaded += 1
                    self.total_downloaded += 1
                    last_download_scroll = scroll
                    pbar.update(1)
                    pbar.set_postfix(
                        user=username, total=self.total_downloaded, scroll=scroll,
                    )

            pbar.set_postfix(
                user=username, total=self.total_downloaded, scroll=scroll,
                found=len(video_posts),
            )

        page.remove_listener("response", on_response)
        return downloaded

    def _extract_videos(self, obj, username: str, out: dict, depth: int = 0):
        """Recursively walk JSON to find nodes with video_versions."""
        if depth > 20:
            return
        if isinstance(obj, dict):
            if "video_versions" in obj and obj.get("video_versions"):
                # Found a video post
                shortcode = obj.get("code") or obj.get("shortcode", "")
                if not shortcode:
                    # Try to find it in parent-level keys
                    shortcode = ""
                if shortcode and shortcode not in out:
                    versions = obj["video_versions"]
                    # Pick best quality (first is usually highest)
                    best = versions[0]
                    # Unescape unicode
                    url = best.get("url", "").replace("\\u0026", "&")
                    media_type = obj.get("media_type", 0)
                    # media_type 2 = video, 1 = image
                    post_type = "reel" if obj.get("product_type") == "clips" else "video"
                    out[shortcode] = {
                        "url": url,
                        "width": best.get("width", 0),
                        "height": best.get("height", 0),
                        "post_type": post_type,
                    }
            for v in obj.values():
                self._extract_videos(v, username, out, depth + 1)
        elif isinstance(obj, list):
            for v in obj:
                self._extract_videos(v, username, out, depth + 1)

    async def _download_video(
        self, http_client: httpx.AsyncClient,
        url: str, username: str, shortcode: str,
        post_type: str, width: int, height: int,
    ) -> bool:
        """Download a video from CDN URL via HTTP."""
        if not url:
            return False

        try:
            resp = await http_client.get(url)
            if resp.status_code != 200:
                return False

            video_data = resp.content
            if len(video_data) < 10000:
                return False

            vid_hash = _content_hash(video_data)
            if vid_hash in self.downloaded_hashes:
                self.downloaded_shortcodes.add(shortcode)
                return False

            filename = f"{vid_hash[:16]}.mp4"
            filepath = self.staging_dir / filename
            filepath.write_bytes(video_data)

            self.downloaded_hashes.add(vid_hash)
            self.downloaded_shortcodes.add(shortcode)

            self._append_manifest({
                "filename": filename,
                "url": url.split("?")[0][:500],
                "content_hash": vid_hash,
                "source": "instagram",
                "username": username,
                "post_shortcode": shortcode,
                "post_type": post_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "downloaded",
                "file_size": len(video_data),
                "width": width,
                "height": height,
            })

            return True
        except Exception:
            return False

    @staticmethod
    def _shortcode(link: str) -> str:
        """Extract shortcode from /p/XXX/ or /reel/XXX/ link."""
        m = re.search(r"/(p|reel)/([A-Za-z0-9_-]+)", link)
        return m.group(2) if m else link


@click.command(help="Instagram video scraper")
@click.option("--config", "-c", default=None, help="Config file")
@click.option("--usernames", "-u", default=None, help="Comma-separated usernames (overrides config)")
@click.option("--account-file", default=None, help="File with usernames (overrides config)")
@click.option("--max-videos", "-n", type=int, default=None, help="Override MAX_VIDEOS")
@click.option("--max-per-user", type=int, default=None, help="Override MAX_PER_USER")
@click.option("--output", "-o", default=None, help="Override OUTPUT_DIR")
@click.option("--cookies", default=None, help="Override COOKIES_PATH")
@click.option("--force", is_flag=True)
def main(config, usernames, account_file, max_videos, max_per_user, output,
         cookies, force):
    # Load config if provided
    cfg = None
    if config:
        from configs import load_config
        cfg = load_config(config)

    # Resolve usernames: CLI > config
    users: list[str] = []
    if usernames:
        users = [u.strip() for u in usernames.split(",") if u.strip()]
    elif account_file:
        with open(account_file) as f:
            users = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    elif cfg and hasattr(cfg, "INSTAGRAM_USERNAMES"):
        users = cfg.INSTAGRAM_USERNAMES

    if not users:
        print("No usernames specified. Use --config, --usernames, or --account-file.")
        sys.exit(1)

    # Resolve parameters: CLI > config > defaults
    mv = max_videos or getattr(cfg, "MAX_VIDEOS", 500)
    mpu = max_per_user or getattr(cfg, "MAX_PER_USER", 99999)
    output_dir = output or getattr(cfg, "OUTPUT_DIR", FALLBACK_OUTPUT_DIR)
    cookies_path = cookies or getattr(cfg, "COOKIES_PATH", FALLBACK_COOKIES_PATH)
    videos_per_visit = getattr(cfg, "VIDEOS_PER_VISIT", 20)
    stale_visits = getattr(cfg, "STALE_VISITS_TO_EXHAUST", 3)

    scraper = InstagramVideoScraper(
        usernames=users,
        max_videos=mv,
        max_per_user=mpu,
        output_dir=output_dir,
        cookies_path=cookies_path,
        videos_per_visit=videos_per_visit,
        stale_visits_to_exhaust=stale_visits,
        force=force,
    )
    asyncio.run(scraper.run())


if __name__ == "__main__":
    main()
