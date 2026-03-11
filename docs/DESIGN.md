# Agentic Data Curation — Design Document

> Written: 2026-03-11
> Context: This project was born from a conversation during FSD detector development.
> The problem: manual data curation scripts are slow to write, buggy, and produce
> dirty data (thumbnails, real uploaded images mixed with AI-generated ones, etc.)

---

## Problem Statement

The FSD (Forensic Self-Description) detector at `~/1-workdir/07-fsd/` needs training
data from various AI image generators. Currently, engineers write custom scraping
scripts per source. These scripts:

1. **Take a long time to write** — each source has different page structure, APIs, auth
2. **Produce dirty data** — the Grok scraper downloaded thumbnails (464x688 instead of
   native 784x1168) and real user-uploaded photos (a 3072x4608 DSLR photo of a man
   in a jacket that scored z=-0.30, clearly real)
3. **Have no validation** — no automated checks for resolution, EXIF metadata,
   compression quality, or whether images are actually AI-generated
4. **Are fragile** — no rate limiting, no resume, no error handling

### The Grok Case Study (2026-03-11)

We scraped 123 images from Grok's public gallery. After training a projection:
- 109/123 (88.6%) detected as fake
- 14 misclassified — analysis revealed:
  - **4 images at 464x688** — exactly 0.6x of Grok's native 784x1168 → thumbnails
  - **1 image at 3072x4608** — a real DSLR photograph (user upload for editing)
  - **Other non-native resolutions** (640x480, 480x640, 720x1280, 960x960) — screenshots, thumbnails, or uploads
  - Only ~4-5 genuinely hard cases at native resolution

Conclusion: ~8-9 of 14 "misclassifications" were actually **bad training data**, not
detector failures. Automated validation would have caught these before they entered
the pipeline.

---

## Architecture

### Three-Phase Workflow

#### Phase 1: Reconnaissance & Script Development
- Claude Code (orchestrator) visits the target source
- Understands page structure: gallery layout, pagination, full-res vs thumbnail URLs
- Writes scraping code using appropriate tools:
  - **Scrapling** (`https://github.com/D4Vinci/Scrapling`) — modern, anti-bot-detection
  - **Crawlee** (`https://github.com/apify/crawlee-python`) — full crawling framework
  - **Selenium + BeautifulSoup4** — old-school, headless Chromium for JS-heavy sites
  - **requests + BS4** — for simple static pages or known APIs
- MCP browser tools (Playwright) for page rendering and visual understanding

#### Phase 2: Validation & Testing
- Run scraper on small batch (20-50 images)
- Automated quality checks (NOT using FSD detector — it might fail on new generators):
  - **Resolution check**: matches known native output size for that generator
  - **EXIF analysis**: no camera metadata (Make/Model/exposure → likely real photo)
  - **Thumbnail detection**: dimensions suspiciously small or exact fractional scale of native
  - **File size / BPP**: within expected range for generator
  - **Format check**: expected format (e.g., Grok outputs JPEG with specific quantization)
  - **Duplicate detection**: perceptual hashing to catch re-downloads
- Human review of flagged items
- Iterate until pipeline is clean

#### Phase 3: Production Pipeline (as Claude Code Skill)
- Package tested code as a Claude Code skill (e.g., `/curate-grok`)
- Skill handles: rate limiting, exponential backoff, random delays, resume-on-failure
- Agent teams can run multiple sources in parallel
- Structured output: X downloaded, Y filtered, Z flagged for review

### Agent Architecture

```
┌─────────────────────────────────────────────┐
│           Claude Code (Orchestrator)         │
│  - Plans curation tasks                      │
│  - Dispatches sub-agents                     │
│  - Aggregates results                        │
│  - Human-in-the-loop decisions               │
├──────────┬──────────────┬───────────────────┤
│          │              │                    │
│  Scraper │  Validator   │  Report Generator  │
│  Agent   │  Agent       │  Agent             │
│          │              │                    │
│  Browses │  Resolution  │  Summarizes run    │
│  source, │  EXIF check  │  Flags anomalies   │
│  downloads│  BPP check  │  For human review  │
│  images  │  Dedup       │                    │
└──────────┴──────────────┴───────────────────┘
```

### LLM Resources

