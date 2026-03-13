# Worklog: Nano Banana Curation — 2026-03-13

## Summary
Curating Google's Nano Banana (v1, Pro, 2) AI-generated images. Target: 3-5K in-the-wild images.

## Timeline

### Phase 0: User Intake (19:30)
- Target: 3-5K images, as many as possible
- In-the-wild only (no API generation)
- X.com cookies: `data/cookies-x.txt`
- Additional source: Higgsfield.ai community galleries (cookies provided)
- User emphasis: respect rate limits, don't get banned

### Phase 1: Generator Profiling (19:33)
- Research team (3 agents) completed profiling:
  - **Civitai**: model_id=1903424, 3 versions found but 0 on-site generations — NOT viable for scraping
  - **@NanoBanana**: Official Google X.com account, ~150K followers, safe to scrape media timeline
  - **API docs**: 14 aspect ratios, 512/1K/2K/4K resolution tiers, PNG/JPEG/WebP
  - **Safety**: Hard blocks on nudity, violence, hate, deepfakes, minors
  - **Watermarks**: SynthID (invisible, always), C2PA metadata, no visible watermark via API
  - **FSD detection**: 90.9% for Gemini/Imagen (mean z = -6.75)
  - **Reddit**: r/Gemini, r/GoogleGemini, possibly r/nanobanana — all high noise
- Config created: `configs/nano_banana.py`

**Source plan:**
| Source | Priority | Expected yield | Notes |
|--------|----------|---------------|-------|
| @NanoBanana/media | 1 | ~600 (Twitter cap) | Official bot, every image is Nano Banana |
| Higgsfield.ai | 2 | TBD (scouting) | Community galleries, need to reverse API |
| Civitai user uploads | 3 | TBD | model_version filter, provenance varies |
| Reddit | 4 (supplemental) | Low (~10% yield) | Very noisy, needs heavy filtering |

### Phase 2: Scraping (16:07 — in progress)

**Clean restart at 16:07** — wiped all prior data, restarted all scrapers with `--force`.

**Twitter (@NanoBanana/media):**
- Media timeline found **832 URLs** (exceeds Grok's ~600 cap)
- Downloading at ~2-4 img/s, ~502 downloaded so far
- Search queries (`@NanoBanana generate/create/make/draw...`) finding threads but **0 bot replies** — @NanoBanana may not reply in-thread like @grok does
- 1024x559 resolution common in older tweets (early Nano Banana v1). Newer tweets are 2K-4K. All `name=orig`.

**Higgsfield.ai:**
- API: `GET fnf.higgsfield.ai/publications/community/approved?model=<name>&approved=true`
- nano_banana: 2 images, nano_banana_2: ~56 images. Gallery exhausted at ~69 total.
- Quality excellent — full-res PNGs, clearly AI art.

**Reddit:**
- Subreddits: r/GoogleGemini, r/nanobanana, r/AiGeminiPhotoPrompts
- ~209 images so far, heavily filtered. Stalled briefly between subreddits.
- Contamination confirmed: screenshots, Gemini UI quiz, memes mixed in.

**Spot-check (16:12):**
- Twitter: legit AI images, 1024x559 = early v1 originals (not crops)
- Higgsfield: excellent quality, best provenance
- Reddit: noisy — Gemini quiz screenshot, phone screenshots (1242x1656 = iPhone retina)
- 1242x1656 is iPhone screenshot resolution — NOT a Nano Banana output. Validation will catch.
- Aspect ratio filter key: 1.832 (1024x559) close to but not 16:9 (1.778) — needs investigation

**At ~16:12:** Total manifest: ~1,269 images (1002 twitter, 209 reddit, 58 higgsfield)

**Scraping final totals (manifest):**
| Source | Downloaded |
|--------|-----------|
| Reddit | 9,474 (from 200+ subs via search queries) |
| Twitter | 1,652 (832 media timeline + search) |
| Higgsfield nano_banana_2 | 67 (approved gallery) |
| Higgsfield nano_banana | 65 (approved gallery) |
| **Total** | **11,258** |

Reddit subs: r/nanobanana (2,776), r/AiGeminiPhotoPrompts (2,428), r/GeminiAI (434), r/Bard (319), r/GoogleGemini (317), + 200 smaller subs.

### Phase 3: Validation (17:07)

**Structural validation** (relaxed mode):
- 5,834 validated → 4,558 passed (78%), 1,276 rejected
- Rejection: too_small 665, bad_aspect_ratio 648, too_large 28

**FSD scoring**: 3,794 scored, 38.3% z<-2.0 (AI detected)
- Lower than expected 90.9% — likely due to Reddit JPEG recompression weakening signal

**VLM/Caption content filter**: 3,791 classified
- 847 images with hard reject signals removed (tables 248, logos 237, screenshots 126, promotional 121, ads 68, infographics 54, comics 52, collages 35, banners 32, anime 28)

**After all validation**: **3,711 images** in images/
| Source | Count | % |
|--------|-------|---|
| Reddit | 3,329 | 89.7% |
| Twitter | 272 | 7.3% |
| Higgsfield | 110 | 3.0% |

### Phase 4: Cleanup
- Higgsfield /community scrape running in background (~12K available)
- More Higgsfield images will improve non-Reddit ratio

## Lessons Learned
- @NanoBanana doesn't reply in-thread like @grok — search queries yield 0 bot replies. Media timeline is the only Twitter source.
- Higgsfield.ai `/community` endpoint has ~12K images vs `/community/approved` with only 69 — remove `approved=true` param for much larger yield
- Nano Banana v1 posted lower-res images (1024x559) — not a standard aspect ratio, needs investigation
- Reddit iPhone screenshot resolutions (1242x1656) leak through as PNGs — caught by aspect ratio filter
- Twitter media timeline found 832 URLs — more than Grok's ~600 cap
- Reddit search queries cast very wide net (200+ subs) — good for volume but contamination is high
- VLM caption-based filtering caught 847 contaminated images that passed structural validation — multi-stage is mandatory
- FSD detection only 38.3% at z<-2.0 for Nano Banana (vs 72% for Grok) — JPEG recompression a likely factor
- r/Gemini is a CRYPTO subreddit, not Google Gemini — skip it

## Pending / Follow-up
- Higgsfield /community scrape in progress (~12K images) — will improve source diversity
- Manual spot-check of Reddit images still needed (Grok experience: 48% rejected manually)
- Investigate 1024x559 Twitter images — standard Nano Banana v1 output or previews?
- Consider Civitai user uploads (model_version filter) for additional volume
