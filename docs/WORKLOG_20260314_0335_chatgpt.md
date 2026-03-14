# Worklog: ChatGPT (GPT-Image-1 / GPT-Image-1.5) Curation

**Started**: 2026-03-14 03:35 UTC
**Generator**: GPT-Image-1, GPT-Image-1.5 (OpenAI, integrated into ChatGPT)
**Target**: 5-10K validated photorealistic images

## Phase 0: Intake

- User knows Higgsfield has GPT-Image-1.5 (https://higgsfield.ai/gpt-1.5)
- No official bot account on X.com
- Reddit needs strict filtering (date gate + flair gate)
- **User corrections**: DALL-E 2/3 ≠ GPT-Image-1/1.5. Civitai tool_id unreliable. Reddit provenance must be certain.

## Phase 1: Source Research (completed)

### Viable Sources
| Source | Model | Volume | Provenance | Format |
|--------|-------|--------|------------|--------|
| Civitai on-site gen | v1 (mvid 1733399) | ~14,000 API, ~3% CDN alive | Guaranteed | JPEG |
| Civitai on-site gen | v1.5 (mvid 2512167) | ~4,100 API, ~14-45% CDN alive | Guaranteed | JPEG |
| Higgsfield | openai_hazel + text2image_gpt | 84 total | Good | PNG/JPEG |
| Reddit r/AIArt | "Image - ChatGPT" flair | ~600-750/month | User-declared flair | PNG/JPEG |
| Reddit r/dalle2 | "GPT-4o" flair | ~130 total | User-declared flair | PNG/JPEG |

### Key Finding: Civitai CDN Mass Purge
- ~50-95% of GPT-Image CDN URLs return 500 (permanently gone, confirmed from multiple IPs)
- v1 (oldest, April 2025+): ~3% success rate
- v1.5 (newest, Dec 2025+): ~14-45% success rate (newest pages up to 100%)
- This drastically reduced expected Civitai yield from ~18K to ~1K-2K

### Generator Profile
- **Resolutions**: 1024x1024, 1536x1024, 1024x1536 (API). v1.5 may have higher res.
- **Aspect ratios**: 1:1, 3:2, 2:3 only
- **GPT-Image-1**: Released March 25, 2025 (Plus/Pro), April 1, 2025 (all tiers)
- **GPT-Image-1.5**: Released December 16, 2025
- **Before April 1, 2025**: ChatGPT used DALL-E 3 (different model) — date gate critical

## Phase 2: Scraping

### Higgsfield (completed)
- 84/84 downloaded, 0 failures
- Models: `openai_hazel` (62, PNG), `text2image_gpt` (22, JPEG)
- Confirmed only 84 total via full pagination — GPT-Image not popular on Higgsfield

### Civitai (in progress)
- **v1.5** (PID 81377): Scraping model_version:2512167, ~14% CDN success
- **v1** (PID 251290): Scraping model_version:1733399, ~3% CDN success
- Added 4 concurrent download workers (was 1 sequential) — ~4x throughput
- Fixed progress bar to track total items processed, not just successes
- Estimated yield: ~200-600 from v1.5, ~100-400 from v1

### Reddit (completed)
- **1,276 images downloaded** from 11,554 fetched posts
- Strict filtering: date gate (April 1, 2025+), flair gate (only "Image - ChatGPT" and "GPT-4o"), title keywords, domain allowlist
- Filter stats: 5,924 wrong flair, 1,960 too old (DALL-E 3 era), 4,242 duplicate, 162 title keywords
- r/AIArt was primary source (high volume), r/dalle2 supplemental

## Phase 3: Validation

### Content Classification (JoyCaption booru tags)
- **57% overall rejection rate** (higher than Nano Banana's 18%)
- Dominant signal: "digital art" (50%+ of rejections) — GPT-Image heavily used for non-photo content
- Other signals: illustration, anime, cartoon, digital painting, cgi, sketch

### Keyword Refinement
- **Added**: "clipart", "clip art", "graphic design", "minimalistic art"
- **Tested and rejected**: "logo", "icon", "silhouette", "sticker", "badge", "emblem", "decal"
  - These appear as *elements within* photorealistic images (Nike logo on shirt, boat silhouettes at sunset)
  - Too many false positives — reverted 34 wrongly-rejected images

### Spot Checks
- **Accepts**: 10/10 correct (photorealistic portraits, product shots, architecture, surreal photorealistic)
- **Rejects**: 7/8 correct (cartoon, illustration, anime, vector art)
- **False negative found**: "Happy Thanksgiving" vector/clipart slipped through because JoyCaption hallucinated wrong content ("photograph, black background, minimal light"). Manually moved to rejected. Added "minimalistic art" keyword which catches this case.
- **False positive concern**: JoyCaption sometimes tags photorealistic images containing logos/silhouettes. Must keep reject keywords narrow to avoid false positives.

### Structural Validation
- ~5-8% structural rejection rate (non-standard aspect ratios, too small)
- GPT-Image has only 3 aspect ratios (1:1, 3:2, 2:3) — very tight structural filter

## Current State (as of 05:00 UTC)

| Metric | Count |
|--------|-------|
| Validated (images/) | ~497 |
| Staging (awaiting sweep) | ~1 |
| Rejected | ~977 |
| Manifest entries | ~1,500+ |

### Scrapers Status
- **Higgsfield**: Done (84 images)
- **Reddit**: Done (1,276 images)
- **Civitai v1.5**: Running (~200+ downloads so far)
- **Civitai v1**: Running (~50+ downloads so far)

## Pending

- [ ] Continue Civitai scraping until both v1 and v1.5 exhausted
- [ ] Caption+pipeline sweeps as Civitai images arrive
- [ ] FSD scoring on final validated images
- [ ] Final metadata.csv rebuild with source breakdown
- [ ] Manifest deduplication
- [ ] Distill lessons into LESSONS_CHATGPT.md
