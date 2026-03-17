# Lessons from Seedream 4.0 / 4.5 / 5.0 Lite Curation

Distilled from the March 2026 curation run. 1,814 validated images from Civitai,
Higgsfield, AIGCArena, and Yodayo. See `WORKLOG_20260314_1930_seedream4.md` for timeline.

## Source Viability

| Source | Viability | Notes |
|--------|-----------|-------|
| Civitai on-site gen | **Best provenance, CDN alive** | 23.1% of dataset. 0 download failures. |
| Higgsfield | **Largest volume, NSFW risk** | 71.9% of dataset. Bypasses safety filters — must add NSFW keywords. |
| AIGCArena | **Excellent provenance, small** | 1.7% of dataset. ByteDance's own arena. Also has other generators. |
| Yodayo | **Good provenance, Cloudflare** | 3.3% of dataset. Needs Playwright stealth for Cloudflare bypass. |
| Reddit | **Dead end** | No Seedream presence. Not a consumer-facing tool. |

## Key Findings

### 1. Higgsfield Bypasses Safety Filters
18% of initially validated images were NSFW. Higgsfield reportedly bypasses ByteDance's
content filters. **For any generator scraped from Higgsfield, add NSFW rejection keywords.**

### 2. CDN Health Varies by Generator
Civitai CDN: 0% failure for Seedream (Sep 2025+) vs 85-97% failure for ChatGPT GPT-Image
(Apr 2025+). Newer models have healthier CDNs. Scrape early regardless.

### 3. FSD Detection Rate: 11.7%
Very low. Seedream uses DiT + MoE (diffusion transformer with mixture-of-experts) —
fundamentally different from standard U-Net diffusion. This is the lowest detection
rate we've seen (vs 96% ChatGPT, 72% Grok, 33% Nano Banana).

### 4. New Scraper Patterns: Playwright + Stealth
Two new scrapers built for anti-bot protected platforms:
- **Yodayo**: Cloudflare bypass via `--disable-blink-features=AutomationControlled` +
  webdriver override. API calls via `page.evaluate(fetch(...))`.
- **AIGCArena**: `a_bogus` ByteDance anti-bot. Must load page first to initialize
  tokens, then call POST API from browser context.

### 5. AIGCArena Is a Multi-Generator Gold Mine
ByteDance's arena platform has server-side generations from 8 models: Imagen 4 Ultra,
Seedream v4.5, FLUX.2 [max], Gemini 3 Pro, Seedream 5.0 Lite, Gemini 2.5 Flash,
GPT Image 1.5, Hunyuan 3.0. All with excellent provenance. Reusable for future runs.

### 6. Reddit Is Not Universal
Unlike Grok and ChatGPT, Seedream has virtually no Reddit presence. Not every
generator has a Reddit community. Skip research early when web searches show zero results.

### 7. API Response Structures Vary Wildly
- Yodayo: `posts[].photo_media[].text_to_image.model`
- AIGCArena: `Resources[].ModelImages[].ImageUri` + `Resources[].ModelName`
- Civitai: `items[].meta.civitaiResources[].modelVersionId`
- Higgsfield: `items[].results.raw.url` + `items[].params.prompt`

Always inspect actual API responses with curl/Playwright before coding scrapers.

## Dataset Summary

| Metric | Value |
|--------|-------|
| Validated images | 1,814 |
| FSD detection rate | 11.7% |
| Source mix | Higgsfield 71.9%, Civitai 23.1%, Yodayo 3.3%, AIGCArena 1.7% |
| Model versions | 4.0: 62.0%, 4.5: 36.0%, 5.0 Lite: 2.0% |
| Rejection rate | 55% (content 41% + NSFW 18%) |
