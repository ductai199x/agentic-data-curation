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
make sync            # sync data/images/ to weka
make adapt           # new-generator adaptation pipeline (docs/ADAPT.md)
```

## Project Structure

```
09-agent-data-curation/
├── CLAUDE.md              # This file
├── Makefile               # Common commands (make help)
├── pyproject.toml         # Package config
├── configs/
│   ├── curate/
│   │   ├── images/        # Per-generator image scrape configs (grok, flux1, etc.)
│   │   └── videos/        # Real-video ingest configs (youtube, instagram)
│   └── generate/          # Fake-video generation configs (wan22, hunyuan, etc.)
├── curate/                # Data curation pipelines
│   ├── images/            # Image curation
│   │   ├── scrapers/      # Per-source scraping modules
│   │   │   ├── base.py            # BaseScraper (content-addressed, manifest, resume)
│   │   │   ├── civitai.py         # Civitai TRPC API (on-site generation)
│   │   │   ├── civitai_simple.py  # Simplified Civitai scraper
│   │   │   ├── twitter.py         # X.com direct image search + /media timeline
│   │   │   ├── reddit.py          # Reddit JSON API with post-level pre-filtering
│   │   │   ├── higgsfield.py      # Higgsfield community gallery REST API
│   │   │   ├── midjourney.py      # Discord REST API with version detection
│   │   │   ├── instagram.py       # Instagram Playwright grid extraction
│   │   │   ├── recraft.py         # Recraft community gallery (Playwright)
│   │   │   ├── tensorart.py       # Tensor.Art (Playwright + requests hybrid)
│   │   │   ├── yodayo.py          # Yodayo (Playwright stealth)
│   │   │   ├── openart.py         # OpenArt REST API
│   │   │   ├── aigcarena.py       # AIGCArena (Playwright + a_bogus)
│   │   │   ├── sora.py            # Sora REST API (curl_cffi)
│   │   │   └── freepik.py         # Freepik REST API
│   │   └── validators/    # Image validation pipeline
│   │       ├── pipeline.py        # Config-driven validation (JoyCaption + structural + FSD)
│   │       ├── classify.py        # Caption keyword matching logic
│   │       ├── batch_classify.py  # Batch captioning (HTTP service or --local mode)
│   │       ├── serve_joycaption.py # JoyCaption Ray Serve deployment
│   │       ├── split_grids.py     # Midjourney grid splitter (256-worker parallel)
│   │       └── image_validator.py # Structural checks (pixels, aspect ratio, EXIF)
│   ├── videos/            # Real-video curation (discover → download → validate)
│   ├── stats.py           # Dataset stats viewer (curate stats)
│   ├── build_metadata.py  # Metadata builder (curate build-metadata)
│   └── cli.py             # Top-level `curate` CLI
├── generate/              # Fake-video generation pipeline
│   ├── comfy_batch_run.py # Generic ComfyUI worker shard
│   ├── comfy_config.py    # Config loader + ComfyRunConfig
│   ├── workflows/         # Per-model ComfyUI workflow builders
│   ├── extract_frames.py  # First/last frame pre-extract
│   ├── diversity_rank.py  # Stratified round-robin clip picker
│   ├── interpolate_fps.py # RIFE 16fps→30fps interpolation
│   ├── rewrite_captions.py# Short-form caption rewriter
│   ├── taxonomy_label.py  # Qwen taxonomy labeler
│   ├── build_dataset_metadata.py # vFSD manifest+metadata builder
│   ├── regen_stretched.py # Re-gen aspect-broken clips on resume
│   └── cli.py             # Top-level `generate` CLI
├── shared/                # Shared helpers (clip listing, manifests, sharding)
├── scripts/               # Bash launchers + standalone tools
│   ├── launch.sh          # ComfyUI worker launcher
│   ├── launch_interpolate.sh # RIFE multi-shard launcher
│   ├── sync_data.sh       # Weka sync (make sync)
│   └── youtube_standalone_downloader.py # multi-machine yt-dlp script
├── docs/                  # Per-run worklogs and lessons
│   ├── LESSONS_*.md       # Distilled lessons per generator
│   └── WORKLOG_*.md       # Per-run worklogs
├── .claude/skills/        # Claude Code skills (/curate)
└── data/                  # All data (gitignored)
    ├── images/            # AI-generated image datasets (per generator)
    ├── videos/            # Video datasets (real + AI-generated)
    └── cookies/           # Auth cookies for scrapers
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

## ⚠️  Critical: Verify File Contents, Not Just Filenames

Before processing, renaming, deleting, or generating downstream from any data file
that's named after a pipeline stage (e.g., `salmonn_captions_cleaned.json`,
`joycaption_tags.csv`, `embeddings_clip_l.npy`), **open it and sample at least one
value** to confirm the format matches what the name claims.

