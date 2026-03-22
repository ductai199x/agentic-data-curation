# Lessons — Recraft V3/V4 Curation

Distilled from the Recraft v3/v4 curation run (March 2026).
6,901 validated images from Recraft community gallery.

## Key Insights

### 1. Recraft is a single-source generator
- Closed-source, API-only model — no Civitai, no open weights
- The community gallery at recraft.ai is the ONLY source
- No Reddit presence, no Twitter bot, no third-party platforms
- This limits volume but guarantees 100% provenance

### 2. The community API has a 1,000-item cap per query
- `GET /api/images/community?imageParentType=realistic_image&model=recraftv3`
- Each query combo returns max 1,000 results
- Workaround: iterate all 19 combos (16 V3 sub-types + 3 V4 model variants)
- V3 sub-types: `realistic_image`, `realistic_image/b_and_w`, `realistic_image/enterprise`,
  `realistic_image/evening_light`, etc.
- This got us ~8,157 total images

### 3. WebP-only output from the API
- Recraft serves WebP from its CDN (img.recraft.ai with imgproxy)
- HMAC-signed URLs — can't modify format parameters
- WebP is fine for our pipeline — PIL handles it, and the resolution is good

### 4. Strict safety filter is a provenance signal
- Recraft is AIUC-1 certified with strict NSFW filtering
- No explicit content in the dataset at all
- This means any NSFW content would indicate contamination (useful for QA)

### 5. V3 vs V4 have very different characteristics
- V3 (Oct 2024): 1MP max, 14 aspect ratios, 16 realistic sub-types
- V4 (Feb 2026): 1MP standard / 4MP Pro, fewer sub-types
- V4 Pro generates notably higher resolution images
- Version breakdown: v3 72%, v4 20%, v4_pro 8%

### 6. JoyCaption outage caused apparent 85% rejection
- First run: 1,263 validated out of 8,157 (15% pass rate)
- Investigation: 6,665 images had JoyCaption connection error captions
- After re-captioning: 6,901 validated (84% true pass rate)
- Lesson: ALWAYS audit captions.json for `"error"` entries before trusting pass rates

### 7. Realistic-only filter is important
- The `imageParentType=realistic_image` URL parameter filters out illustrations,
  vector art, icons, and other non-photorealistic content at the API level
- Without this filter, the community gallery is dominated by non-photorealistic content
- Pre-filtering at the API level >> post-download JoyCaption filtering

## Source Quality

| Metric | Value |
|--------|-------|
| Source | Recraft community gallery |
| Raw downloads | 8,157 |
| Validated | 6,901 |
| Pass rate | 84% (after re-captioning) |
| Format | WebP |
| Models | recraftv3, recraftv4, recraftv4_pro |
| NSFW content | None (strict safety filter) |
| Provenance | 100% (on-platform generation) |
