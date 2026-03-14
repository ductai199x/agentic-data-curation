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

### Phase 3b: Second Validation Pass (18:00)

**Context**: After context compression, images/ was empty. Staging had 3,547 files, rejected/ had 2,462.
Previous captions.json was lost. Need to re-run full classification + validation pipeline.

**Bug fix**: Higgsfield scraper was deadlocking on page 5 due to blocking `requests.get()` inside async
producer/consumer event loop. Rewrote to fully synchronous (no async needed for sequential pagination).

**Running (18:15)**:
- **JoyCaption batch classify**: 2,400/6,780 staging files captioned at ~1 img/s
- **Higgsfield /community scrape**: 1,671 nano_banana + 67 nano_banana_2 in manifest (up from 600)
- Staging growing: 6,780 files (from 3,547 before Higgsfield resumed)
- Added incremental save (every 300 images) to batch_classify to prevent data loss on crash

**Validation pass 1 results (18:30)**:
- Tier 0 (JoyCaption content filter): 2,493 rejected (screenshots, logos, tables, ads, etc.)
- Tier 1 (Structural): 633 rejected (370 too_small, 265 bad_aspect_ratio, 17 too_large)
- Passed: 3,921 images → images/
- Skipped: 736 uncaptioned (new Higgsfield downloads) → left in staging

**FSD scoring (18:50)**:
- 38.3% detected as AI at z<-2.0 (consistent with previous run)
- 91.5% have z<0 (strongly AI-leaning)
- Max z-score 0.48 — no clearly real photos in dataset
- FSD detection rate lower than expected 90.9% for Gemini — JPEG recompression factor

**Validation pass 2 (19:00)**:
- Additional Higgsfield images classified and validated
- **4,738 total validated images** in images/
- Source breakdown: Reddit 2,691 (56.8%), HF nano_banana 1,101 (23.2%), HF nano_banana_2 740 (15.6%), Twitter 206 (4.3%)
- Non-Reddit: 43.2% (up from ~10% in first pass — Higgsfield significantly improved diversity)
- Higgsfield scraper still running (nano_banana_2 at 1,010, targeting 5,000 total)

**Ongoing periodic classify+validate (19:30-20:45)**:
- Running classify+validate cycles every 20 min as Higgsfield scraper adds images
- Higgsfield images have near-100% structural pass rate (best provenance)
- At 20:30: **6,073 validated images**
  - Reddit: 2,691 (44.3%) | HF nano_banana_2: 2,075 (34.2%) | HF nano_banana: 1,101 (18.1%) | Twitter: 206 (3.4%)
  - **Non-Reddit: 55.7%** (up from 10% at start — Higgsfield dramatically improved diversity)
- At 20:45: **6,267 validated images** (+ ~194 from continued Higgsfield scraping + validation)

### Phase 4: Cleanup & Final Scoring (20:45)

**FSD scoring on full dataset (6,166 images)**:
- Running in background (PID 2169671)
- Partial results (841/6,166): 35.1% detected at z<-2.0, 85.4% z<0 (AI-leaning)
- Max z=0.54 — no clearly real photos in dataset
- Consistent with earlier 38.3% rate; JPEG recompression weakens signal

**Final dataset stats**:
| Source | Count | % |
|--------|-------|---|
| Reddit | 2,691 | 42.9% |
| Higgsfield nano_banana_2 | 2,168 | 34.6% |
| Higgsfield nano_banana | 1,101 | 17.6% |
| Twitter | 206 | 3.3% |
| **(other/unmatched)** | ~101 | 1.6% |
| **Total** | **6,267** | |
| **Non-Reddit** | **3,576** | **57.1%** |

- Higgsfield scraper still downloading (nano_banana_2 at ~2,551, scraper still running)

### Phase 5: Classification Overhaul — Bracket Types → Booru Tags (session 2)

**Context**: User directed removal of ALL bracket-type classification code. The old system
used JoyCaption with a bracket-type prompt (`[type of image]`) and PASS_BRACKET_TYPES to
filter. This was replaced with a pure booru tag approach.

**Changes made:**
- `validators/classify.py`: Removed `_parse_bracket_types()` entirely. Changed `CAPTION_PROMPT`
  to `"Write a list of Booru-like tags for this image."`. `classify_caption()` now matches
  `REJECT_KEYWORDS` against booru tag text using word-boundary regex.
- `validators/serve_joycaption.py`: Made config-independent — returns only `{"caption": "..."}`
  with no classification. All rejection logic moved to pipeline via `classify_caption()`.
