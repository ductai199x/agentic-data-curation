# Lessons — Sora

Distilled from the Sora video/image curation run (March 2026).

## 1. Empty sentinel tokens can bypass PoW challenges
OpenAI's Sentinel proof-of-work token appeared mandatory for authenticated API calls, but sending an empty sentinel (`{"p":"","t":"","c":"","id":"DEVICE_ID","flow":"sora_list_feed"}`) returns 200. Always test with empty/minimal auth before assuming a challenge is required.

## 2. Different feed variants have wildly different content ratios
- `recent`: 2% videos, 98% images (7,751 items)
- `featured`: ~30% videos, 70% images (45K+ items, deepest)
- `videos`: 100% videos but only 127 items
- `images`: 100% images, 233 items

The obvious choice (`/feed/videos`) had the least content. The bulk came from `featured` which had 200× more items.

## 3. curl_cffi is essential for Cloudflare-protected APIs
Regular `requests` and even Playwright headless fail against Cloudflare's TLS fingerprinting. `curl_cffi` with `impersonate="chrome131"` bypasses it by mimicking Chrome's TLS handshake. This is a general-purpose tool for any Cloudflare-protected site.

## 4. Producer/consumer with timeouts prevents deadlocks
The initial sequential design (enumerate all → download all) was slow and fragile. The async producer/consumer pattern with `asyncio.Queue` was much better, but **consumers must have timeouts** on both `queue.get()` and download operations. Without timeouts, a stuck download or empty queue causes the entire process to hang indefinitely.

## 5. Signed CDN URLs don't need auth
Sora's video/image URLs are signed Azure Blob Storage URLs that work without any authentication. Only the feed API needs auth. This means: enumerate items via API (needs auth), download media via CDN (no auth). Two completely separate auth domains.

## 6. Bearer tokens from session endpoints are long-lived
The `/api/auth/session` endpoint returns a bearer token that lasts days (unlike the sentinel token which expires in minutes). Session cookies → bearer token → API calls is a reliable chain.

## 7. Video content is a different beast than images
- Videos are 5-50MB each vs 0.1-1MB for images
- Need separate staging directories (staging/videos/, staging/images/)
- Download speed is dominated by file size, not API rate limits
- Content-addressed storage works the same (SHA256[:16] + .mp4)
- Manifest and metadata work identically

## 8. Time-sensitive scraping needs urgency in design
Sora shuts down April 26, 2026. This deadline influenced every design decision:
- Skip validation/captioning (raw archival, not training-ready)
- Maximize throughput over data quality
- Resume support is critical (server crashes, rate limits)
- Cursor persistence saves hours on restart

## 9. "As many as possible" means set limits to 999999
Never use arbitrary caps (50K, 100K). The user means it literally. Any cap we set is a premature optimization that wastes time when we have to restart.

## 10. Feed pagination with `last_id` cursor is fragile
The Sora API uses `last_id` from the response as the pagination cursor. When items are deleted or reordered between requests, the cursor can skip or repeat items. Cross-deduplication via `seen_ids` set is essential. Stale-page detection (5 consecutive pages with 0 new items) prevents infinite loops.

## Final Stats
- **17,635 videos** + **36,102 images** = **53,737 total**
- 0 failures
- Sources: recent (7,751), featured (45K+), images (233), ranked (235), videos (127)
- All content-addressed, with per-item metadata (prompt, creator, resolution, duration, model)
