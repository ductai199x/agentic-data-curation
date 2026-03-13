# CLAUDE.md — Agentic Data Curation

## Project Overview

Automated data curation toolkit for collecting clean AI-generated image datasets.
Uses Claude Code as the orchestrator with sub-agents for scraping, validation, and
reporting. Built to feed training data into the FSD forensic detector pipeline.

**Read `docs/LESSONS_GROK.md` for lessons from the first curation run (Grok, ~1,700 images).**

## Setup & Installation

```bash
uv pip install -e .
```

Requires Python >=3.12. Uses `uv` for package management.

### VLM Backend (vLLM)

```bash
# Start Qwen2.5-VL on GPU 3, port 8001 (JoyCaption uses 8000)
CUDA_VISIBLE_DEVICES=3 uv run vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --port 8001 --max-model-len 8192 --trust-remote-code --gpu-memory-utilization 0.5
```

OpenAI-compatible API at `http://localhost:8001/v1/chat/completions`.
Use 8k+ context (images consume many tokens). Install: `uv pip install -e ".[vlm]"`

### JoyCaption (captioning service — config-independent)

```bash
source .venv/bin/activate
CUDA_VISIBLE_DEVICES=0,1,2,3 python -m validators.serve_joycaption serve --gpu 0.5 --replicas 6
```

Ray Serve on port 8000, 6 replicas across GPUs 0-3.

### MCP Browser Server (optional, for page reconnaissance)

```bash
claude mcp add --transport stdio playwright -- npx -y microsoft/playwright-mcp
```

## Project Structure

```
09-agent-data-curation/
├── CLAUDE.md              # This file
├── pyproject.toml         # Package config
├── docs/
│   ├── LESSONS_GROK.md    # Distilled lessons from Grok curation
│   └── WORKLOG_*.md       # Per-run worklogs (auto-maintained by agents)
├── scrapers/              # Per-source scraping modules (civitai, reddit, twitter, grok_imagine)
├── validators/            # Image validation, JoyCaption serve, batch classify
├── configs/               # Per-generator configs (grok.py, etc.)
├── .claude/skills/        # Claude Code skills (/curate, /curate-grok)
└── data/                  # Downloaded images (gitignored)
```

## Key Conventions

- **Standalone project** — do NOT import from or depend on 07-fsd. Copy needed code.
- **Content-addressed storage** — filename = `SHA256[:16] + ext`. Zero duplicates.
- **Per-generator configs** — each generator has its own config with known resolutions,
  expected formats, EXIF patterns, scraping parameters, and Reddit post filters.
- **Multi-stage validation** — no single filter catches everything. Run all stages.
- **Reddit pre-filtering** — scraper rejects posts by flair, title keywords, self-posts,
  and non-image domains BEFORE downloading. Config: `REDDIT_REJECT_FLAIRS`,
  `REDDIT_REJECT_TITLE_KEYWORDS`, `REDDIT_ALLOWED_IMAGE_DOMAINS`, `REDDIT_SKIP_SELF_POSTS`.
- **Always use `uv run`** for Python scripts — not bare `python3`.

## Curating a New Generator

Use the `/curate` skill — it encodes the full pipeline:

1. **User intake** — ask about sources, generator profile, auth, content policy
2. **Generator profiling** — create `configs/<generator>.py` with aspect ratios, pixel bounds
3. **Scraping** — Civitai (best quality) → X.com (full-res) → Reddit (noisy, pre-filtered)
4. **Multi-stage validation** — Format → Resolution → Aspect ratio → VLM/JoyCaption → FSD tag → Manual
5. **Metadata & cleanup** — rebuild metadata.csv, remove staging/rejected

Agents maintain a worklog at `docs/WORKLOG_<datetime>_<generator>.md` throughout curation.

See `.claude/skills/curate/SKILL.md` for the full pipeline with checkpoints.

## Data Output Structure

```
data/{generator_name}/
├── images/              # Validated images (ready for FSD pipeline)
├── staging/             # Freshly downloaded, pre-validation
├── manifest.csv         # Download log: filename, url, timestamp, status
├── metadata.csv         # Per-image metadata after validation
├── booru_tags.json      # JoyCaption booru tags
├── fsd_scores.csv       # FSD z-scores (tag only, don't filter)
└── quality_scores.json  # JoyCaption quality ratings
```

## Scraping Rules

- Always add random delays between requests (1-5s)
- Exponential backoff on 429s
- Resume support via manifest (skip already-downloaded files)
- Never commit downloaded images to git

## FSD Scoring

FSD is installed as a local dependency (`fsd-detector` in pyproject.toml).
Weights are at `validators/fsd-weights/`. Run from this project:

```bash
uv run fsd-score --dir path/to/images/ --weights-dir validators/fsd-weights --csv > results.csv
```

## Related Projects

- **FSD Detector (source)**: `~/1-workdir/07-fsd-public/` (do NOT cd there to run — use local dependency)
- **FSD Data**: `/home/tai/weka_data/tai/fsd_generations/version_MUPIN1k_v1.1/`

## GPU Allocation

| GPU | Usage |
|-----|-------|
| 0-2 | JoyCaption Ray Serve (6 replicas, ~34GB each) |
| 3   | vLLM Qwen2.5-VL-7B (port 8001, 50% util) |
| 4-7 | Reserved (other users) |