- **Claude Code (Max plan)**: Primary orchestrator + sub-agents. Unlimited usage.
- **Qwen3.5 122B-A10B**: Running locally via llama.cpp, accessible at `http://tai.ngrok.dev`.
  OpenAI-compatible API. Text-only (no vision). Good for:
  - Bulk text processing (parsing HTML, extracting URLs)
  - Generating scraping code variants
  - Summarization tasks
  - Fallback when Claude Code usage is throttled

### MCP Browser Server Setup

For page rendering and visual understanding of galleries:

```bash
# Playwright MCP (Microsoft official, uses accessibility trees — more efficient)
claude mcp add --transport stdio playwright -- npx -y microsoft/playwright-mcp

# Or Puppeteer MCP (from MCP project repo)
claude mcp add --transport stdio puppeteer -- npx -y @modelcontextprotocol/server-puppeteer
```

This gives Claude Code tools like: `navigate`, `screenshot`, `click`, `get_page_content`,
`get_accessibility_tree`, `evaluate` (run JS), `fill`, `wait_for_selector`.

---

## Known Generator Metadata

Information gathered from analysis (update as we learn more):

### Grok (Aurora model, as of 2026-03)
- **API docs**: https://docs.x.ai/developers/model-capabilities/images/generation#aspect-ratio
- **Aspect ratios**: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 19.5:9, 9:19.5, 20:9, 9:20, auto
- **Resolution tiers**: "1k" (~915k pixels) and "2k" (~4M pixels, TBD)
- **DON'T match exact resolutions** — too many aspect ratio + tier combinations.
  Use pixel count bounds instead: MIN_PIXELS=800k, MAX_PIXELS=5M
- **Observed 1k resolutions** (for reference): 784x1168, 1168x784, 832x1248,
  1248x832, 960x960, 720x1280, 1280x720, 896x1344, 1360x768
- **Output format**: JPEG (quality ~95-100, avg quantization ≈ 1.0) or PNG
- **EXIF signature**: Some images have `Artist` = UUID, `ImageDescription` = `Signature: <base64>` (C2PA-style watermark). Not all images have this.
- **No camera EXIF**: No Make, Model, ExposureTime, FNumber, etc.
- **Gallery URL**: Grok Imagine public gallery (exact URL TBD)
- **Gotchas**:
  - Gallery serves thumbnails (~319k pixels, e.g., 464x688) alongside full-res
  - Users can upload real photos for editing/remixing — these appear in gallery
    (e.g., 3072x4608 = 14M pixels DSLR photo)
  - Some images are re-compressed (avg_q ≈ 29, vs native ≈ 1.0-5.8)
