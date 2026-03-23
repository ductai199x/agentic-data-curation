# CLAUDE.md — Agentic Data Curation

## Project Overview

Automated data curation toolkit for collecting clean AI-generated image datasets.
Uses Claude Code as the orchestrator with sub-agents for scraping, validation, and
reporting. Built to feed training data into the FSD forensic detector pipeline.

**162K+ validated images across 10 generators.** See `docs/LESSONS_*.md` for
per-generator lessons and `make stats` for current numbers.

## Setup & Installation

```bash
uv pip install -e .
```

Requires Python >=3.12. Uses `uv` for package management.

## Quick Commands

```bash
make help            # list all commands
make stats           # short summary table
make stats-detailed  # detailed per-dataset breakdown
make metadata        # rebuild metadata.csv for all datasets
make sync            # sync data/ to weka
```

## Project Structure

```
09-agent-data-curation/
├── CLAUDE.md              # This file
├── Makefile               # Common commands (make help)
├── pyproject.toml         # Package config
├── configs/               # Per-generator configs
│   ├── grok.py, flux1.py, flux2.py, midjourney_v7.py, soul2.py,
│   ├── recraft_3_4.py, gpt_image_1.py, nano_banana_1_2.py,
│   ├── seedream4.py, instagram_ai_influencer.py
├── scrapers/              # Per-source scraping modules
│   ├── base.py            # BaseScraper (content-addressed, manifest, resume)
│   ├── civitai.py         # Civitai TRPC API (on-site generation)
│   ├── civitai_simple.py  # Simplified Civitai scraper
│   ├── twitter.py         # X.com direct image search + /media timeline
│   ├── reddit.py          # Reddit JSON API with post-level pre-filtering
│   ├── higgsfield.py      # Higgsfield community gallery REST API
│   ├── midjourney.py      # Discord REST API with version detection
│   ├── instagram.py       # Instagram Playwright grid extraction
│   ├── recraft.py         # Recraft community gallery (Playwright)
│   ├── tensorart.py       # Tensor.Art (Playwright + requests hybrid)
│   ├── yodayo.py          # Yodayo (Playwright stealth)
│   ├── openart.py         # OpenArt REST API
│   ├── aigcarena.py       # AIGCArena (Playwright + a_bogus)
│   └── freepik.py         # Freepik REST API
├── validators/            # Image validation pipeline
│   ├── pipeline.py        # Config-driven validation (JoyCaption + structural + FSD)
│   ├── classify.py        # Caption keyword matching logic
│   ├── batch_classify.py  # Batch captioning (HTTP service or --local mode)
│   ├── serve_joycaption.py # JoyCaption Ray Serve deployment
│   ├── split_grids.py     # Midjourney grid splitter (256-worker parallel)
│   └── image_validator.py # Structural checks (pixels, aspect ratio, EXIF)
├── scripts/               # Utility scripts
│   ├── stats.py           # Dataset stats viewer (make stats)
│   ├── build_all_metadata.py # Metadata builder (make metadata)
│   └── sync_data.sh       # Weka sync (make sync)
├── docs/                  # Per-run worklogs and lessons
│   ├── LESSONS_*.md       # Distilled lessons per generator
│   └── WORKLOG_*.md       # Per-run worklogs
├── .claude/skills/        # Claude Code skills (/curate)
└── data/                  # Downloaded images (gitignored)
```

## Curated Datasets

| Dataset | Images | Source(s) | FSD Det% |
|---------|--------|-----------|----------|
| Midjourney v7 | 67,778 | Discord | 90.7% |
| Soul 2.0 | 25,796 | Higgsfield | 64.6% |
| FLUX.1 | 23,296 | Civitai, Tensor.Art, Yodayo, OpenArt | 81.5% |
| Nano Banana 1&2 | 12,566 | Higgsfield | 97.2% |
| Instagram AI | 11,797 | 57 Instagram accounts (eval set) | 47.9% |
| Recraft 3/4 | 6,901 | Recraft community | 93.7% |
| GPT-Image 1 | 4,138 | Civitai, Reddit, Higgsfield | 98.4% |
| Grok | 4,215 | Twitter, grok.com, Civitai | 88.4% |
| FLUX.2 | 3,430 | Civitai, Higgsfield, Tensor.Art | 83.8% |
| Seedream 4 | 2,733 | Higgsfield, Civitai, Yodayo | 21.3% |

## Key Conventions

- **Standalone project** — do NOT import from or depend on 07-fsd. Copy needed code.
- **Content-addressed storage** — filename = `SHA256[:16] + ext`. Zero duplicates.
- **Per-generator configs** — each generator has its own config with known resolutions,
  expected formats, scraping parameters, and content filtering keywords.
- **Multi-stage validation** — Format → Resolution → Aspect ratio → JoyCaption → FSD tag.
- **Always use `uv run`** for Python scripts — not bare `python3`.

## Curating a New Generator

Use the `/curate` skill — it encodes the full pipeline:

1. **User intake** — sources, generator profile, auth, content policy, target volume
2. **Generator profiling** — create `configs/<generator>.py` with aspect ratios, pixel bounds
3. **Scraping** — priority: generator gallery → Civitai on-site → Twitter direct search → Reddit (supplemental only)
4. **Multi-stage validation** — JoyCaption content filter → structural → FSD z-score tagging
5. **Metadata & cleanup** — rebuild metadata.csv, FSD scoring, sync to weka

See `.claude/skills/curate/SKILL.md` and `.claude/skills/curate/reference.md` for the
full pipeline with checkpoints, code patterns, and per-source gotchas.

## Data Output Structure

```
data/{generator_name}/
├── images/              # Validated images (ready for FSD pipeline)
├── staging/             # Freshly downloaded, pre-validation
├── manifest.csv         # Download log: filename, url, source, flair, timestamp
├── metadata.csv         # Per-image metadata (synced to weka)
├── captions.json        # JoyCaption booru tags
└── fsd_scores.csv       # FSD z-scores (tag only, don't filter)
```

## JoyCaption

Two modes:

```bash
# Ray Serve (high throughput, multi-GPU) — for large batches
CUDA_VISIBLE_DEVICES=6,7 python -m validators.serve_joycaption serve --gpu 0.25 --replicas 8
uv run python -m validators.batch_classify --dir data/<gen>/staging --output data/<gen>/captions.json --concurrency 8

# Local mode (single GPU, no Ray) — for small batches
uv run python -m validators.batch_classify --dir data/<gen>/staging --output data/<gen>/captions.json --local --gpu 6
```

## FSD Scoring

```bash
uv run fsd-score --dir data/<gen>/images/ --csv > data/<gen>/fsd_scores.csv
```

FSD is a local dependency (`fsd-detector` in pyproject.toml). Tag only, never filter —
detection rates vary wildly (21% Seedream to 98% GPT-Image).

## Scraping Rules

- Content-addressed storage (SHA256[:16] + ext) — zero duplicates
- Resume via manifest — skip already-downloaded files
- Random delays between requests (varies by platform)
- Exponential backoff on 429s
- Never commit downloaded images to git
- Civitai: on-site generation (model_version_id) ONLY — never tool_id
- Twitter: direct image search with daily date windowing
- Instagram: Playwright grid extraction (~2 img/s)
- Discord: REST API with snowflake pagination

## Related Projects

- **FSD Detector**: `~/1-workdir/07-fsd-public/` (local dependency, don't cd there)
- **Weka sync target**: `~/weka_data/tai/agentic-data-curation/ai_generated/`
