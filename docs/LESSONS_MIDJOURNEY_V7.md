# Lessons — Midjourney v7 Curation

Distilled from the Midjourney v7 Discord curation run (March 2026).
67,778 validated images from Discord general-1 channel.

## Key Insights

### 1. midjourney.com is NOT viable for scraping
- Cloudflare Turnstile blocks all automated access to the explore page
- Only ~50 static images retrievable from the top feed
- No public gallery API, no user profile browsing
- Discord is the only viable source for Midjourney images

### 2. Discord REST API is excellent for scraping
- Simple REST API: `GET /api/v10/channels/{id}/messages?limit=100&before=SNOWFLAKE`
- Snowflake-based pagination: `snowflake = (unix_ms - 1420070400000) << 22`
- Filter by bot author ID (936929561302675456) to get only Midjourney generations
- CDN URLs are public but expire in ~24h — download immediately
- Rate limit: ~5 req/5s per route, use 3s delay between API calls
- 50,000 images from a single channel in ~16 hours

### 3. Version detection requires two signals
- Midjourney doesn't embed version in image metadata
- **Explicit**: `--v 7` in prompt text or `_v7_` in component `custom_id`
- **Default by date**: If no explicit flag, use message timestamp against known defaults:
  - v6: Jul 2024 – Jun 17, 2025
  - v7: Jun 17, 2025 – present
- Never label as "unknown" — either confirm the version or skip the image
- This pattern applies to any future version scraping

### 4. Grid splitting is the biggest volume multiplier
- Midjourney posts 2×2 grids for initial generations (~75% of all images)
- Upscaled images are singles (~25%)
- Detect grids by dimensions (2× known base tile) NOT by flair tags
- "Upscaled" in Discord message content distinguishes singles from grids
- The `:grid` flair was unreliable — tagged base tiles as grids
- 30,169 grids → 120,676 tiles with 256-worker multiprocessing in 4 minutes
- PNG compression is the bottleneck — parallelism is essential

### 5. Known base tile dimensions are critical
- Midjourney v7 has ~48 known base tile sizes (1024×1024, 1456×816, 896×1344, etc.)
- Grid sizes are exactly 2× the base tile (zero gap between tiles)
- Images > 3.5 MP with even dimensions are almost certainly grids
- Build the lookup table from empirical data, then verify with spot checks

### 6. One Discord channel = massive volume
- general-1 alone yielded 50,000 downloads → 67,778 validated (after grid split)
- 19 more general channels + 5 themed channels remain untapped
- Total potential: 1M+ images from full Discord scrape

### 7. Error captions cause mass rejection
- 30,300 images had JoyCaption error captions (connection refused)
- Pipeline treated these as content-rejected — all moved to rejected/
- Always verify JoyCaption is running before captioning
- Always audit captions.json for error entries before running pipeline
- Those 30K images were permanently lost (rejected dir cleaned up)

### 8. Tile naming preserves traceability
- Tiles named `{parent_hash}_0.png` through `_3.png`
- Parent hash traces back to the original grid image
- Manifest updated in-place: grid rows replaced with 4 tile rows each

## Source Quality

| Metric | Value |
|--------|-------|
| Channel | general-1 (1 of 20+) |
| Raw downloads | 50,000 |
| After grid split | ~146,000 |
| Validated | 67,778 |
| Pass rate | 46% (low due to 30K error captions) |
| True pass rate | ~70% (excluding error captions) |
| Format | JPEG (from Discord CDN) |
| Version mix | v7 100% |