- **FSD detection**: 88.6% after Grok projection (projection #18, leaf=0c7ce0ee560c)
  Pre-projection was only 12.2%. Most misses were bad data (thumbnails/uploads).

### ChatGPT (DALL-E 3, as of 2026-02)
- **Detection rate**: 100% (11/11 in our tests)
- **Mean z-score**: -15.56 (very strong signal)

### Gemini (Imagen, as of 2026-02)
- **Detection rate**: 90.9% (10/11)
- **Mean z-score**: -6.75
- **1 miss**: z = +0.01 (borderline)

### Qwen3 (as of 2026-02)
- **Detection rate**: 90.0% (9/10)
- **Mean z-score**: -4.43
- **1 miss**: z = -0.58

---

## Validation Heuristics

### Pixel Count Filtering (preferred over exact resolution matching)

Don't try to enumerate every valid resolution — generators have many aspect ratios
and resolution tiers, making exact matching brittle. Instead, use pixel count bounds:

```python
# Per-generator pixel count bounds
PIXEL_BOUNDS = {
    "grok": {"min": 800_000, "max": 5_000_000},  # 1k tier ≈ 915k pixels
    # Add more generators as we learn them
}
```

This catches:
- Thumbnails (e.g., 464x688 = 319k pixels — well below 800k)
- Real uploads (e.g., 3072x4608 = 14M pixels — well above 5M)

### EXIF-Based Filtering

AI-generated images should NOT have camera EXIF data. Presence of any of these
strongly suggests a real photograph:
- `Make` / `Model` (camera manufacturer/model)
- `ExposureTime`, `FNumber`, `ISOSpeedRatings`, `FocalLength`
- GPS coordinates

Some generators add their own EXIF (Grok's `Artist` + `Signature`), which is fine.

### Size-Based Filtering

- **Thumbnails**: If image dimensions are an exact fractional scale (0.5x, 0.6x, 0.25x)
  of the native resolution, it's likely a thumbnail
- **Too large**: If dimensions significantly exceed the generator's max output, it's
  likely a real uploaded photo or upscaled image
- **BPP (bits per pixel)**: Unusual BPP may indicate re-compression or format conversion

---

## Scraping Best Practices

### Rate Limiting
- Random delays between requests (e.g., 1-5 seconds, uniform distribution)
- Respect `robots.txt` where applicable
- Exponential backoff on HTTP 429 (Too Many Requests)
- Track and log all rate limit events

### Resume Support
- Track downloaded files in a CSV/SQLite manifest
- On restart, skip already-downloaded files
- Separate tracking for: downloaded, filtered, errored

### Anti-Detection (where needed)
- Rotate User-Agent strings
- Use headless browser for JS-rendered content
- Random request intervals to mimic human browsing

### Output Structure
```
data/{generator_name}/
├── images/              # Downloaded images (only validated ones)
├── staging/             # Freshly downloaded, pre-validation
├── rejected/            # Failed validation (for debugging)
├── manifest.csv         # Download log: filename, url, timestamp, status
└── validation_report.json  # Per-image validation results
```

---

## Relationship to FSD Detector

This project produces clean training data that feeds into the FSD pipeline:

```
[This Project]                    [FSD Detector (07-fsd)]

Source Gallery
    │
    ▼
Scraper Agent ──► staging/
    │
    ▼
Validator Agent ──► images/  ──►  fsd-gen (Ray Serve) ──► .pth files
                    or                                        │
                    rejected/                                 ▼
                                                        fsd-train-projection
                                                              │
                                                              ▼
                                                        New projection checkpoint
```

### Key Paths in FSD Detector
- **Dev repo**: `~/1-workdir/07-fsd/`
- **Public repo**: `~/1-workdir/07-fsd-public/`
- **FSD data**: `/home/tai/weka_data/tai/fsd_generations/version_MUPIN1k_v1.1/`
- **Projections**: `/home/tai/weka_data/tai/fsd_generations/version_MUPIN1k_v1.1/projections/`
- **Current projection leaf**: `0c7ce0ee560c3736245476c3dfe9e076e3b0a96bba289ffb65998196a7133815` (18 projections, includes Grok)
- **FSD generation service**: `fsd-gen` via Ray Serve (expects grayscale PIL image as base64)
- **Conversion guide**: `~/1-workdir/07-fsd-public/internal/CONVERSION_GUIDE.md`

### FSD Generation for New Data
Once curated images are ready, generate FSDs:
```bash
cd ~/1-workdir/07-fsd
# Start Ray Serve (uses fsd/services/fsd_modeling_v0_1.py)
# Then use fsd-gen CLI or POST to http://localhost:8000 with image_b64
```

---

## Technology Stack

- **Python >=3.12** (matching FSD detector)
- **uv** for package management
- **Scraping**: Scrapling, Crawlee-python, or Selenium+BS4 (per source)
- **Image processing**: Pillow (EXIF, resolution, format detection)
- **Deduplication**: imagehash (perceptual hashing)
- **Browser automation**: Playwright MCP server (for Claude Code) + Playwright Python (for scripts)
- **LLM**: Claude Code (Max plan, orchestrator), Qwen3.5 122B (local, text tasks)
- **Data storage**: Local filesystem with CSV/JSON manifests

---

## Open Questions

1. **Browser MCP vs Python Playwright**: MCP gives Claude Code direct browser tools.
   Python Playwright gives more control in scripts. Probably need both — MCP for
   reconnaissance (Phase 1), Python for production scraping (Phase 3).

2. **Qwen3.5 integration**: How to best use the local LLM. It's text-only, so no
   image understanding. Best for: HTML parsing, URL extraction, code generation,
   summarization. Could wrap it as an MCP server or just call via requests.

3. **Skill format**: What's the best way to package scrapers as Claude Code skills?
   Need to research the skill spec.

4. **Scale**: How many images per generator do we need? The FSD projection training
   used 86 train / 37 test for Grok (123 total). More data = better projection.
   Target maybe 500-1000 per generator?

5. **Legal/ToS**: Each source has different terms. Need to check before scraping.
