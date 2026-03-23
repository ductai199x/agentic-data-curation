---
name: curate
description: Collect and validate AI-generated images from a specific generator for FSD forensic detector training. Use when the user wants to curate, scrape, or build a dataset of AI-generated images from a specific generator (e.g. grok, gemini, gpt_image_1, midjourney, nano_banana_1_2). Handles source research, scraping from Civitai/Twitter/Reddit/Higgsfield, multi-stage validation (JoyCaption + structural + FSD), and quality assurance. Invoke with /curate <generator_name>.
argument-hint: "<generator> [--max-images N] [--sources civitai,reddit,twitter]"
---

# Curate AI-Generated Images

Curate a validated dataset of `$ARGUMENTS` images for FSD training.

Read [reference.md](reference.md) for scraper commands, config template, validation
commands, and critical rules. Read it section-by-section as needed, not all at once.

## How You Operate

You are the orchestrator. The user invoked this skill because they want you to
handle the pipeline, not babysit it.

**Principles:**
- Run autonomously after intake — no confirmation prompts or approval gates
- Escalate only on true blockers (expired auth, platform outages, ambiguous policy)
- Spot-check constantly — after every batch, not just at the end
- Parallelize: scrape multiple sources simultaneously, build new scrapers while others run
- Use `nohup` with log files for long-running tasks (not `run_in_background` — 10-min timeout)
- Check `ps aux | grep` before starting any background process

**Worklog** — Create `docs/WORKLOG_<YYYYMMDD_HHMM>_<generator>.md` at the start.
Update at every phase boundary and decision point.

## Phase 0: User Intake

Ask all at once, skip what's already answered:

> 1. **Sources**: Where are `$ARGUMENTS` images posted? Or should I research?
> 2. **Generator profile**: Known resolutions/formats? Or should I research?
> 3. **Auth**: Cookies for X.com, Discord, Instagram? Is JoyCaption/GPU available?
> 4. **Content policy**: NSFW ok? What can't this generator produce?
> 5. **Target**: How many images? Any quality bar?
> 6. **Known issues**: Prior attempts, contamination, Reddit noise?

Key decisions from intake:
- **GPU available** → scrape + validate in parallel (producer/consumer)
- **GPU NOT available** → scrape only, accumulate in staging, validate later
- **Reddit** → only if user explicitly wants it, with extremely strict filtering

## Phase 1: Research & Profiling

**Before building anything**, check what already exists:
- Run `make stats` to see current datasets
- Check `configs/` for existing configs that might cover this generator
- Check `scrapers/` for scrapers that already work with the target platform
- Read `docs/LESSONS_*.md` for any prior attempts

**Research sources in parallel** using agent teams:
- One agent per potential platform (Civitai, Higgsfield, Discord, Tensor.Art, etc.)
- Each agent should: check if the generator exists on that platform, estimate volume,
  test the API inline (curl/python), and report viability
- See [reference.md → Available Scrapers](reference.md#available-scrapers) for the full
  platform list and which scrapers already exist

**Build the config** at `configs/<generator>.py` from research results.
Use an existing config as template (e.g. `configs/flux1.py`).

**Build new scrapers only if needed.** If the platform already has a scraper, just
update the config. If a new scraper is needed, build it while existing scrapers run.

## Phase 2: Scraping

Start scrapers in priority order (see [reference.md → Source Priority](reference.md#source-priority)).
Run multiple sources in parallel via `nohup`.

**If GPU available** — run caption+pipeline sweeps on staging every 15-20 min:
```
while scraper_running:
    batch_classify staging → captions.json
    pipeline --skip-fsd staging
    sleep 15-20 min
final_sweep after scraper exits
fsd-score on images/
```

**If GPU NOT available** — just accumulate in staging. Report counts periodically.

**Monitor actively:**
- Check download counts every 15-30 min
- Spot-check downloaded images (are they the right generator? right resolution?)
- Watch for errors, rate limits, account bans
- Build new scrapers for additional platforms while waiting

## Phase 3: Validation

**BEFORE running batch_classify:**
- Confirm JoyCaption is running: `ps aux | grep serve_joycaption`
- If not running, start it or use `--local` mode for small batches

**AFTER running batch_classify:**
- **Audit captions.json for errors**: `python -c "import json; d=json.load(open('captions.json')); print(sum(1 for v in d.values() if 'error' in v), 'errors')"`
- If errors > 0, JoyCaption wasn't running. Clear errors, restart, re-caption.

**Run pipeline**: `uv run python -m validators.pipeline --config configs/<gen>.py --skip-fsd`

**Spot-check**: Sample 10-20 rejected AND accepted images. Look for:
- False rejects (photorealistic images wrongly rejected by keywords)
- False accepts (illustrations, screenshots, wrong-generator images that slipped through)

**FSD scoring**: Run after validation on final `images/` directory. Tag only, never filter.

## Phase 4: Finalize

1. `make metadata` — rebuild metadata.csv for all datasets
2. `make stats` — verify counts look right
3. `make sync` — push to weka
4. Write `docs/LESSONS_<GENERATOR>.md` — distill what worked, what failed, platform quirks
5. Update worklog with final stats
6. Commit and push (`git add`, small focused commits)

## Lessons

Read `docs/LESSONS_MASTER.md` — 14 hard-won lessons from 10 generator runs.
It covers pipeline pitfalls, source selection, scraper building, and operations.
Per-generator details are in `docs/LESSONS_<GENERATOR>.md` — read those only
when working with a specific platform.
