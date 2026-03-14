# Worklog: ChatGPT (GPT-Image-1 / GPT-Image-1.5) Curation

**Started**: 2026-03-14 03:35 UTC
**Generator**: GPT-Image-1, GPT-Image-1.5 (OpenAI, integrated into ChatGPT)
**Target**: 5-10K validated photorealistic images
**Result**: 497 validated images (below target — Civitai CDN purge was the primary blocker)

## Phase 0: Intake

- User knows Higgsfield has GPT-Image-1.5 (https://higgsfield.ai/gpt-1.5)
- No official bot account on X.com
- Reddit needs strict filtering (date gate + flair gate)
- **User corrections**: DALL-E 2/3 ≠ GPT-Image-1/1.5. Civitai tool_id unreliable. Reddit provenance must be certain.

## Phase 1: Source Research (completed)

### Viable Sources
| Source | Model | API Volume | CDN Alive | Format |
|--------|-------|-----------|-----------|--------|
| Civitai on-site gen | v1 (mvid 1733399) | ~14,000 | ~3% | JPEG |
| Civitai on-site gen | v1.5 (mvid 2512167) | ~4,100 | ~14% | JPEG |
| Higgsfield | openai_hazel + text2image_gpt | 84 | 100% | PNG/JPEG |
| Reddit r/AIArt | "Image - ChatGPT" flair | ~600-750/month | N/A | PNG/JPEG |
| Reddit r/dalle2 | "GPT-4o" flair | ~130 total | N/A | PNG/JPEG |

### Key Finding: Civitai CDN Mass Purge
- **50-97% of GPT-Image CDN URLs return 500** (permanently gone)
- Confirmed from multiple IPs — not rate limiting
- v1 (oldest, April 2025+): ~3% success rate → only 23 downloads from ~14K
- v1.5 (newest, Dec 2025+): ~11% success rate → only 76 downloads from ~4.1K
- This was the biggest surprise — expected ~18K downloadable, got ~100

### Generator Profile
- **Resolutions**: 1024x1024, 1536x1024, 1024x1536 (3 only)
- **Aspect ratios**: 1:1, 3:2, 2:3 only (very tight structural filter)
- **GPT-Image-1**: Released March 25, 2025 (Plus/Pro), April 1, 2025 (all)
- **GPT-Image-1.5**: Released December 16, 2025
- **Before April 1, 2025**: ChatGPT used DALL-E 3 — date gate critical for Reddit

### Dead Ends
- **X.com/Twitter**: No official bot account. Dead end.
- **Civitai tool_id**: Unreliable — anyone can upload with any tags.
- **PromptHero/NightCafe**: Provenance is user-tagged, not verified.

## Phase 2: Scraping Results

### Higgsfield (completed, 84 images)
- `openai_hazel`: 62 PNGs (GPT-Image-1.5)
- `text2image_gpt`: 22 JPEGs (GPT-Image-1)
- 0 failures — tiny but clean

### Civitai (completed, 115 images)
- v1.5 (mvid 2512167): 76 downloads from 688 processed (11%)
- v1 (mvid 1733399): 23 downloads from 1,419 processed (1.6%)
- Added 4 concurrent download workers to speed up, but CDN failures dominate
- Killed after ~10 min each — nearly 100% failure on deeper pages

### Reddit (completed, 1,276 images)
- **Strict filtering**: date gate (April 1, 2025+), flair gate (only "Image - ChatGPT" and "GPT-4o")
- r/AIArt: Primary source (~1,200 from "Image - ChatGPT" flair)
- r/dalle2: Supplemental (~76 from "GPT-4o" flair)
- Filter stats from 11,554 fetched posts:
  - 5,924 wrong flair (51%) — strict flair gate working
  - 1,960 too old (17%) — date gate catching DALL-E 3 era
  - 4,242 duplicate URLs (37%) — same posts across sort orders
  - 162 title keywords (1%)

### Total Downloads: 1,475
| Source | Downloads | % |
|--------|-----------|---|
| Reddit | 1,276 | 87% |
| Civitai | 115 | 8% |
| Higgsfield openai_hazel | 62 | 4% |
| Higgsfield text2image_gpt | 22 | 1% |

## Phase 3: Validation Results

### Content Classification (JoyCaption booru tags)
- **66% rejection rate** (much higher than Nano Banana's 18%)
- GPT-Image is extremely popular for non-photorealistic content
- Top signals: digital art (50%+), illustration, anime, cartoon, cgi, sketch

### Keyword Refinement
- **Added**: "clipart", "clip art", "graphic design", "minimalistic art"
- **Tested and REVERTED**: "logo", "icon", "silhouette", "sticker", "badge", "emblem", "decal"
  - These match elements WITHIN photorealistic images (Nike logo, boat silhouettes)
  - 34 false positives caught and reverted

### Structural Validation
- ~5-8% rejection rate on non-standard aspect ratios
- GPT-Image's 3 aspect ratios make this a very tight filter

### Spot Checks Summary
- Accepts: 13/14 correct (1 vector art false negative caught by "minimalistic art")
- Rejects: 7/8 correct (3 cartoon, 3 illustration, 1 borderline CGI)

### FSD Detection
- **0% detection rate** — FSD completely fails on GPT-Image
- All z-scores negative (mean -7.96, min -55.14, max 0.48)
- GPT-Image uses autoregressive architecture (not diffusion) → different frequency artifacts
- **This is exactly why we're collecting this data** — FSD needs GPT-Image training samples

## Final Dataset

| Metric | Count |
|--------|-------|
| **Validated (images/)** | **497** |
| Rejected | 978 |
| Staging | 0 |
| Manifest entries | 1,475 |

### Source Breakdown (validated)
| Source | Count | % |
|--------|-------|---|
| Reddit | 384 | 77.3% |
| Higgsfield openai_hazel | 52 | 10.5% |
| Civitai | 49 | 9.9% |
| Higgsfield text2image_gpt | 12 | 2.4% |

### Disk Usage
- images/: 564 MB
- rejected/: 1.2 GB (user to confirm deletion)

## Lessons Learned

### Sources
1. **Civitai CDN purges are real** — 18K images in API, <1% downloadable for v1. CDN availability degrades rapidly with age. Scrape early or miss the window.
2. **Higgsfield has model-specific galleries** — clean, small, reliable. Always check even if volume is low.
3. **Reddit with date+flair gating works** — date gate (April 1, 2025) excluded DALL-E 3 era posts, flair gate ("Image - ChatGPT") isolated generator-specific content. Combined, these give reasonable provenance confidence.
4. **No X.com/Twitter source exists** for GPT-Image — unlike Grok, there's no official bot posting generations.

### Validation
5. **GPT-Image has extreme non-photorealistic usage** — 66% of downloads rejected (vs 18% for Nano Banana). Ghibli-style, anime, illustration dominate.
6. **JoyCaption can hallucinate on high-contrast graphics** — vector art with text was described as "photograph, black background, minimal light". Added "minimalistic art" keyword to catch these.
7. **Reject keywords must be narrow** — "logo", "icon", "silhouette" match elements within photorealistic images. Only use unambiguous style descriptors.

### Technical
8. **FSD 0% detection on GPT-Image** — autoregressive architecture produces fundamentally different artifacts than diffusion. Critical training data gap.
9. **Concurrent download workers help with CDN failures** — 4 workers process failures fast, maximizing the few successes. Fixed pbar to track total progress (dl/fail/skip).
10. **Reddit date filtering requires UTC timestamps** — `created_utc` field in Reddit API, configure as `REDDIT_MIN_CREATED_UTC`.

## Pending for User
- [ ] Confirm deletion of rejected/ directory (1.2 GB)
- [ ] Consider re-running Civitai scrape in future (CDN may restore)
- [ ] Dataset is 497 images — well below 5-10K target. Consider supplementing with PromptHero or NightCafe if more volume needed.
