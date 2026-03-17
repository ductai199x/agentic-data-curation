# Worklog: ChatGPT (GPT-Image-1 / GPT-Image-1.5) Curation

**Started**: 2026-03-14 03:35 UTC
**Completed**: 2026-03-14 ~19:00 UTC
**Generator**: GPT-Image-1, GPT-Image-1.5 (OpenAI, integrated into ChatGPT)
**Target**: 5-10K validated photorealistic images
**Result**: **2,725 validated images** (below target — Civitai CDN purge was the primary blocker)

## Phase 0: Intake

- User knows Higgsfield has GPT-Image-1.5 (https://higgsfield.ai/gpt-1.5)
- No official bot account on X.com
- Reddit needs strict filtering (date gate + flair gate)
- **User corrections**: DALL-E 2/3 ≠ GPT-Image-1/1.5. Civitai tool_id unreliable. Reddit provenance must be certain.

## Phase 1: Source Research

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
- v1 (oldest, April 2025+): ~3% success rate
- v1.5 (newest, Dec 2025+): ~14% success rate
- This was the biggest surprise — expected ~18K downloadable, got much less

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

### Round 1 (initial scrape)

#### Higgsfield (84 images)
- `openai_hazel`: 62 PNGs (GPT-Image-1.5)
- `text2image_gpt`: 22 JPEGs (GPT-Image-1)
- 0 failures — tiny but clean

#### Civitai Round 1 (115 images)
- v1.5 (mvid 2512167): 76 downloads from 688 processed (11%)
- v1 (mvid 1733399): 23 downloads from 1,419 processed (1.6%)
- Killed after ~10 min each — nearly 100% failure on deeper pages

#### Reddit Round 1 (1,276 images)
- **Strict filtering**: date gate (April 1, 2025+), flair gate (only "Image - ChatGPT" and "GPT-4o")
- r/AIArt: Primary source (~1,200 from "Image - ChatGPT" flair)
- r/dalle2: Supplemental (~76 from "GPT-4o" flair)

### Round 2 (retry — exhausting sources)

#### Civitai Round 2 (~6,200 more images)
- Retried with 4 concurrent download workers and reduced delays
- Pagination through all ~18K items across both model versions
- Most CDN URLs still 500, but picked up stragglers the first run missed
- Added skip-delay optimization (no sleep for already-downloaded items)
- Fixed producer/consumer deadlock issue (workers sleeping on skips)

#### Reddit Round 2
- Additional search queries: `"gpt-image-1"`, `"chatgpt image generation"`, `"gpt-4o image"`
- Hit 429 rate limits on some queries — backed off
- Picked up additional posts from r/OpenAI, r/AIArt, r/dalle2

### Total Downloads: ~7,693 unique
| Source | Downloads | % |
|--------|-----------|---|
| Civitai | 6,333 | 82% |
| Reddit | 1,276 | 17% |
| Higgsfield openai_hazel | 62 | 0.8% |
| Higgsfield text2image_gpt | 22 | 0.3% |

Note: Civitai downloads are high because the scraper paginated through all items, but
most failed at CDN (500 errors). Successfully downloaded images are a fraction.

## Phase 3: Validation Results

### Content Classification (JoyCaption booru tags)
- **~65% rejection rate** (much higher than Nano Banana's 18%)
- GPT-Image is extremely popular for non-photorealistic content
- Top rejection signals: digital art (50%+), illustration, anime, cartoon, cgi, sketch

### Keyword Refinement — Multiple Iterations
1. **Added**: "clipart", "clip art", "graphic design", "minimalistic art"
2. **Tested and REVERTED**: "logo", "icon", "silhouette", "sticker", "badge", "emblem", "decal"
   - These match elements WITHIN photorealistic images (Nike logo, boat silhouettes)
   - 34 false positives caught and reverted
3. **Added**: "speech bubble", "speech bubbles", "thought bubble", "word balloon", "dialogue bubble"
   - Caught 14 meme images with speech bubbles that slipped through content filter
   - Found via spot check — meme image had "speech bubbles" tag but no "meme" tag

### Pipeline Bug Fix: Error-Captioned Images
- **34 images with captioning errors** (FileNotFoundError) slipped through pipeline
- Root cause: pipeline checked `should_reject` and `caption` fields, but error entries
  had `{"error": "..."}` with neither field → treated as "not rejected"
- Fix: added `or "error" in v` to rejection filter in pipeline.py
- Re-captioned all 34 — all succeeded on retry (original errors were race conditions)
- 32 passed validation, 2 rejected by content filter

### Structural Validation
- ~5-8% rejection rate on non-standard aspect ratios
- GPT-Image's 3 aspect ratios make this a very tight filter

### Spot Checks
- **Round 1**: Accepts 13/14 correct, Rejects 7/8 correct
- **Round 2 (final)**: 5 random validated images — 4/5 correct, 1 meme with speech bubbles
  caught → led to adding speech bubble keywords and removing 14 more meme images

### FSD Detection
- **96.0% detection rate** (2,615/2,725 detected as AI-generated)
- z_score column uses `is_fake=True` with negative z-scores
- Much higher than Grok (72%) or Nano Banana (33%)
- GPT-Image artifacts are distinctive to FSD

## Final Dataset

| Metric | Count |
|--------|-------|
| **Validated (images/)** | **2,725** |
| Rejected | ~4,968 (cleaned up) |
| Staging | 0 |
| Manifest entries | 7,693 unique |

### Source Breakdown (validated)
| Source | Count | % |
|--------|-------|---|
| Civitai | 2,280 | 83.7% |
| Reddit | 381 | 14.0% |
| Higgsfield openai_hazel | 52 | 1.9% |
| Higgsfield text2image_gpt | 12 | 0.4% |

### Model Version Breakdown
| Version | Count | % |
|---------|-------|---|
| GPT-Image-1.5 | 1,878 | 68.9% |
| GPT-Image-1 | 466 | 17.1% |
| Unknown (Reddit) | 381 | 14.0% |

### Output Files
- `images/` — 2,725 validated images
- `metadata.csv` — per-image metadata with model_version field
- `fsd_scores.csv` — FSD z-scores for all validated images
- `captions.json` — JoyCaption booru tags
- `manifest.csv` — download log (7,693 unique entries)

## Lessons Learned

### Sources
1. **Civitai CDN purges are real and catastrophic** — 18K images in API, <15% downloadable for v1.5, <3% for v1. CDN availability degrades rapidly with age. Scrape early or miss the window entirely.
2. **Retry scraping pays off** — Round 2 with concurrent workers yielded significantly more Civitai downloads. The CDN returns 500 intermittently for some images, and retries can recover them.
3. **Higgsfield has model-specific galleries** — clean, small, reliable. Always check even if volume is low.
4. **Reddit with date+flair gating works** — date gate (April 1, 2025) excluded DALL-E 3 era posts, flair gate ("Image - ChatGPT") isolated generator-specific content. Combined, these give reasonable provenance confidence.
5. **No X.com/Twitter source exists** for GPT-Image — unlike Grok, there's no official bot posting generations.

### Validation
6. **GPT-Image has extreme non-photorealistic usage** — 65% of downloads rejected (vs 18% for Nano Banana). Ghibli-style, anime, illustration dominate. This generator is uniquely popular for stylized content.
7. **Speech bubbles/memes slip through content filter** — JoyCaption tags "speech bubbles" but not "meme". Added speech bubble variants to REJECT_KEYWORDS.
8. **Reject keywords must be narrow** — "logo", "icon", "silhouette" match elements within photorealistic images. Only use unambiguous style descriptors.
9. **Error-captioned images are a pipeline hole** — FileNotFoundError during captioning produces entries with no `caption` or `should_reject` fields. Pipeline must explicitly reject these.

### Technical
10. **FSD 96% detection on GPT-Image** — much higher than expected. Previous 0% was on a tiny sample. Large sample shows GPT-Image artifacts are well-detected.
11. **Concurrent download workers help with CDN failures** — 4 workers process failures fast, maximizing the few successes. Skip delay on already-downloaded items prevents unnecessary sleeping.
12. **Producer/consumer deadlock with many skips** — when most items are skips, consumers sleep on download delay even for skipped items. Fix: only delay on actual downloads.
13. **Reddit date filtering requires UTC timestamps** — `created_utc` field in Reddit API, configure as `REDDIT_MIN_CREATED_UTC`.
