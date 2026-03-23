# Curate Skill — Reference

Quick-reference for the `/curate` pipeline. SKILL.md links here — read sections
as needed, not all at once.

---

## Config Template

Each generator needs `configs/<generator>.py`. Copy from an existing config
(e.g. `configs/flux1.py`) and modify. Key fields:

```python
NAME = "<generator>"                    # data folder name
DISPLAY_NAME = "<Generator Name>"

# Structural validation
EXPECTED_FORMATS = ["JPEG", "PNG"]
MIN_PIXELS = 800_000
MAX_PIXELS = 5_000_000
KNOWN_ASPECT_RATIOS = [(1, 1), (16, 9), (9, 16), (4, 3), (3, 4)]
ASPECT_RATIO_TOLERANCE = 0.05
CAMERA_EXIF_TAGS = ["Make", "Model", "ExposureTime", "FNumber", "ISOSpeedRatings"]

# Content filtering (JoyCaption booru tags)
REJECT_KEYWORDS = [
    "illustration", "cartoon", "anime", "cgi", "comic", "screenshot",
    "3d_render", "pixel_art", "watercolor",
]
TEXT_PAIRED_KEYWORDS = ["table", "chart", "conversation", "infographic"]
TEXT_INDICATORS = ["text", "font", "typed", "data", "numbers", "screenshot"]
BLOCKED_CONTENT_TAGS = []   # genital keywords for NSFW policy

# Source-specific (add only what applies)
CIVITAI_MODEL_VERSIONS = []          # [(model_id, version_id), ...]
TWITTER_BOT_USERNAME = None          # e.g. "grok"
TWITTER_DIRECT_SEARCH_DAYS = 365
HIGGSFIELD_MODELS = []               # e.g. ["soul_v1", "soul_v2"]
INSTAGRAM_USERNAMES = []             # for AI influencer scraping
YODAYO_MODELS = {}                   # {label: version_uuid}
```

Look at existing configs for real examples — don't guess field names.

---

## Available Scrapers

| Scraper | Platform | Auth Required | Provenance | Command |
|---------|----------|---------------|------------|---------|
| `civitai` | Civitai on-site gen | None | Excellent | `uv run python -m scrapers.civitai -c CONFIG -n N` |
| `civitai_simple` | Civitai (simplified) | None | Excellent | `uv run python -m scrapers.civitai_simple -c CONFIG -n N` |
| `higgsfield` | Higgsfield gallery | None | Excellent | `uv run python -m scrapers.higgsfield -c CONFIG -n N` |
| `twitter` | X.com bot images | cookies-x.txt | Good | `uv run python -m scrapers.twitter -c CONFIG -n N` |
| `midjourney` | Discord channels | Discord token | Good | `uv run python -m scrapers.midjourney -c CONFIG -n N` |
| `instagram` | Instagram profiles | cookies-instagram.txt | Good (eval) | `uv run python -m scrapers.instagram -c CONFIG -n N` |
| `recraft` | Recraft community | None (Playwright) | Excellent | `uv run python -m scrapers.recraft -c CONFIG -n N` |
| `tensorart` | Tensor.Art gallery | None (Playwright) | Good | `uv run python -m scrapers.tensorart -c CONFIG -n N` |
| `yodayo` | Yodayo gallery | None (Playwright) | Good | `uv run python -m scrapers.yodayo -c CONFIG -n N` |
| `openart` | OpenArt gallery | None | Good | `uv run python -m scrapers.openart -c CONFIG -n N` |
| `aigcarena` | AIGCArena | cookies-aigcarena.txt | Good | `uv run python -m scrapers.aigcarena -c CONFIG -n N` |
| `reddit` | Reddit | None | Poor | `uv run python -m scrapers.reddit -c CONFIG -n N` |

All scrapers: `--force` for clean run, resume by default via manifest.

---

## Source Priority

When choosing sources for a new generator, follow this priority:

1. **Generator-specific gallery** (Higgsfield, Recraft, grok.com) — 100% provenance
2. **Civitai on-site generation** (`model_version_id`) — full-res, guaranteed AI
3. **Platform galleries** (Tensor.Art, Yodayo, OpenArt) — good provenance, may need LoRA filtering
4. **Discord** (Midjourney) — requires version detection, grid splitting
5. **Twitter/X direct search** (`from:bot filter:images`) — official bot only
6. **Instagram** (AI influencer accounts) — evaluation only, unknown generators
7. **Reddit** — supplemental only, cap at 20%. Extremely noisy.

**Never use**: Civitai `tool_id` (user uploads), third-party bot accounts, unverified sources.

