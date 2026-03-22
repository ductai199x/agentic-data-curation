"""Discord-based scraper for Midjourney images.

Scrapes the official Midjourney Discord server via Discord REST API.
Auto-discovers general channels, paginates backwards from present,
filters for Midjourney Bot messages with target versions (v7, v8).

Auth: Discord user token (env var DISCORD_TOKEN or config).
No Playwright needed — pure REST API + CDN downloads.

Usage:
    uv run python -m scrapers.midjourney --config configs/midjourney_v7.py --max-images 50000
    uv run python -m scrapers.midjourney --config configs/midjourney_v7.py --max-images 20 --channels general-1,general-2
"""

import argparse
import random
import re
import sys
import time
from datetime import datetime, timezone

from tqdm import tqdm

from scrapers.base import BaseScraper

DISCORD_API_BASE = "https://discord.com/api/v10"


def datetime_to_snowflake(dt: datetime) -> int:
    """Convert a datetime to a Discord snowflake ID."""
    unix_ms = int(dt.timestamp() * 1000)
    return (unix_ms - 1420070400000) << 22


def snowflake_to_datetime(snowflake: int) -> datetime:
    """Convert a Discord snowflake ID to a datetime."""
    unix_ms = (snowflake >> 22) + 1420070400000
    return datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)


def parse_version(message: dict) -> str:
    """Extract Midjourney version from a Discord message.

    Checks (in order):
    1. Component custom_ids (most reliable)
    2. --v flag in message content
    3. Falls back to "unknown"
    """
    # Method 1: component custom_ids
    for row in message.get("components", []):
        for comp in row.get("components", []):
            cid = comp.get("custom_id", "")
            if "_v8" in cid or "v8_" in cid:
                return "8"
            if "_v7" in cid or "v7_" in cid:
                return "7"
            if "v6r1" in cid or "_v6.1" in cid:
                return "6.1"
            if "_v6" in cid or "v6_" in cid:
                return "6"
            if "_v5" in cid or "v5_" in cid:
                return "5"

    # Method 2: --v flag in content
    content = message.get("content", "")
    match = re.search(r"--v\s+(\d+(?:\.\d+)?)", content)
    if match:
        return match.group(1)

    # Method 3: unknown
    return "unknown"


def is_upscaled(message: dict) -> bool:
    """Check if the message contains an upscaled (single) image."""
    content = message.get("content", "")
    return "Upscaled" in content