This rule exists because of a real failure (Apr 2026): a file labeled
`salmonn_captions_cleaned.json` actually contained JoyCaption-per-frame booru-tag
concatenations (median 21 KB per entry, "photograph," repeated 30+ times) — NOT
SALMONN paragraph captions. The mislabel was baked in from inception. Across
multiple "thorough audits" the file's **size, schema, importability, and key set**
were all checked, but **no value was ever sampled**. As a result, ~15,400 YouTube
fake videos were generated over a week of compute on garbage prompts.

**Audit checklist (do this for any "labeled" data file before downstream use):**
- Captions: `python -c "import json; d=json.load(open(F)); v=list(d.values())[0]; print(repr(v)[:500] if not isinstance(v,dict) else repr(v.get('caption',''))[:500])"`
- Captions length distribution: SALMONN paragraphs ≈ 1-3 KB / JoyCaption single-frame tags ≈ 0.5-1 KB / JoyCaption-frame-concat ≈ 10-30 KB
- CSVs: `head -2` for columns + 5 random `awk` rows
- Embeddings: load + assert `arr.shape[1]` matches expected dim
- If a smoke test produces unexpected quality, **the first hypothesis to check is the
  input prompt/data, not the model**.

See [memory/feedback_verify_file_contents_not_filenames.md](memory/feedback_verify_file_contents_not_filenames.md)
for the full lesson.

## Adapting to a New Generator (timed)

`adapt/` turns a new row in `configs/adapt/releases.md` into samples, a ready-to-train batch, a before/after
evaluation through the processing ladder, and a time-to-adapt log with a halving curve. Training and the detector
plug in through `ADAPT_TRAIN_CMD` / `ADAPT_DETECT_CMD`. See `docs/ADAPT.md`; `make adapt-dry-run` is safe anywhere.

## Curating a New Generator

Use the `/curate` skill — it encodes the full pipeline:

1. **User intake** — sources, generator profile, auth, content policy, target volume
2. **Generator profiling** — create `configs/curate/images/<generator>.py` with aspect ratios, pixel bounds
3. **Scraping** — priority: generator gallery → Civitai on-site → Twitter direct search → Reddit (supplemental only)
4. **Multi-stage validation** — JoyCaption content filter → structural → FSD z-score tagging
5. **Metadata & cleanup** — rebuild metadata.csv, FSD scoring, sync to weka

See `.claude/skills/curate/SKILL.md` and `.claude/skills/curate/reference.md` for the
full pipeline with checkpoints, code patterns, and per-source gotchas.

## Data Output Structure

```
data/
├── images/{generator_name}/     # AI-generated image datasets
│   ├── images/                  # Validated images (ready for FSD pipeline)
│   ├── staging/                 # Freshly downloaded, pre-validation
│   ├── manifest.csv             # Download log: filename, url, source, flair, timestamp
│   ├── metadata.csv             # Per-image metadata (synced to weka)
│   ├── captions.json            # JoyCaption booru tags
│   └── fsd_scores.csv           # FSD z-scores (tag only, don't filter)
├── videos/                      # Video datasets (real + AI-generated)
│   └── real/{source}/           # Real video clips by platform
│       ├── staging/             # Downloaded, pre-validation
│       ├── validated/           # Passed all checks
│       ├── rejected/            # Failed validation
│       ├── manifest.csv         # Download log with taxonomy tags
│       └── metadata.csv         # Per-clip metadata (resolution, fps, codec, etc.)
└── cookies/                     # Auth cookies for scrapers
```

## JoyCaption

Two modes:

```bash
# Ray Serve (high throughput, multi-GPU) — for large batches
CUDA_VISIBLE_DEVICES=6,7 python -m curate.images.validators.serve_joycaption serve --gpu 0.25 --replicas 8
uv run python -m curate.images.validators.batch_classify --dir data/images/<gen>/staging --output data/images/<gen>/captions.json --concurrency 8

# Local mode (single GPU, no Ray) — for small batches
uv run python -m curate.images.validators.batch_classify --dir data/images/<gen>/staging --output data/images/<gen>/captions.json --local --gpu 6
```

## Video Captioning (SALMONN 2+)

Generates the `video_captions.json` files that condition fake-video generation.
Multi-GPU launcher mirrors `scripts/launch.sh` (ComfyUI):

```bash
VIDEOS_DIR=data/videos/real/youtube/validated \
OUTPUT_JSON=data/videos/real/youtube/video_captions.json \
scripts/launch_caption.sh start

scripts/launch_caption.sh status   # check workers
scripts/launch_caption.sh stop     # kill all shards
```

Or single-shard via CLI: `curate videos caption-salmonn --videos-dir ... --output ...`

The captioner code is at [curate/videos/caption_salmonn.py](curate/videos/caption_salmonn.py)
but runs against the SALMONN venv at
`third_party/SALMONN-2-plus/.venv/` (heavy ML deps:
qwenvl, flash-attn, liger_kernel). The launcher sets PYTHONPATH so imports
resolve. Outputs are sharded `*_shard{id}.json` per worker; merging is the
caller's responsibility.

## FSD Scoring

```bash
uv run fsd-score --dir data/images/<gen>/images/ --csv > data/images/<gen>/fsd_scores.csv
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