---

## Validation Pipeline

### Commands

```bash
# JoyCaption — Ray Serve (large batches)
CUDA_VISIBLE_DEVICES=6,7 python -m validators.serve_joycaption serve --gpu 0.25 --replicas 8
uv run python -m validators.batch_classify --dir data/<gen>/staging --output data/<gen>/captions.json --concurrency 8

# JoyCaption — local mode (small batches, no Ray needed)
uv run python -m validators.batch_classify --dir data/<gen>/staging --output data/<gen>/captions.json --local --gpu 6

# Validation pipeline (after captioning)
uv run python -m validators.pipeline --config configs/<gen>.py --skip-fsd

# FSD scoring (after validation, on final images)
uv run fsd-score --dir data/<gen>/images/ --csv > data/<gen>/fsd_scores.csv

# Grid splitting (Midjourney only)
uv run python -m validators.split_grids -c configs/midjourney_v7.py
```

### Validation Stages

**Tier 0 — JoyCaption content filter**
- Booru tag mode (NOT descriptive captions — 25% false-reject with descriptions)
- Config-driven `REJECT_KEYWORDS` with word-boundary regex (`\b`)
- `TEXT_PAIRED_KEYWORDS` only reject when `TEXT_INDICATORS` also present
- "digital art" is too generic — do NOT include it in REJECT_KEYWORDS

**Tier 1 — Structural validation**
- Format: PIL verification (not file extension)
- Pixel count: `MIN_PIXELS` to `MAX_PIXELS`
- Aspect ratio: `KNOWN_ASPECT_RATIOS` with ±5% tolerance
- EXIF camera tags → real photo → reject

**Tier 2 — FSD z-score tagging**
- Tag only, NEVER filter — detection rates range from 21% (Seedream) to 98% (GPT-Image)
- Run on final validated set, not during sweeps

---

## Critical Rules

These come from real failures — violating any of them causes data loss or corruption:

1. **Verify JoyCaption is running before captioning.** Error captions silently pass through
   and cause mass rejection. Always audit `captions.json` for `"error"` entries.

2. **Never label versions as "unknown" if avoidable.** Use explicit flags + default version
   date ranges (Midjourney), source/flair fields (Higgsfield, Civitai), or API metadata.

3. **Civitai: `model_version_id` only.** Never `tool_id` — anyone can upload anything.

4. **Spot-check constantly.** After every scraping batch and validation stage, not just at
   the end. Check rejected AND accepted samples.

5. **Instagram CDN URLs expire.** Download immediately when found. Don't modify CDN URL
   parameters (e.g. `dst-webp` → `dst-jpg` breaks downloads).

6. **Twitter: be conservative with scrolling.** Aggressive search scrolling causes account
   soft-bans. Use daily date windowing instead of deep scrolling.

7. **Discord CDN URLs expire in ~24h.** Download during scraping, not after.

8. **Resume by default.** All scrapers and batch_classify skip already-processed items.
   Use `--force` only for intentional clean reruns.

---

## Workflow Checklist

- [ ] Worklog created: `docs/WORKLOG_<YYYYMMDD_HHMM>_<generator>.md`
- [ ] Generator config: `configs/<generator>.py`
- [ ] Sources identified and prioritized
- [ ] Small test batch scraped and spot-checked
- [ ] Full scrape (parallel sources where possible)
- [ ] JoyCaption confirmed running (`ps aux | grep serve_joycaption`)
- [ ] Batch captioning complete — **audit captions.json for errors**
- [ ] Validation pipeline run (`--skip-fsd`)
- [ ] Spot-check rejected AND accepted samples
- [ ] FSD z-score tagging on validated images
- [ ] Metadata CSV rebuilt (`make metadata`)
- [ ] Worklog finalized with stats
- [ ] Lessons distilled into `docs/LESSONS_<GENERATOR>.md`
- [ ] Synced to weka (`make sync`)

---

## Data Layout

```
data/<generator>/
├── images/          # Validated (ready for FSD pipeline)
├── staging/         # Downloaded, pre-validation
├── rejected/        # Failed validation (clean up after run)
├── manifest.csv     # Download tracking (resume support)
├── captions.json    # JoyCaption booru tags
├── metadata.csv     # Per-image metadata (synced to weka)
└── fsd_scores.csv   # FSD z-scores
```

## Metadata Fields

`metadata.csv` columns: `filename, source, model_version, width, height, format, file_size, url, timestamp`

Model version is mapped from manifest `source`/`flair` fields per generator.
See `scripts/build_all_metadata.py` for all mapping logic.
