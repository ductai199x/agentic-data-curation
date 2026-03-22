# Worklog: Midjourney v7 Curation

**Started**: 2026-03-20 01:00 UTC
**Generator**: Midjourney v7 (Apr 2025)
**Target**: As many v7 images as possible from Discord

## Phase 0: Intake

- Sources: Midjourney Discord server (20+ general channels)
- midjourney.com explore page: too locked down (Cloudflare Turnstile, 50 images max)
- Civitai: not available (closed-source model)
- GPU not available — scrape only, validate later

## Phase 1: Research

### midjourney.com
- Cloudflare Turnstile blocks pagination — only 50 static images from explore top feed
- CDN works for individual downloads but requires browser context
- User profile pages don't expose other users' galleries
- NOT viable as primary source

### Discord REST API
- Auth token works, 20+ general channels accessible
- Midjourney Bot (ID 936929561302675456) posts every generation
- Version info in component custom_ids and --v content flags
- CDN URLs public but expire in ~24h
- Pagination via snowflake IDs, 100 msgs/page
- Estimated 60K+ v7 images from recent history

### Generator Profile
- v7: Apr 2025, 1024x1024 base, up to 4096x4096 with upscalers
- v8 Alpha: Mar 17, 2026, native 2K, GPU+PyTorch rewrite
- Strict PG-13 safety filter
- PNG output with prompt in metadata
- Closed-source LDM architecture

### Version Detection Strategy
Midjourney doesn't embed version in image metadata — must infer from Discord message:
1. **Explicit `--v X` in prompt** or **`_vX_` in component custom_id** → confirmed version
2. **No version specified** → use message date against known default version windows:
   - v5: default ~May 2023 – Dec 2023
   - v5.2: default ~Dec 2023 – Jul 2024
   - v6: default ~Jul 2024 – Jun 17, 2025
   - v7: default Jun 17, 2025 – present
3. **Skip** any image outside known default window without explicit version

This eliminates all "unknown" labels. For v7 specifically:
- Explicit `--v 7` or `_v7_` in components → v7
- No version + date ≥ 2025-06-17 → v7 (default)
- Skip everything else

### Grid Splitting
- Midjourney Discord posts 2x2 grids (4 variations) for initial generations
- Upscaled images are singles (message content contains "Upscaled")
- Grid detection: dimensions match 2× known base tile AND NOT upscaled
- Split at exact center (zero gap between tiles)
- Tile naming: `{parent_hash}_0.png` through `{parent_hash}_3.png`

Known v7 base tile sizes → grid sizes:
- 1024×1024 → 2048×2048 (1:1)
- 1456×816 → 2912×1632 (16:9)
- 896×1344 → 1792×2688 (2:3)
- 928×1232 → 1856×2464 (3:4)
- etc. (48 known base dimensions)

## Phase 2: Scraping

### Discord Channel Scrape — Pass 1 (general-1 only)
- 50,000 images from general-1 channel only (hit max-images cap)
- 22,075 confirmed v7 + 27,925 unknown (pre-date-detection logic)
- 4,010 upscaled singles + ~46,000 grids/base tiles
- 19 more general channels + 5 themed channels remaining
- ...
