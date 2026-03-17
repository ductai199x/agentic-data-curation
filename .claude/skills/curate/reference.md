# Curate Skill — Reference

Detailed tool commands, generator profiles, code patterns, and checklists.
SKILL.md links here for specifics — read sections as needed, not all at once.

## Table of Contents
- [Config Template](#config-template)
- [Scraping](#scraping)
- [Validation Pipeline](#validation-pipeline)
- [Metadata Fields](#metadata-fields)
- [Generator Profiles](#generator-profiles)
- [Code Patterns](#code-patterns)
- [Workflow Checklist](#workflow-checklist)

---

## Config Template

Each generator needs `configs/<generator>.py`. Copy and fill in from API docs
and Phase 1 research:

```python
"""<Generator Name> — generator configuration."""

NAME = "<generator>"
DISPLAY_NAME = "<Generator Name>"

EXPECTED_FORMATS = ["JPEG", "PNG"]
MIN_PIXELS = 800_000     # reject thumbnails
MAX_PIXELS = 5_000_000   # reject real uploads
KNOWN_ASPECT_RATIOS = [  # from official docs
    (1, 1), (16, 9), (9, 16), (4, 3), (3, 4),
    # ... add actual ratios
]
ASPECT_RATIO_TOLERANCE = 0.05  # 5%
CAMERA_EXIF_TAGS = ["Make", "Model", "ExposureTime", "FNumber", "ISOSpeedRatings"]

# Civitai — on-site generation (most trustworthy)
# Each entry: (model_id, model_version_id)
CIVITAI_MODEL_VERSIONS = []
CIVITAI_TOOL_ID = None  # fallback only — user-uploaded, less trustworthy

# X.com — bot media timeline + direct image search
TWITTER_BOT_USERNAME = None     # e.g. "grok", "NanoBanana"
TWITTER_MEDIA_URL = None        # e.g. "https://x.com/grok/media"
TWITTER_COOKIES_PATH = "data/cookies-x.txt"
TWITTER_DIRECT_SEARCH_DAYS = 365  # auto-generates daily "from:bot filter:images until:YYYY-MM-DD"

# Higgsfield — community gallery API (if applicable)
HIGGSFIELD_MODELS = []       # e.g. ["nano_banana", "nano_banana_2"]

# Reddit
REDDIT_SUBREDDITS = []
REDDIT_SEARCH_QUERIES = []

# Reddit post-level filtering (pre-download noise reduction)
REDDIT_REJECT_FLAIRS = {
    "Discussion", "Meme", "News", "Comparison", "Question", "Help",
    "Meta", "Feedback", "Announcement", "Poll", "Video", "Rant",
    # Add subreddit-specific flairs after scouting
}
REDDIT_REJECT_TITLE_KEYWORDS = [
    " vs ", "comparison", "benchmark", "censored", "banned",
    "pov:", "when you", "me when", "goodbye", "bring back",
    # Add generator-specific keywords after scouting
]
REDDIT_ALLOWED_IMAGE_DOMAINS = {"i.redd.it", "preview.redd.it", "i.imgur.com"}
REDDIT_SKIP_SELF_POSTS = True

# Content classification keywords (used by classify.py)
# See configs/nano_banana_1_2.py for comprehensive example
REJECT_KEYWORDS = [
    "illustration", "cartoon", "anime", "cgi", "comic", "screenshot",
    "digital_art", "3d_render", "pixel_art", "watercolor",
    # Add generator-specific keywords
]
TEXT_PAIRED_KEYWORDS = [
    "table", "chart", "conversation", "notification", "infographic",
]
TEXT_INDICATORS = [
    "text", "font", "typed", "data", "numbers", "screenshot",
]
BLOCKED_CONTENT_TAGS = []  # safety filter (content generator can't produce)
```

---

## Scraping

### Tool Commands

```bash
# Civitai — prefers on-site generation (model versions), falls back to tool_id
uv run python -m scrapers.civitai --config configs/<gen>.py --max-images N

# Civitai — explicit model version (most trustworthy)
uv run python -m scrapers.civitai --config configs/<gen>.py --model-version <id> --max-images N

# Twitter/X — bot's media timeline (TWITTER_MEDIA_URL from config)
uv run python -m scrapers.twitter --config configs/<gen>.py --max-images N

# Reddit — subreddits + search queries + post-level filters from config
uv run python -m scrapers.reddit --config configs/<gen>.py --max-images N

# Higgsfield — community gallery API, paginates through all posts
uv run python -m scrapers.higgsfield --config configs/<gen>.py --max-images N

# grok.com/imagine — 100% Grok provenance, requires SSO cookies
uv run python -m scrapers.grok_imagine -c configs/grok.py --cookies data/cookies-grok.txt -n 3000

# All scrapers: --output DIR (default: data/<generator>), resume via manifest
```

### Source Priority & Gotchas

**1. Generator-specific galleries** (grok.com/imagine, Higgsfield)
- Best provenance — 100% guaranteed generator output
- Higgsfield: REST API, paginated via cursor, ~3s/image. Source field encodes model version
- grok.com/imagine: `POST /rest/media/post/list`, requires SSO cookies, CDN: images-public.x.ai

**2. Civitai on-site generation** (`model_version_id`)
- Full-res PNGs, no multi-tool contamination
- Civitai `tool_id` (user-uploaded) is unreliable — multi-tool ComfyUI workflows contaminate results
- Check CDN filenames for `ComfyUI_*` if using tool_id
- Rate limit: 5-12s between API calls, 1-3s between downloads

**3. X.com/Twitter** (media timeline + direct image search)
- Only scrape the generator's OFFICIAL bot account (e.g. @grok, @NanoBanana)
- Two methods: `/media` timeline (gallery-dl) + direct search (`from:bot filter:images`)
- Direct search: auto-generates daily `until:YYYY-MM-DD` windows going back N days
  - Every result is a bot image — 100% provenance, no thread checking needed
  - Config: `TWITTER_BOT_USERNAME` + `TWITTER_DIRECT_SEARCH_DAYS = 365`
- Never use third-party bot accounts — unverified provenance
- Requires `cookies.txt` (Netscape format, expires ~2 weeks)
- Be conservative with search scrolling — aggressive scrolling causes account soft-bans

**4. Reddit** (supplemental only)
- Public JSON API, no auth needed
- ~10% actual AI art in generator subs; rest is screenshots/memes/discussions
- Pre-download filtering (flair + title + domain + self-post) catches ~57% of noise
- Even after filtering, 48% of remaining images were junk in Grok run — manual spot-check critical
- JPEGs get recompressed — only PNGs preserve forensic signal
- Cap Reddit at 20-25% of final dataset

### Data Layout

```
data/<generator>/
├── images/          # Validated (ready for FSD pipeline)
├── staging/         # Downloaded, pre-validation
├── rejected/        # Failed validation (clean up after run)
├── manifest.csv     # Download tracking (resume support)
├── captions.json    # JoyCaption booru tags
├── metadata.csv     # Per-image metadata after validation
├── fsd_scores.csv   # FSD z-scores
└── validation_report.json
```

---

## Validation Pipeline

### Tool Commands

```bash
# JoyCaption — start Ray Serve (6 replicas, GPUs 0-3)
source .venv/bin/activate
CUDA_VISIBLE_DEVICES=0,1,2,3 python -m validators.serve_joycaption serve \
  --gpu 0.5 --replicas 6

# Batch caption staging images (async, resume-aware)
uv run python -m validators.batch_classify \
  --dir data/<gen>/staging --output data/<gen>/captions.json --concurrency 6

# Run validation pipeline (JoyCaption content filter + structural)
uv run python -m validators.pipeline --config configs/<gen>.py --skip-fsd

# Full pipeline including FSD
uv run python -m validators.pipeline --config configs/<gen>.py

# Force revalidation (moves images/ and rejected/ back to staging/)
uv run python -m validators.pipeline --config configs/<gen>.py --force

# FSD scoring (run separately on final validated images)
uv run fsd-score --dir data/<gen>/images/ --csv > data/<gen>/fsd_scores.csv

# vLLM (alternative to JoyCaption, port 8001)
CUDA_VISIBLE_DEVICES=3 uv run vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --port 8001 --max-model-len 8192 --trust-remote-code --gpu-memory-utilization 0.5
```

### Pipeline Architecture

```
batch_classify.py    → Async HTTP client → JoyCaption Ray Serve → captions.json
pipeline.py          → Loads captions.json → classify_caption() → structural → FSD → sort
classify.py          → Config-driven keyword matching (REJECT_KEYWORDS, TEXT_PAIRED_KEYWORDS)
image_validator.py   → Structural: pixels, aspect ratio, EXIF, format
```

### Stage Details

**Tier 0: JoyCaption content filter**
- Booru tag mode: `"Write a list of Booru-like tags for this image."`
- NOT descriptive captions (25% false-reject rate from background descriptions like "city skyline")
- `classify_caption()` uses config REJECT_KEYWORDS with `re.search(r'\b' + keyword + r'\b', text)`
- TEXT_PAIRED_KEYWORDS only reject when TEXT_INDICATORS also present in the same caption
- Catches ~15-18% of images (illustration, cartoon, anime, screenshot, etc.)

**Tier 1: Structural validation**
- Format: `PIL.Image.open()` verification (not file extension)
- Pixel count: MIN_PIXELS to MAX_PIXELS from config
- Aspect ratio: against KNOWN_ASPECT_RATIOS with ±5% tolerance
- EXIF: camera tags (Make, Model, ExposureTime) = real photo = reject

**Tier 2: FSD z-score**
- Tag only — detection rates vary wildly across generators
- z > -0.15 = almost certainly real photo (safe to hard-filter at this threshold)
- Run on final validated set, not during sweep cycles (slow, GPU-intensive)

**Additional manual stages** (do throughout, not just at the end):
- Aspect ratio outlier scan — non-standard ratios catch screenshots, crops, wrong generators
- Tag-based provenance signals — watermarks, safety filter violations
- Visual spot-check — sort by FSD z-score descending, inspect most suspicious first

---

## Metadata Fields

Final `metadata.csv` should include:

```
filename, source, model_version, width, height, format, file_size,
url, subreddit, timestamp
```

Optional extended fields (when available from source):
```
content_hash, post_id, post_title, flair, exif_artist, exif_description,
exif_software, has_generator_signature, fsd_zscore, fsd_raw, fsd_is_fake,
quality_rating
```

The `model_version` field is a passthrough from the manifest `source` column — no
pipeline logic needed. Map source strings to version names (e.g. `higgsfield_nano_banana_2`
→ `nano_banana_2`, Reddit/Twitter → `unknown`).

---

## Generator Profiles

### Grok — `configs/grok.py`
- **Best sources**: grok.com/imagine API (100% provenance), Civitai on-site gen (model_version_id=2738377)
- **X.com**: @grok/media timeline (~616 items, server-side cap)
- **Civitai tool_id**: 284 — DO NOT USE (user-uploaded, multi-tool contamination)
- **Aspects**: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 11:6, 6:11, 19.5:9, 9:19.5, 20:9, 9:20
- **Pixel count**: ~915K (1K tier), ~4M (2K tier)
- **Format**: JPEG (avg_q 1.0-5.8) or PNG
- **EXIF**: Artist=UUID, ImageDescription="Signature: <base64>" (C2PA)
- **Safety**: Blocks exposed genitalia (provenance signal)
- **FSD**: 72% detection at z < -2.0
- **Reddit**: r/grok, r/GrokAI, r/GrokImagine — 11.3% yield (1,500→169 validated)
- **Final dataset (v3)**: 1,713 images — Twitter 40.7%, grok.com 35.0%, Civitai 10.7%, Reddit 9.9%

### Nano Banana (Google Gemini Image) — `configs/nano_banana_1_2.py`
- **Best source**: Higgsfield.ai community gallery (REST API, ~12,375 total posts exhausted)
  - API: paginated cursor, ~3s/image, CDN strips all metadata
  - Source field encodes model version: `nano_banana` (v1) vs `nano_banana_2` (v2)
  - 82% pass rate through automated validation — very clean source
- **X.com**: @NanoBanana/media (official Google bot, ~200 images)
- **Civitai**: model_id=1903424, 3 versions found but 0 on-site generations — NOT viable
- **Aspects**: 14 ratios including v2-only 1:4, 4:1, 1:8, 8:1
- **Safety**: Hard blocks on nudity, violence, hate, deepfakes, minors
- **Watermarks**: SynthID (invisible, always present), C2PA metadata (stripped by CDNs)
- **FSD**: 32.8% detection at z < -2.0 (mean z = -2.32) — much lower than other generators
- **Reddit**: r/Gemini, r/GoogleGemini — very noisy, supplemental only
- **Final dataset**: 11,833 images — Higgsfield v2 66.2%, Reddit 22.7%, Higgsfield v1 9.3%, Twitter 1.7%

### ChatGPT (GPT-Image-1/1.5) / DALL-E 3 — partially profiled
- **FSD**: 100% detection (11/11), mean z = -15.56 — very strong signal
- **Watermark**: Rainbow square in corner (DALL-E), C2PA metadata
- **Civitai**: OpenAI GPT-image-1 — check for on-site generation model_version_ids
- **Reddit**: r/ChatGPT, r/dalle, r/OpenAI

### Known Civitai On-Site Generators
Alibaba (Qwen), Black Forest Labs (Flux.1/2), ByteDance (Seedream), Google (Imagen 4,
Nano Banana), OpenAI, Pony Diffusion, SDXL Community (Illustrious, NoobAI),
Stability AI (SD 1.x, SDXL), xAI (Grok), Chroma, HiDream

---

## Code Patterns

### Aspect ratio checker
```python
def matches_known_ratio(w, h, known_ratios, tolerance=0.05):
    img_ratio = w / h
    for rw, rh in known_ratios:
        expected = rw / rh
        if abs(img_ratio - expected) / expected <= tolerance:
            return f"{rw}:{rh}"
    return None
```

### Safety filter (tag-based provenance signal)
```python
GENITAL_KEYWORDS = ['penis', 'vagina', 'vulva', 'genitals', 'testicle', 'labia', 'clitoris']

def flag_safety_violations(booru_tags, existing_files):
    """Flag images with content the generator can't produce."""
    flagged = []
    for fname in existing_files:
        tags = booru_tags.get(fname, '')
        tag_str = ', '.join(tags) if isinstance(tags, list) else str(tags)
        matches = [kw for kw in GENITAL_KEYWORDS if kw in tag_str.lower()]
        if matches:
            flagged.append((fname, matches))
    return flagged
```

### Model version passthrough (metadata rebuild)
```python
def get_model_version(source):
    if not source:
        return 'unknown'
    s = source.lower()
    # Generator-specific mapping — extend per generator
    if 'nano_banana_2' in s: return 'nano_banana_2'
    elif 'nano_banana' in s: return 'nano_banana'
    else: return 'unknown'
```

---

## Workflow Checklist

Copy and track through the run:

- [ ] Worklog created: `docs/WORKLOG_<datetime>_<generator>.md`
- [ ] Generator config: `configs/<generator>.py`
- [ ] Sources identified and prioritized
- [ ] Reddit flairs scouted, REDDIT_REJECT_FLAIRS populated
- [ ] Reddit title keywords populated
- [ ] JoyCaption Ray Serve running (check `ps aux` first)
- [ ] Small test batch (50 images) scraped and validated
- [ ] Full scrape to target count (parallel sources)
- [ ] Sweep cycles running during scrape (caption + pipeline every 15-20 min)
- [ ] Spot-check after each sweep (rejected AND accepted samples)
- [ ] Final sweep after scraper exits
- [ ] FSD z-score tagging on validated images
- [ ] Manifest deduplicated
- [ ] Metadata CSV rebuilt
- [ ] staging/ and rejected/ cleaned up
- [ ] Worklog finalized with stats and lessons
- [ ] Lessons distilled into `docs/LESSONS_<GENERATOR>.md`

---

## GPU Allocation

| GPU | Usage |
|-----|-------|
| 0-3 | JoyCaption Ray Serve (6 replicas, ~34GB each) |
| 3   | vLLM Qwen2.5-VL-7B (port 8001, 50% util) — shares with JoyCaption |
| 4-7 | Reserved (other users) |
