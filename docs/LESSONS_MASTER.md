# Master Lessons — Agentic Data Curation

The most impactful lessons from curating 162K+ images across 10 generators.
These apply to every current and future curation run. Per-generator details
are in `docs/LESSONS_<GENERATOR>.md`.

---

## Pipeline & Validation

### 1. Audit captions.json for errors before running pipeline
JoyCaption outages produce error entries that silently pass through the pipeline,
causing mass rejection. This hit 5 out of 10 datasets — 30K+ images wrongly
rejected in Midjourney alone. Always run a quick error count before pipeline:
```python
import json; d=json.load(open("captions.json")); print(sum(1 for v in d.values() if "error" in v), "errors")
```

### 2. Don't filter on generic keywords
"digital art" was in REJECT_KEYWORDS and JoyCaption tagged photorealistic images
with it as a style qualifier. Removing it recovered 2,000+ images across 4 datasets.
When in doubt about a keyword, keep the image — false rejects are worse than false
accepts because rejected images get deleted.

### 3. FSD: tag only, never filter
FSD detection rates range from 21% (Seedream) to 98% (GPT-Image). Using FSD as a
filter would destroy datasets for generators with low detection. FSD is metadata
for downstream consumers, not a gatekeeper.

### 4. Spot-check both rejected AND accepted images
Rejected images catch false positives (overly aggressive keywords). Accepted images
catch contamination that slipped through (wrong generator, real photos, screenshots).
Sample 10-20 from each after every pipeline run.

---

## Source Selection

### 5. Source provenance beats any classifier
Higgsfield has 95% pass rate because every image is generated on-platform with
full metadata. Reddit has ~10% yield because it's full of screenshots and memes.
A trusted source with clean provenance is worth 10× a noisy source. Prioritize
generator galleries and on-site generation APIs over social media.

### 6. Civitai: model_version_id only, never tool_id
`tool_id` includes user uploads from multi-tool ComfyUI workflows — anyone can
tag anything. `model_version_id` restricts to on-site generation only, which
guarantees the specific model was used. This rule has no exceptions.

### 7. Scrape now, validate later
Downloads are time-sensitive: CDN URLs expire, APIs change, accounts get banned,
platforms add rate limits. Validation can always happen later when GPU is available.
If GPU isn't free, accumulate images in staging and move on.

---

## Building Scrapers

### 8. Check what already exists before building
We have 14 scrapers covering Civitai, Higgsfield, Twitter, Reddit, Discord,
Instagram, Recraft, Tensor.Art, Yodayo, OpenArt, AIGCArena, and Freepik. Most
new generators can reuse an existing scraper with just a config change. Run
`ls scrapers/` and `ls configs/` before writing any code.

### 9. Test APIs inline before building scrapers
A 5-line curl or python snippet confirms whether an API works, what the response
structure looks like, and what auth is needed. This takes 2 minutes and saves
hours of building a scraper for a dead-end API.

### 10. Use Playwright for reconnaissance, then decide the approach
Playwright is the universal tool for understanding a new platform:
- **Intercept API calls**: load the page, watch Network tab via `page.on("response")`
  to discover real API endpoints, auth patterns, and pagination
- **Bypass anti-bot**: `page.evaluate(fetch(...))` makes API calls from the browser
  context, automatically including cookies, tokens, and signing headers (solved
  AIGCArena's `a_bogus`, Tensor.Art's HMAC)
- **Cloudflare stealth**: `--disable-blink-features=AutomationControlled` +
  `navigator.webdriver` override bypasses most Cloudflare checks

After recon, choose the right approach:
- **Full Playwright** when the platform requires browser context (Instagram grid
  extraction, Recraft scrolling)
- **Hybrid** when you can capture auth headers once then switch to plain requests
  (Tensor.Art: Playwright captures HMAC, then `requests.post()` for pagination)
- **Plain HTTP** when the API is open (Higgsfield REST, OpenArt, Civitai TRPC)

### 11. Extract data from the DOM, not by navigating pages
Navigating to individual pages is slow, fragile, and often blocked (Instagram
post pages render blank in headless mode). Instead:
- Scroll the current page and harvest data from the DOM
- Instagram: grid images are already full-res in the DOM — no need to click posts
- Use `page.evaluate()` to extract structured data in one call

### 12. Extend BaseScraper, don't reinvent
`BaseScraper` provides content-addressed storage, manifest resume, download
deduplication, signal handling, and progress tracking. Every scraper we built
extends it. Starting from scratch means re-implementing all of that.

### 13. Make everything resumable from the start
Every scraper, classifier, and processing script must be able to stop and restart
without losing progress or re-doing work. This is not an optimization — it's a
requirement. Long-running jobs WILL get interrupted (GPU reclaimed, rate limits,
cookie expiry, context window compaction, machine restarts).
- Scrapers: manifest tracks downloaded URLs and hashes — skip on restart
- batch_classify: captions.json tracks processed images — skip on restart
- Grid splitter: check if tile files exist before splitting
- Instagram: post_id fast-skip avoids revisiting downloaded posts
Design for interruption from line 1, not as an afterthought.

---

## Operations

### 14. Parallelize everything
- Scrape from multiple sources simultaneously
- Build new scrapers while existing ones run
- Caption while scraping (producer/consumer)
- Use all CPU cores for batch operations (grid splitting: 256 workers = 4 min vs 7 hours)
- Never wait sequentially when you can overlap
