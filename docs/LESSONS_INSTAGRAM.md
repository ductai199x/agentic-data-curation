# Lessons — Instagram AI Influencer Scraping

Distilled from the Instagram AI influencer curation run (March 2026).
11,797 images from 57 confirmed AI influencer accounts.

## Key Insights

### 1. Grid extraction >> post-page navigation
- Individual post pages (`/p/XXXXX/`) render blank in headless Playwright — Instagram
  detects automation on that route
- Profile grid pages work fine — and the DOM already contains full-res images for
  all visible posts
- Scrolling the grid + extracting CDN images from DOM = ~2 img/s (60× faster than
  visiting each post page)
- No need to click posts or open modals — just scroll and harvest

### 2. Instagram CDN URL rewriting breaks downloads
- Attempted to force JPEG by changing `dst-webp` → `dst-jpg` in CDN URLs
- This causes 404s — Instagram CDN validates the format parameter server-side
- Accept whatever format the CDN serves (WebP or JPEG) — both are full resolution
- WebP images are the same resolution as JPEG (1440×1920), just different encoding

### 3. cf_clearance cookies are TLS-fingerprint-bound
- Cloudflare Turnstile `cf_clearance` cookies cannot be transferred between browser
  and Playwright/curl — they're bound to the TLS fingerprint of the client that solved
  the challenge
- This means imginn.com and similar Instagram viewers with Cloudflare protection
  can't be scraped via cookie transfer
- Direct Instagram scraping with Playwright + session cookies is more reliable

### 4. Instagram session cookies expire quickly
- `sessionid` cookies expire within ~1 hour of inactivity from a different client
- If scraper stops working (blank pages), first thing to check is cookie freshness
- Always re-export cookies from browser before a new scraping session

### 5. srcset contains the highest resolution
- Instagram `<img>` elements have `srcset` with multiple resolutions
- Pick the largest width from srcset — this gives 1440px+ images
- `naturalWidth` only reflects what the browser loaded (depends on viewport)
- `og:image` meta tag is always a 640×640 thumbnail — don't use it

### 6. Many AI influencer accounts are video-heavy
- emilypellegrini: only 24/127 posts had static images (19%)
- The scraper visits video posts, finds no extractable image, moves on
- Grid extraction mitigates this — it only picks up images already in the DOM,
  skipping video thumbnails naturally

### 7. Fast-skip via post_id is essential for re-runs
- Without it, re-running scrolls every profile and visits every post again
- Store downloaded post_ids in manifest and check before making any HTTP request
- Also store "no image found" post_ids to skip video posts on re-run

### 8. Aggressive scrolling after stale detection
- Instagram sometimes pauses lazy loading mid-scroll
- Normal scrolling: scroll to bottom, wait 4-7s
- After 3 stale scrolls: scroll up 500px, back down, overshoot by 100px — retriggers
  the intersection observer
- Stop after 6 total stale scrolls (3 normal + 3 aggressive)

### 9. This is an evaluation set, not training data
- AI influencer images have unknown generators — can't attribute to specific models
- Heavy Instagram compression (JPEG re-encoding) degrades forensic signal
- Value is as a real-world test set: images "in the wild" on social media
- Tests what detectors actually encounter in practice

## Source Quality

| Metric | Value |
|--------|-------|
| Accounts scraped | 57 |
| Total images | 11,797 |
| Failures | 0 |
| Total time | ~2.5 hours |
| Throughput | ~2 img/s |
| Format | JPEG (some WebP) |
| Resolution | Mostly 1440×1920 |
| 404 accounts | 1 (jessicaa.foster) |
| Video-only accounts | ~3-4 |
