---
name: curate
description: Collect and validate AI-generated images from a specific generator for FSD forensic detector training. Use when the user wants to curate, scrape, or build a dataset of AI-generated images from a specific generator (e.g. grok, gemini, gpt_image_1, midjourney, nano_banana_1_2). Handles source research, scraping from Civitai/Twitter/Reddit/Higgsfield, multi-stage validation (JoyCaption + structural + FSD), and quality assurance. Invoke with /curate <generator_name>.
argument-hint: "<generator> [--max-images N] [--sources civitai,reddit,twitter]"
---

# Curate AI-Generated Images

Curate a validated dataset of `$ARGUMENTS` images for FSD training. This skill runs
an end-to-end pipeline: research sources, scrape images, validate through multiple
stages, and produce a clean dataset with metadata.

For detailed tool commands, generator profiles, code patterns, and the workflow
checklist, see [reference.md](reference.md).

## How You Operate

You are the orchestrator — you own the entire pipeline after the user answers a few
intake questions. The user invoked this skill because they want you to handle it,
not babysit it.

**Research phase** (Phase 1): Use agent teams — independent teammates who can
challenge each other's findings and converge on the best sources. This prevents
anchoring on the first plausible source.

**Execution phase** (Phases 2–4): Use sub-agents for well-defined parallel jobs
(scraping, captioning, validation). You coordinate; they execute and report back.

**Principles:**
- Run autonomously after intake — no confirmation prompts or approval gates
- Escalate only on true blockers (expired auth, platform outages, ambiguous decisions)
- Spot-check constantly — after every scraping batch and validation stage, not just at the end
- Parallelize independent work (scrape multiple sources simultaneously, caption while scraping)
- Keep the user informed with concise status updates at phase boundaries
- Check `ps aux | grep` before starting any background process — duplicates cause corruption
- Use `nohup` with log files for long-running tasks, not `run_in_background` (10-min timeout)

**Worklog** — Create `docs/WORKLOG_<YYYYMMDD_HHMM>_<generator>.md` at the start.
Update at every phase boundary, unexpected finding, judgment call, and spot-check.
This is your lab notebook — it survives context compressions and becomes the raw
material for `docs/LESSONS_<GENERATOR>.md` at the end.

## Phase 0: User Intake

The only phase requiring user input. Ask these questions all at once, skip any the
user already answered:

> 1. **Sources**: Where are `$ARGUMENTS` images posted? (subreddits, Civitai, X.com accounts, galleries)
> 2. **Generator profile**: Known resolutions, aspect ratios, formats? Or should I research?
> 3. **Auth**: Have `cookies.txt` for X.com? Is JoyCaption running?
> 4. **Content policy**: What can't this generator produce? (provenance signal for filtering)
> 5. **Target**: How many images, what quality bar? ("1000 photorealistic" vs "5000 any style")
> 6. **Known issues**: Contamination patterns, watermarks, prior attempts?

After intake, incorporate their answers into the config and proceed immediately.

## Phase 1: Generator Profiling

Build or update `configs/<generator>.py`. Research what the user couldn't answer:
official API docs (aspect ratios, resolution tiers, formats), EXIF patterns, safety
filters, watermarks, Civitai model versions. Scout subreddit flairs early — add
reject flairs to config now, not after discovering contamination.

Use agent teams for this — one teammate per source type (Civitai, Twitter, Reddit,
other galleries). They should test APIs inline with curl/python before building
scraper code.