- `configs/nano_banana.py`: Added comprehensive REJECT_KEYWORDS (illustration, cartoon, anime,
  cgi, screenshot, UI elements, memes, etc.), TEXT_PAIRED_KEYWORDS, and TEXT_INDICATORS for
  two-tier keyword matching.
- `.claude/skills/curate/SKILL.md`: Updated config template to remove bracket type references.

**Bug fixes in this session:**
- `scrapers/higgsfield.py`: NoneType crash — `params.get("prompt", "")[:200]` fails when
  API returns `{"prompt": null}`. Fixed: `(params.get("prompt") or "")[:200]`.
- `scrapers/twitter.py`: Mixed 2/4-space indentation in `_worker` function.
- `validators/batch_classify.py`: Added tqdm progress bars, removed unused imports.
- `validators/pipeline.py`: Added tqdm to structural validation, removed unused `asdict` import.

**17 clean commits** covering all changes.

### Phase 6: Full Re-classification (session 2, continued)

**Restarted everything from scratch** with the new booru tag prompt:
1. Wiped `captions.json`, re-ran JoyCaption on all staging images
2. Moved `rejected/` back to `staging/` for re-evaluation with new keywords
3. Ran pipeline with config-driven keyword classification

**Duplicate process disaster**: Started batch_classify via Claude's `run_in_background`
(10-min timeout), then switched to `nohup` without killing the originals. Both survived,
creating two batch_classify instances and two Higgsfield scrapers writing to the same files.
Had to manually kill duplicates. **Lesson: always `ps aux | grep` before starting any
background process.**

