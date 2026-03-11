# CLAUDE.md — Agentic Data Curation

## Project Overview

Automated data curation toolkit for collecting clean AI-generated image datasets.
Uses Claude Code as the orchestrator with sub-agents for scraping, validation, and
reporting. Built to feed training data into the FSD forensic detector pipeline.

**Read `docs/DESIGN.md` first** — it contains the full design, architecture, known
generator metadata, validation heuristics, and the Grok case study that motivated
this project.

## Setup & Installation

```bash
uv pip install -e .
```

Requires Python >=3.12. Uses `uv` for package management.

### MCP Browser Server (optional, for page reconnaissance)

```bash
claude mcp add --transport stdio playwright -- npx -y microsoft/playwright-mcp
```

### Local LLM (optional)

Qwen3.5 122B-A10B available at `http://tai.ngrok.dev` (OpenAI-compatible API, text-only).

## Project Structure

```
09-agent-data-curation/
├── CLAUDE.md              # This file
├── pyproject.toml         # Package config
├── docs/
│   └── DESIGN.md          # Full design document (READ THIS)
├── scrapers/              # Per-source scraping modules
├── validators/            # Image validation (resolution, EXIF, etc.)
├── skills/                # Claude Code skills (/curate-grok, etc.)
├── configs/               # Per-source configs (URLs, resolutions, etc.)
└── tests/                 # Tests
```

## Key Conventions

- **Standalone project** — do NOT import from or depend on 07-fsd. Copy needed code.
- **Content-addressed storage** — use content hashes, not metadata or absolute paths.
- **Per-source configs** — each generator has its own config with known resolutions,
  expected formats, EXIF patterns, and scraping parameters.
- **Three-phase workflow**: 1) Recon & script dev, 2) Validate & test, 3) Skill-ify

## Related Projects

- **FSD Detector (dev)**: `~/1-workdir/07-fsd/`
- **FSD Detector (public)**: `~/1-workdir/07-fsd-public/`
- **FSD Data**: `/home/tai/weka_data/tai/fsd_generations/version_MUPIN1k_v1.1/`
- **Conversion Guide**: `~/1-workdir/07-fsd-public/internal/CONVERSION_GUIDE.md`

## Workflow: Adding a New Generator

1. **Recon**: Identify the source gallery/API. Use Playwright MCP or manual browsing
   to understand page structure.
2. **Write scraper**: In `scrapers/{generator}.py`. Use appropriate library for the
   source (Scrapling, Crawlee, Selenium+BS4, or plain requests).
3. **Configure**: Add generator metadata to `configs/{generator}.py` — native
   resolutions, expected formats, EXIF patterns.
4. **Validate**: Run validator on a small test batch. Check resolution, EXIF,
   file size, duplicates. Fix scraper issues.
5. **Skill-ify**: Once stable, package as a Claude Code skill in `skills/`.
6. **Deploy**: Run the skill to collect the target number of images.
7. **Feed to FSD**: Generate FSDs via `fsd-gen`, train projection, evaluate.

## Data Output Structure

```
data/{generator_name}/
├── images/              # Validated images (ready for FSD pipeline)
├── staging/             # Freshly downloaded, pre-validation
├── rejected/            # Failed validation (kept for debugging)
├── manifest.csv         # Download log: filename, url, timestamp, status
└── validation_report.json
```

## Scraping Rules

- Always add random delays between requests (1-5s)
- Respect robots.txt
- Exponential backoff on 429s
- Resume support via manifest (skip already-downloaded files)
- Never commit downloaded images to git