For the config template, see [reference.md → Config Template](reference.md#config-template).

Post a brief status update after profiling, then proceed to scraping without waiting.

## Phase 2: Scraping

Scrape from multiple sources in parallel, in priority order:

1. **Generator-specific galleries** (e.g. grok.com/imagine, Higgsfield) — best provenance
2. **Civitai on-site generation** — full-res, guaranteed AI, most trustworthy
3. **X.com bot media timeline** — official bot account only, every image is a generation
4. **Reddit** — supplemental only, extremely noisy (~10% actual AI art)

All scrapers use content-addressed storage (SHA256[:16] + ext), resume via manifest,
random delays (1-5s), and exponential backoff on 429s.

For detailed scraper commands and source-specific gotchas, see
[reference.md → Scraping](reference.md#scraping).

**During scraping**, run caption+pipeline sweeps on staging every 15-20 minutes.
Don't wait for scraping to finish — process images as they arrive using the
producer/consumer pattern:

```
while scraper_running:
    batch_classify staging → captions.json  (JoyCaption booru tags)
    pipeline --skip-fsd staging             (structural + content filter)
    sleep 15-20 min
final_sweep after scraper exits
fsd-score on images/                        (tag only, after all validation)
```

## Phase 3: Multi-Stage Validation

No single filter catches everything. Each stage catches different contamination.
The pipeline (`validators/pipeline.py`) orchestrates Tiers 0-2 automatically:

**Tier 0 — JoyCaption content filter** (catches ~15-18% of images)
- Booru tag mode, not descriptive captions (25% false-reject rate with descriptions)
- Config-driven REJECT_KEYWORDS with word-boundary regex (`\b`) — "graph" must not match "photograph"
- TEXT_PAIRED_KEYWORDS only reject when TEXT_INDICATORS also present

**Tier 1 — Structural validation**
- Format (PIL verification, not extension), pixel count (min/max), aspect ratio (known ratios ±5%)
- EXIF camera tags → real photo. Non-matching aspect ratio → screenshot/crop/wrong generator

**Tier 2 — FSD z-score tagging**
- Tag only, never filter — detection varies wildly: 100% DALL-E, 91% Gemini, 72% Grok, 33% Nano Banana
- Source provenance beats FSD for borderline cases every time

**Throughout validation**: spot-check rejected AND accepted images. Rejections catch
false positives early. Accepts catch contamination that slipped through. Sample 5-10
from each batch.

For stage-by-stage details, see [reference.md → Validation](reference.md#validation-pipeline).

## Phase 4: Metadata & Cleanup

After all validation:
1. Deduplicate manifest.csv (scrapers append on restart, creating duplicates)
2. Rebuild metadata.csv with all fields including model_version where available
3. Run FSD scoring on final validated images
4. Clean up staging/ and rejected/ (after user confirms)
5. Distill lessons into `docs/LESSONS_<GENERATOR>.md`
6. Update worklog with final stats

For metadata fields, see [reference.md → Metadata](reference.md#metadata-fields).

## Key Lessons (from Grok + Nano Banana curation)

These are hard-won — each came from a real failure or near-miss:

1. **Cleaning is harder than scraping** — expect 30-65% rejection rate depending on source mix
2. **Multi-stage filtering is mandatory** — format→resolution→aspect→content→FSD each catch different things
3. **Source provenance > any automated signal** — a trusted source (official gallery, on-site gen) beats any classifier
4. **Generator safety filters are provenance signals** — content the generator can't produce indicates contamination
5. **Reddit is supplemental only** — cap at 20-25% of dataset. Pre-filter by flair/title/domain (~57% noise reduction), then still manually spot-check (48% of post-filter images were junk for Grok)
6. **Civitai tool_id ≠ on-site generation** — tool_id includes user uploads with multi-tool workflows. Prefer model_version_id
7. **Aspect ratio outliers catch contamination fast** — screenshots, real photos, and wrong-generator images have non-standard ratios
8. **Word boundary regex is essential** — `\bgraph\b` not `graph` (matches "photograph")
9. **FSD: tag, never filter** — detection rates range from 33% (Nano Banana) to 100% (DALL-E)
10. **Test APIs inline before building scrapers** — curl/python one-liner first, scraper code second
11. **CDN metadata stripping is common** — C2PA/SynthID often stripped by CDNs (Higgsfield, Reddit). Model version info must come from API responses, not file metadata
12. **Resume by default, --force for clean rerun** — all scripts preserve existing work
13. **JoyCaption is a hard gate** — pipeline refuses uncaptioned images. Run batch_classify before pipeline