class MidjourneyScraper(BaseScraper):
    """Scrapes Midjourney images from the official Discord server."""

    source_name = "discord_midjourney_v7"

    def __init__(self, config, max_images: int = 50000, force: bool = False,
                 channels: list[str] | None = None):
        output_dir = f"data/{config.NAME}"
        super().__init__(
            output_dir, max_images,
            min_pixels=getattr(config, "MIN_PIXELS", 200_000),
            force=force,
        )
        self.config = config

        # Discord settings from config
        self.token = getattr(config, "DISCORD_TOKEN", "")
        if not self.token:
            raise ValueError(
                "DISCORD_TOKEN not set. Export it as an env var or set it in the config."
            )

        self.guild_id = getattr(config, "DISCORD_GUILD_ID", "662267976984297473")
        self.bot_id = getattr(config, "DISCORD_BOT_ID", "936929561302675456")
        self.channel_pattern = re.compile(
            getattr(config, "DISCORD_CHANNEL_PATTERN", r"^general-")
        )
        self.target_versions = set(
            getattr(config, "DISCORD_TARGET_VERSIONS", ["7", "8"])
        )
        self.api_delay = getattr(config, "DISCORD_API_DELAY", 3.0)
        self.download_delay = getattr(config, "DISCORD_DOWNLOAD_DELAY", 0.5)

        # Parse start date into snowflake
        start_date_str = getattr(config, "DISCORD_START_DATE", "2025-04-01")
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        self.start_snowflake = datetime_to_snowflake(start_dt)

        # Optional channel filter from CLI
        self.channel_filter = set(channels) if channels else None

        # Auth headers for Discord API
        self.session.headers.update({
            "Authorization": self.token,
            "Content-Type": "application/json",
        })

        # Extra stats
        self.stats.update({
            "channels_scraped": 0,
            "messages_scanned": 0,
            "bot_messages": 0,
            "skipped_version": 0,
            "skipped_no_attachment": 0,
            "grids": 0,
            "upscaled": 0,
        })

    # ── Channel discovery ──────────────────────────────────────────

    def discover_channels(self) -> list[dict]:
        """List guild channels and filter by pattern."""
        url = f"{DISCORD_API_BASE}/guilds/{self.guild_id}/channels"
        resp = self._api_get(url)
        if resp is None:
            print("Failed to list guild channels", flush=True)
            return []

        channels = resp
        # Filter to text channels (type 0) matching the pattern
        matched = []
        for ch in channels:
            if ch.get("type") != 0:
                continue
            name = ch.get("name", "")
            if self.channel_pattern.search(name):
                if self.channel_filter is None or name in self.channel_filter:
                    matched.append(ch)

        # Sort by name for deterministic ordering
        matched.sort(key=lambda c: c.get("name", ""))

        print(f"Discovered {len(matched)} channels matching "
              f"pattern '{self.channel_pattern.pattern}':", flush=True)
        for ch in matched:
            print(f"  #{ch['name']} ({ch['id']})", flush=True)

        return matched

    # ── API helpers ────────────────────────────────────────────────

    def _api_get(self, url: str, params: dict | None = None) -> list | dict | None:
        """Make a GET request to the Discord API with retry/backoff."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=30)

                if resp.status_code == 429:
                    # Rate limited — respect Retry-After header
                    retry_after = resp.json().get("retry_after", 5.0)
                    wait = max(retry_after, (attempt + 1) * 5)
                    tqdm.write(f"  Rate limited (429), waiting {wait:.1f}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code == 403:
                    tqdm.write(f"  Access denied (403) for {url}")
                    return None

                if resp.status_code == 404:
                    tqdm.write(f"  Not found (404) for {url}")
                    return None

                resp.raise_for_status()
                return resp.json()

            except Exception as e:
                wait = (attempt + 1) * 10
                tqdm.write(f"  API error: {e}, retrying in {wait}s...")
                time.sleep(wait)

        tqdm.write(f"  Failed after {max_retries} retries: {url}")
        return None

    def _fetch_messages(self, channel_id: str, before: str | None = None) -> list[dict]:
        """Fetch up to 100 messages from a channel, paginating backwards."""
        url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages"
        params = {"limit": 100}
        if before:
            params["before"] = before

        result = self._api_get(url, params)
        if result is None:
            return []
        return result

    # ── Image extraction ───────────────────────────────────────────

    def _extract_image_url(self, message: dict) -> str | None:
        """Get the first image attachment URL from a message."""
        attachments = message.get("attachments", [])
        for att in attachments:
            content_type = att.get("content_type", "")
            filename = att.get("filename", "").lower()
            # Only images
            if (content_type.startswith("image/")
                    or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))):
                return att.get("url")
        return None

    def _extract_prompt(self, message: dict) -> str:
        """Extract the prompt text from a Midjourney bot message."""
        content = message.get("content", "")
        # Midjourney format: "**prompt text** - <@user_id> (options)"
        # Extract text between ** **
        match = re.search(r"\*\*(.+?)\*\*", content)
        if match:
            return match.group(1)
        return content[:200]

    # ── Main scraping loop ─────────────────────────────────────────

    def run(self):
        """Synchronous scraper — iterate channels, paginate backwards."""
        channels = self.discover_channels()
        if not channels:
            print("No channels found. Check DISCORD_CHANNEL_PATTERN or --channels.", flush=True)
            return

        pbar = tqdm(desc="Midjourney", unit="img", file=sys.stderr)

        for ch in channels:
            if self.done:
                break

            channel_id = ch["id"]
            channel_name = ch["name"]
            channel_downloaded = 0

            print(f"\n--- Scraping #{channel_name} ({channel_id}) ---", flush=True)

            # Start from latest messages (no "before" = most recent)
            before_id = None
            empty_count = 0

            while not self.done:
                messages = self._fetch_messages(channel_id, before=before_id)
                time.sleep(self.api_delay + random.uniform(0, 1.0))

                if not messages:
                    empty_count += 1
                    if empty_count >= 2:
                        print(f"  #{channel_name}: no more messages", flush=True)
                        break
                    continue

                empty_count = 0
                self.stats["messages_scanned"] += len(messages)

                # Check if we've gone past the start date
                oldest_msg = messages[-1]
                oldest_id = int(oldest_msg["id"])
                if oldest_id < self.start_snowflake:
                    # Filter this batch to only include messages after start date
                    messages = [m for m in messages if int(m["id"]) >= self.start_snowflake]
                    if not messages:
                        oldest_dt = snowflake_to_datetime(oldest_id)
                        print(f"  #{channel_name}: reached start date boundary "
                              f"({oldest_dt.strftime('%Y-%m-%d')})", flush=True)
                        break

                # Update pagination cursor to oldest message in batch
                before_id = messages[-1]["id"]

                for msg in messages:
                    if self.done:
                        break

                    # Only Midjourney Bot messages
                    author = msg.get("author", {})
                    if author.get("id") != self.bot_id:
                        continue

                    self.stats["bot_messages"] += 1

                    # Must have image attachment
                    image_url = self._extract_image_url(msg)
                    if not image_url:
                        self.stats["skipped_no_attachment"] += 1
                        continue

                    # Parse version
                    version = parse_version(msg)
                    if version not in self.target_versions and version != "unknown":
                        self.stats["skipped_version"] += 1
                        continue

                    # Determine if upscaled or grid
                    upscaled = is_upscaled(msg)
                    image_type = "upscaled" if upscaled else "grid"

                    if upscaled:
                        self.stats["upscaled"] += 1
                    else:
                        self.stats["grids"] += 1

                    # Build flair
                    flair = f"midjourney_v7:v{version}"
                    if image_type == "grid":
                        flair += ":grid"

                    # Extract prompt and raw message content
                    prompt = self._extract_prompt(msg)
                    raw_content = msg.get("content", "")

                    metadata = {
                        "post_id": msg.get("id", ""),
                        "post_title": prompt[:200],
                        "flair": flair,
                        "subreddit": f"discord:{channel_name}",
                        "message_content": raw_content[:500],
                        "is_upscaled": "true" if upscaled else "false",
                    }

                    success = self.download_image(
                        image_url, source="discord_midjourney_v7", metadata=metadata
                    )

                    pbar.update(1)
                    pbar.set_postfix(
                        dl=self.stats["downloaded"],
                        ch=channel_name,
                        ver=f"v{version}",
                        type=image_type,
                    )

                    if success:
                        channel_downloaded += 1
                        time.sleep(self.download_delay + random.uniform(0, 0.5))

                # Progress report every 10 pages
                page_num = self.stats["messages_scanned"] // 100
                if page_num % 10 == 0 and page_num > 0:
                    print(
                        f"  #{channel_name}: scanned {self.stats['messages_scanned']} msgs, "
                        f"{self.stats['downloaded']} downloaded total",
                        flush=True,
                    )

            self.stats["channels_scraped"] += 1
            print(
                f"  #{channel_name}: done ({channel_downloaded} images from this channel)",
                flush=True,
            )

        pbar.close()
        self.print_stats()

    async def run_async(self):
        """Compat — just calls sync run()."""
        self.run()


def main():
    parser = argparse.ArgumentParser(
        description="Scrape Midjourney images from Discord"
    )
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--max-images", "-n", type=int, default=50000,
                        help="Maximum images to download")
    parser.add_argument("--force", action="store_true",
                        help="Ignore existing manifest (fresh start)")
    parser.add_argument("--channels", type=str, default=None,
                        help="Comma-separated channel names to scrape (e.g. general-1,general-2)")
    args = parser.parse_args()

    from configs import load_config
    config = load_config(args.config)

    channels = args.channels.split(",") if args.channels else None

    scraper = MidjourneyScraper(
        config,
        max_images=args.max_images,
        force=args.force,
        channels=channels,
    )
    scraper.run()


if __name__ == "__main__":
    main()