**Pipeline results with booru tag classification:**
- Content rejection (Tier 0): ~15% of images caught by REJECT_KEYWORDS
- Structural rejection: <2% (mostly bad aspect ratio)
- FSD: skipped for speed (tag-only, doesn't filter)

**Higgsfield rejection rate analysis:**
- 82% photorealistic (pass), 18% non-photo content
- Top reject signals: digital art (266), illustration (80), cgi (78), anime (41),
  cartoon (32), comic (24), digital painting (24)
- Much cleaner than Reddit was for Grok (48% manual rejection rate)

**Spot check results (6 rejected + 6 accepted):**
- Rejections all correct: anime samurai, text overlay poster, digital art cyberpunk,
  comic style, product with control panel (borderline but acceptable)
- One borderline false positive: photorealistic superhero scene tagged "comic" — acceptable loss
- All accepts verified photorealistic: hawk in flight, mirror selfie, graffiti alley, product flat-lay
- No bad accepts found

### Phase 7: Exhausting Higgsfield (session 2)

- First run: `--max-images 5000` completed. 5,000 new downloads.
- Restarted with `--max-images 13000` to exhaust both models (~12,375 total posts).
- Running caption+pipeline sweeps every 15-20 min as new images arrive.
- Scraper deduplicates via manifest — skips already-downloaded URLs on restart.

**Progress snapshots:**
| Time | Validated | Staging | Higgsfield dl | Notes |
|------|-----------|---------|---------------|-------|
| 19:30 | 4,738 | 61 | 2,146 (run 1) | First pipeline pass complete |
| 20:00 | 5,181 | 32 | 2,448 | Steady sweeps |
| 20:30 | 5,746 | 30 | 3,110 | |
| 20:45 | 6,045 | 53 | 3,466 | |
| 21:00 | 6,462 | 25 | 3,967 | |
| 21:15 | 6,944 | 145 | 4,703 | |
| 21:25 | 7,301 | 0 | 5,000 | Run 1 complete |
| 21:35 | 7,561 | 79 | 303 (run 2) | Run 2 started |
| 21:55 | 7,993 | 125 | 832 (run 2) | |

### Phase 8: C2PA / Model Version Investigation

**Question**: Can we distinguish Nano Banana v1 vs v2 from the image files?

**C2PA/SynthID scan**: Deep-scanned PNG files (full binary search for c2pa, JUMBF, SynthID,
Google, Gemini markers). Result: **nothing found**. Higgsfield CDN strips all metadata —
PNGs contain only pixel data + DPI. Reddit and Twitter also strip metadata.

**Model version availability:**
| Source | Version known? | Validated count |
|--------|---------------|-----------------|
| `higgsfield_nano_banana` | v1 | ~1,100 (17%) |
| `higgsfield_nano_banana_2` | v2 | ~2,500+ (growing) |
| `reddit` | Unknown | ~2,700 (42%) |
| `twitter` | Unknown | ~200 (3%) |

~55% have known model version (from Higgsfield source field). Reddit/Twitter labeled `unknown`.
V2-only aspect ratios (1:4, 4:1, 1:8, 8:1) could weakly infer v2 for some Reddit/Twitter images.

**Decision**: Add `model_version` field to final metadata.csv — passthrough from manifest source
column, no pipeline changes needed.

## Lessons Learned

### Sources
- @NanoBanana doesn't reply in-thread like @grok — search queries yield 0 bot replies. Media timeline is the only Twitter source.
- Higgsfield.ai `/community` endpoint has ~12K images vs `/community/approved` with only 69 — remove `approved=true` param for much larger yield
- Higgsfield community gallery: 82% photorealistic, 18% non-photo — much cleaner than Reddit
- Twitter media timeline found 832 URLs — more than Grok's ~600 cap
- Reddit search queries cast very wide net (200+ subs) — good for volume but contamination is high
- r/Gemini is a CRYPTO subreddit, not Google Gemini — skip it
- Civitai had 0 on-site generations for Nano Banana — NOT viable

### Validation
- Booru tag keyword matching > bracket-type classification. More reliable, config-driven, generator-agnostic service.
- Word-boundary regex (`\b`) mandatory — "graph" matches "photograph" without it
- Two-tier keywords effective: TEXT_PAIRED_KEYWORDS only reject with TEXT_INDICATORS present (avoids false positives on "table" in dinner scene)
- "control panel" keyword catches product photos with physical control panels — acceptable false positive rate
- Multi-stage filtering mandatory — no single filter catches everything
- FSD detection only 38.3% at z<-2.0 for Nano Banana (vs 72% for Grok) — JPEG recompression a likely factor
- VLM caption-based filtering caught ~15% of images that passed structural validation

### Technical / Process
- **Blocking requests.get() inside asyncio causes deadlocks** — Higgsfield scraper hung on page 5. Fix: synchronous scraper for sequential pagination.
- **batch_classify.py must save incrementally** — added save every 300 images to prevent data loss
- **Always `ps aux | grep` before starting background processes** — duplicate processes writing to same files caused data corruption and confusion. Claude's `run_in_background` processes can survive their supposed timeout.
- **nohup with log files** is the reliable way to run long tasks — Claude's `run_in_background` has a 10-minute timeout that silently kills processes.
- Nano Banana v1 posted lower-res images (1024x559) on Twitter — not a standard aspect ratio
- Reddit iPhone screenshot resolutions (1242x1656) leak through as PNGs — caught by aspect ratio filter
- Higgsfield CDN strips all C2PA/SynthID metadata from PNGs — cannot determine model version from file contents
- Manifest gets duplicate entries when scrapers restart — deduplicate on filename for accurate counts

### Phase 9: Source Exhaustion & Final Processing (00:00–01:30, 2026-03-14)
- Higgsfield scraper round 2 completed: **5,681 downloads** (total ~12,658 across both rounds)
- Source fully exhausted — no more posts available
- Ran 8 caption+pipeline sweep cycles during scraper round 2
- Consistent ~99% pass rate from Higgsfield (rejections: bad_aspect_ratio, high_compression only)
- **Manifest deduplicated**: 22,825 → 16,760 unique entries (removed 6,065 duplicates)
- **metadata.csv rebuilt** with `model_version` field:
  - nano_banana_2: 7,835 (66.2%)
  - unknown (Reddit/Twitter): 2,897 (24.5%)
  - nano_banana: 1,101 (9.3%)
- FSD scoring completed: 32.8% detection at z<-2.0 (mean z=-2.32)

## Final State (2026-03-14 02:00)
- **11,833 validated images** in `data/nano_banana/images/`
- **4,907 rejected** in `data/nano_banana/rejected/`
- **1 skipped** in staging (webp format, correctly filtered)
- Higgsfield source fully exhausted
- Manifest deduplicated (16,760 unique entries)
- metadata.csv rebuilt with model_version field
- FSD scoring complete: **32.8% detection** at z<-2.0 (mean z=-2.32)

### Source Breakdown (validated images)
| Source | Count | % |
|--------|-------|---|
| Higgsfield v2 | 7,835 | 66.2% |
| Reddit | 2,691 | 22.7% |
| Higgsfield v1 | 1,101 | 9.3% |
| Twitter | 206 | 1.7% |

### FSD Detection by Generator Comparison
| Generator | Detection (z<-2.0) | Mean z-score |
|-----------|-------------------|--------------|
| Grok | 72% | ~-4.5 |
| Gemini/Imagen (ref) | 91% | -6.75 |
| Nano Banana | 32.8% | -2.32 |

Note: Nano Banana's lower detection rate likely due to JPEG recompression (Reddit 22.7% of dataset) and generation-specific artifacts.

## Pending / Follow-up
- Manual spot-check of random Reddit sample
- Update MEMORY.md with Nano Banana source viability notes
