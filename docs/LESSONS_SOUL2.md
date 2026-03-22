# Lessons — Higgsfield Soul 2.0 Curation

Distilled from the Soul 2.0 curation run (March 2026).
25,796 validated images from Higgsfield community gallery.

## Key Insights

### 1. Higgsfield is the cleanest source we have
- 95% pass rate (25,796/27,282) — by far the highest of any source
- 100% provenance — every image is generated on-platform with model metadata
- PNG format, CloudFront CDN, no re-encoding
- The only source where we can trust the data almost blindly

### 2. Model ordering matters for scraping efficiency
- Order models small-to-large so you get quick feedback on smaller models first
- ai_influencer (1,001) → soul_cinematic (545) → soul_v2 (2,370) → soul_v1 (31,784)
- Spot-check the small models before committing to the 31K soul_v1 scrape

### 3. canvas_soul should be excluded
- Only 56 posts, but uses `input_images` for inpainting
- Output is conditioned on user-uploaded photos — provenance contamination
- Same logic applies to any Higgsfield model with `input_images` in params

### 4. Soul v1 dominates the volume
- soul_v1: 86% of validated images (22K+)
- soul_v2: 8.5%, soul_cinematic: 2%, ai_influencer: 3.4%
- v2 and cinematic were released later — less community adoption

### 5. AI Influencer variant is unique
- 1,001 posts, all 1536×2752 (9:16 portrait)
- Designed specifically for generating consistent AI personas
- Useful as ground-truth for AI influencer detection research

### 6. Higgsfield scraper NoneType bug
- `results.get("raw", {})` crashes when API returns None for an item
- Fix: add `if results is None: continue` guard
- Manifests on long scrapes — API occasionally returns null entries

### 7. Separate configs by architecture, not brand
- Soul 2.0 models share the same architecture but different fine-tuning
- Keeping all Soul variants in one config/dataset makes sense
- But exclude models with fundamentally different generation modes (canvas_soul)

## Source Quality

| Metric | Value |
|--------|-------|
| Source | Higgsfield community gallery |
| Raw downloads | 27,282 |
| Validated | 25,796 |
| Pass rate | 95% |
| Rejected | 1,486 (5%) |
| Format | PNG |
| Models | soul_v1, soul_v2, soul_cinematic, ai_influencer |
| Provenance | 100% (on-platform generation) |
