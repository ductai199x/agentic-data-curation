# Lessons from FLUX.1 Curation

Distilled from the March 2026 curation run. 23,296 validated images from Civitai,
Tensor.Art, Yodayo, OpenArt, and Higgsfield. See `WORKLOG_20260315_flux.md` for timeline.

## Source Viability

| Source | Viability | Notes |
|--------|-----------|-------|
| Civitai on-site gen | **Best volume + provenance** | 92.7% of dataset. Dev gallery has 14M+ images. |
| Tensor.Art | **Good but pagination capped** | 5.5%. API caps at ~1K posts regardless of sort order. |
| Yodayo | **LoRA contaminated, CDN purged** | 1.2%. 64.5% LoRA contamination on dev. 90% CDN 404s. |
| OpenArt.ai | **Tiny but clean** | 0.3%. Only 125 FLUX items total. Public REST API (no Playwright needed). |
| Higgsfield | **No FLUX.1 base models** | 0.3%. Only flux_kontext (94 posts). No dev/schnell/pro. |
| Freepik | **Scraper built, untested** | REST API, needs API key. Can't filter by model. |

## Key Findings

### 1. "digital art" Is Too Generic to Reject
JoyCaption tags AI-generated photorealistic images as "photograph, digital art, realistic style"
— using "digital art" as a style qualifier, not a medium. Rejecting on "digital art" caused
3,498 false rejections (40.8% of all rejections). **Removed from all generator configs.**
Also recovered 1,413 ChatGPT, 453 Seedream, and 733 Nano Banana images retroactively.

### 2. Civitai Async Scraper Deadlocks
The async producer/consumer scraper (`scrapers/civitai.py`) hangs after ~100-400 downloads.
Root cause: `asyncio.to_thread` threads blocked on slow HTTP responses, exhausting the thread
pool. `asyncio.wait_for` can't cancel blocked threads. **Fixed by writing a synchronous
scraper** (`scrapers/civitai_simple.py`) — slower but never hangs. ~0.5-0.8 img/s per instance,
run multiple versions in parallel for throughput.

### 3. FLUX Gallery Depth Varies Wildly by Version
| Version | Gallery depth | Notes |
|---------|--------------|-------|
| Dev (691639) | ~14,000+ | Open-weight, massive uploads. Deepest gallery. |
| Schnell (699279) | ~7,000 | Exhausted after full pagination. |
| Pro 1.1 (922358) | ~3,900 | API-only model, high on-site gen ratio. |
| Krea Dev (2068000) | ~3,600 | Newest variant. |
| Pro 1.1 Ultra (1088507) | ~2,400 | High-res (2048x2048+). |
| Kontext Pro (1892509) | ~130 | Small gallery. |

### 4. FSD Detection: 81.5%
Mean z-score: -7.07. Significantly higher than Seedream (11.7%) despite both being DiT
architectures. FLUX.1 uses MMDiT (rectified flow transformer) while Seedream uses DiT+MoE.
The architecture difference matters for FSD detection.

### 5. FLUX Open-Weight = NSFW Flood
42% of validated images have NSFW tags (nude, topless, lingerie, etc.). FLUX has no safety
filters on open-weight models. This is expected and acceptable per content policy (keep
everything except exposed genitals).

### 6. Tensor.Art API Pagination Cap
Tensor.Art's post API caps at ~1,000 posts regardless of sort order (NEWEST, MOST_LIKED,
HOT, FRESH_FINDS). Different sorts return overlapping content. The HMAC signing headers
expire after prolonged use — need fresh Playwright capture for each run.

### 7. Multiple Sync Scrapers > One Async Scraper
Running 3 `civitai_simple.py` instances on different model versions (Dev, Schnell, Krea)
achieved ~2 img/s combined — faster and more reliable than the async scraper which frequently
deadlocked.

### 8. Pass Rate Improved Dramatically After "digital art" Fix
Before removing "digital art": ~40% pass rate (mostly false rejections).
After removing: ~62% pass rate. This is a massive efficiency improvement for future runs.

## Dataset Summary

| Metric | Value |
|--------|-------|
| Validated images | 23,296 |
| FSD detection rate | 81.5% |
| Mean z-score | -7.07 |
| Source mix | Civitai 92.7%, Tensor.Art 5.5%, Yodayo 1.2%, OpenArt 0.3%, Higgsfield 0.3% |
| Model versions | Dev 44.1%, Schnell 23.4%, Pro 1.1 11.9%, Krea 10.6%, Ultra 7.2% |
| Total downloads | 37,462 |
| Pass rate | 62% |
| New scrapers built | tensorart.py, openart.py, freepik.py, civitai_simple.py |
