---
name: curate
description: Collect and validate AI-generated images from a specific generator (e.g. grok, gemini, chatgpt). Handles scraping, multi-stage validation, and quality assurance.
argument-hint: "<generator> [--max-images N] [--sources civitai,reddit,twitter]"
allowed-tools:
  - Bash(uv run python *)
  - Bash(uv run fsd-score *)
  - Bash(ls *)
  - Bash(wc *)
  - Bash(rm *)
  - Bash(mv *)
  - Bash(mkdir *)
  - Bash(head *)
  - Bash(file *)
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
---

# Curate AI-Generated Images

## Orchestration Model

**You are the orchestrator.** You lead two types of workers depending on the phase:

- **Agent teams** — for exploratory/research work (Phase 0–1). Teammates are independent
  Claude Code sessions that can talk to each other, challenge findings, and self-coordinate
  via a shared task list. Use when multiple agents need to explore different angles and
  synthesize results collaboratively (e.g., researching sources, profiling a generator,
  scouting APIs and subreddits).
- **Sub-agents** — for execution work (Phase 2–4). Spawned via the `Agent` tool, they
  run tasks and report back to you. They can't talk to each other — you coordinate.
  Use for independent, well-defined jobs like scraping, validation, and scoring.

### When to use agent teams (research/exploration):
- Finding credible sources for a new generator (Civitai, X.com accounts, subreddits)
- Investigating generator profiles (API docs, resolution tiers, EXIF patterns, safety filters)
- Evaluating source quality (provenance reliability, contamination risk, yield estimates)
- Competing hypotheses (e.g., "is this Civitai tool_id clean or multi-tool contaminated?")

Teammates can challenge each other's findings and converge on the best sources. This
prevents anchoring on the first plausible source and missing better alternatives.

### When to use sub-agents (execution):
- Scraping from multiple sources in parallel
- Running batch classification, structural validation, FSD scoring
- Any well-defined task where the agent just needs to run a command and report results

### Example orchestration across phases:
```
Phase 0: User intake (ONLY user interaction)
  Ask questions → get answers → proceed autonomously

Phase 1: Research (agent team)
  Lead (you)
  ├── Teammate: Research Civitai sources (model versions, tool IDs)
  ├── Teammate: Scout X.com bot accounts and media timelines
  ├── Teammate: Survey subreddits, evaluate noise levels
  │   ... teammates share findings, challenge each other ...
  └── Synthesize: build config, post status update, proceed

Phase 2-4: Execution (sub-agents, autonomous — escalate only on blockers)
  Orchestrator (you)
  ├── Sub-agent: Scrape Civitai (background)
  ├── Sub-agent: Scrape X.com media timeline (background)
  ├── Sub-agent: Scrape Reddit (background)
  │   ... wait for scrapers → spot-check samples → post status ...
  ├── Sub-agent: Run JoyCaption batch classify (background)
  ├── Sub-agent: Run structural validation (background)
  │   ... wait for validation → spot-check rejections → post status ...
  ├── Sub-agent: Run FSD scoring (background)
  ├── Spot-check suspicious images (high FSD z-scores)
  ├── Final cleanup and metadata rebuild
  └── Post final report with dataset stats
```

### General principles:
- **Run autonomously** — after Phase 0 (user intake), execute the entire pipeline
  end-to-end without asking for approval or confirmation. Make decisions yourself.
  The user invoked this skill to have you handle it.
- **Escalate only on blockers** — only ask the user for help on things you can't
  resolve yourself: expired cookies/auth, platform outages, catastrophic failures,
  ambiguous decisions that could waste significant work. The user may interject
  while watching you work — incorporate their feedback and keep going.
- **Spot-check often** — don't wait until the end. After each scraping batch and
  each validation stage, sample a few images to verify quality. Catch problems early.
- **Stay in control** — you decide what to run, when, and how to handle failures.
- **Keep the user informed** — post concise status updates at phase boundaries.
  Don't dump raw output; synthesize it into brief progress reports.
- **Parallelize** — don't run independent work sequentially.
- **Maintain a worklog** — see below.

### Worklog (mandatory)

Create a worklog at `docs/WORKLOG_<YYYYMMDD_HHMM>_<generator>.md` at the very start
of Phase 1 (after user intake). Update it regularly throughout the run. This is your
running lab notebook — it captures decisions, findings, and lessons that would otherwise
be lost when the conversation context compresses.

**Update the worklog at these points:**
- After each phase boundary (profiling done, scraping done, validation done)
- When you discover something unexpected (API quirk, contamination pattern, dead end)
- When you make a judgment call (e.g. "skipped tool_id because on-site gen exists")
- When a scraper/validator succeeds or fails with notable stats
- When you do a spot-check and find problems (or confirm quality is good)
- At the very end with final dataset stats and lessons

**Format:**
```markdown
# Worklog: <Generator> Curation — <date>

## Summary
<1-2 line summary, updated at the end>

## Timeline

### Phase 1: Generator Profiling
- <timestamp> — <what happened, what was decided, why>

### Phase 2: Scraping
- <timestamp> — <source, count, issues, stats>

### Phase 3: Validation
- <timestamp> — <stage, pass/fail counts, patterns found>

### Phase 4: Cleanup
- <timestamp> — <final stats>

## Lessons Learned
<Distill into docs/LESSONS_<GENERATOR>.md at the end>

## Pending / Follow-up
<Anything that couldn't be resolved in this run>
```

The worklog serves two purposes:
1. **During the run**: helps you (and the user watching) track progress across context compressions
2. **After the run**: raw material for distilling `docs/LESSONS_<GENERATOR>.md`

## Arguments

- `<generator>`: Target generator name (e.g. `grok`, `gemini`, `chatgpt`, `midjourney`)
- `--max-images N`: Target image count (default: 1000)
- `--sources`: Comma-separated source list (default: `civitai,reddit,twitter`)

## Phase 0: User Intake (ONLY phase requiring user input)

**ALWAYS start here.** This is the ONLY time you ask the user questions. After this
phase, you run the entire pipeline autonomously — no confirmation prompts, no approval
gates. The user invoked this skill to have you handle it end-to-end.

Ask these questions BEFORE doing any research or scraping. Present them all at once
and wait for the user's response. Skip questions the user already answered in their
initial message.

> **Before I start curating `<generator>` images, a few quick questions:**
>
> 1. **Sources**: Do you know where `<generator>` images are posted?
>    (specific subreddits, Civitai tool ID, X.com hashtags/accounts, other galleries)
>
> 2. **Generator profile**: Do you know the native resolutions, aspect ratios, or
>    output formats? Or should I research from API docs?
>
> 3. **Auth**: Do you have `cookies.txt` for X.com? (needed for Twitter scraping)
>    Is JoyCaption Ray Serve already running?
>
> 4. **Content policy**: What can't this generator produce? (e.g. nudity, violence,
>    real people) — useful as a provenance signal for filtering fakes.
>
> 5. **Target**: How many images, and what's the quality bar?
>    (e.g. "1000 photorealistic only" vs "2000 any style")
>
> 6. **Known issues**: Anything else I should know? (contamination patterns,
>    watermarks from other generators, prior curation attempts, etc.)

After the user responds:
- Fill in what they provided into the generator config
- Research anything they said "I don't know" to
- If the user provides source-specific tips (e.g. "use this API endpoint"),
  incorporate them directly — don't override with generic defaults
- Then proceed immediately — no further confirmation needed

## Phase 1: Generator Profiling

Before scraping anything, build a generator profile. Check `configs/<generator>.py` —
if it doesn't exist, create it. Use the user's answers from Phase 0 to pre-fill
known values — only research what's still missing.

### What to research:
1. **Official API docs** — supported aspect ratios, resolution tiers, output formats
2. **Known EXIF patterns** — does the generator add metadata? (C2PA, Artist, Software)
3. **Safety filters** — what content does the generator block? (use as provenance signal)
4. **Known watermarks** — visible or invisible watermarks (SynthID, C2PA, corner logos)
5. **Civitai tool ID** — search Civitai for the generator, note the `tool_id` for API filtering

### Config template (`configs/<generator>.py`):
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

# Civitai — on-site generation (most trustworthy), each entry: (model_id, model_version_id)
CIVITAI_MODEL_VERSIONS = []  # find on Civitai
CIVITAI_TOOL_ID = None       # fallback only — used if no model versions

# X.com — bot media timeline (every image IS a generation)
TWITTER_MEDIA_URL = None     # e.g. "https://x.com/grok/media"
TWITTER_SEARCH_QUERIES = []  # generally unreliable — prefer media timeline
TWITTER_COOKIES_PATH = "data/cookies-x.txt"

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
REJECT_KEYWORDS = [...]      # see configs/nano_banana.py for full example
BLOCKED_CONTENT_TAGS = []    # safety filter (content generator can't produce)
```

## Status Update: Post plan summary (no confirmation needed)

After profiling, post a brief status update so the user knows what's happening,
then proceed immediately to scraping. Do NOT wait for confirmation.

> **Starting `<generator>` curation:**
> - **Sources**: [list with expected yield]
> - **Target**: [N] images
> - **Known risks**: [brief]
> - Scraping now...

## Phase 2: Scraping

Scrape from multiple sources in priority order. Each source has different
quality tradeoffs.

### Source priority:
1. **Civitai on-site generation** (`scrapers/civitai.py`) — Best quality (full-res, guaranteed AI).
   - Use `CIVITAI_MODEL_VERSIONS` tuples: `[(model_id, model_version_id)]` in config
   - On-site generation images are very trustworthy — no multi-tool contamination
   - Falls back to `CIVITAI_TOOL_ID` (user-uploaded) only if no model versions configured
   - ⚠️ Tool ID results include multi-tool workflows — check CDN filenames for `ComfyUI_*`
   - Rate limit: 5-12s between API calls, 1-3s between downloads
2. **X.com/Twitter** (`scrapers/twitter.py`) — Full-res originals with `name=orig`
   - **Primary**: Bot media timeline (e.g. `TWITTER_MEDIA_URL = "https://x.com/grok/media"`)
     - Every image on the bot's media timeline IS a generated image
     - Only scrape the generator's OFFICIAL bot account (e.g. @grok for Grok)
   - **Do NOT use search queries** like `"@grok generate" filter:images` — these match
     the USER's request tweet (with their reference photos), not the bot's reply
   - Requires `cookies.txt` (Netscape format, expires ~2 weeks)
   - Uses gallery-dl Python API with `ratelimit: "abort"` for partial results
   - ⚠️ Sometimes downloads MP4 as .jpg — verify with PIL
3. **Reddit** (`scrapers/reddit.py`) — Easy, no auth, but extremely noisy
   - Public JSON API: `reddit.com/r/<sub>/<sort>.json`
   - Use exact-phrase search queries, not keywords
   - Only PNGs survive compression intact
   - ⚠️ ~10% actual AI art in generator-specific subs; rest is screenshots/memes
   - **Post-level filtering** (config-driven, runs before download):
     - `REDDIT_REJECT_FLAIRS`: Skip Discussion, Meme, Humor, Advocacy flairs (catches ~48%)
     - `REDDIT_REJECT_TITLE_KEYWORDS`: Skip "vs", "comparison", "censored", "POV:", meme formats (catches ~8% more)
     - `REDDIT_SKIP_SELF_POSTS`: Skip text-only discussion threads
     - `REDDIT_ALLOWED_IMAGE_DOMAINS`: Only i.redd.it, preview.redd.it, i.imgur.com
   - Combined pre-filtering rejects ~57% of posts before download
   - **Even after pre-filtering, manual spot-check of Reddit images is still needed**
     (Grok experience: 48% of images passing automated validation were still junk)

### Data layout:
```
data/<generator>/
├── images/          # Validated (ready for FSD pipeline)
├── staging/         # Downloaded, pre-validation
├── manifest.csv     # Download tracking (resume support)
├── metadata.csv     # Per-image metadata after validation
├── booru_tags.json  # JoyCaption tags
├── fsd_scores.csv   # FSD z-scores
└── quality_scores.json
```

### Scraping rules:
- Content-addressed storage: filename = `SHA256[:16] + ext`
- Random delays between requests (1-5s)
- Exponential backoff on 429s
- Resume via manifest (skip already-downloaded URLs/hashes)
- Never commit images to git

## Phase 3: Multi-Stage Validation

No single filter catches everything. Run ALL stages in order.
Each stage catches different contamination types.

### Stage 1: Format check
- Reject GIFs, MP4s mislabeled as .jpg, corrupt files
- Verify with `PIL.Image.open()`, not file extension

### Stage 2: Resolution/pixel count
- Use `MIN_PIXELS` and `MAX_PIXELS` from config
- Don't enumerate exact resolutions — too many aspect ratio × tier combinations
- Below min = thumbnail or downscaled. Above max = real upload.

### Stage 3: Aspect ratio
- Check against `KNOWN_ASPECT_RATIOS` with tolerance
- Non-matching = screenshot, composite, crop, or different generator

### Stage 4: VLM content filter (vLLM or JoyCaption)
Two options — use whichever is available:

**Option A: vLLM with vision model** (preferred for flexibility)
- Start: `CUDA_VISIBLE_DEVICES=<gpu> uv run vllm serve <model> --port 8001 --max-model-len 8192 --gpu-memory-utilization 0.5`
- Recommended model: `Qwen/Qwen2.5-VL-7B-Instruct` (7B, fits on 1 GPU with 50% util)
- OpenAI-compatible API at `http://localhost:8001/v1/chat/completions`
- Can do both content classification AND quality assessment in one pass
- Use structured prompts: "Is this a photograph, screenshot, meme, chart, or AI-generated art?"
- ⚠️ Use port 8001 (JoyCaption uses 8000)

**Option B: JoyCaption booru tags** (proven for content filtering)
- **Use booru tag mode**: `"Write a list of Booru-like tags for this image."`
- NOT descriptive captions (25% false-reject rate from background descriptions)
- Run 6 parallel replicas via Ray Serve for throughput
- Start server: `CUDA_VISIBLE_DEVICES=0,1,2,3 python -m validators.serve_joycaption serve --config configs/<generator>.py --gpu 0.5 --replicas 6`

Both options:
- Reject: screenshots, memes, charts, comics, UI captures, text-heavy images
- ⚠️ Tag filter false positives common — use word-boundary regex (`\b`), spot-check results

### Stage 5: Quality rating
- JoyCaption prompt: rate SHARP / ACCEPTABLE / BLURRY
- Or vLLM prompt: "Rate image quality: SHARP, ACCEPTABLE, or BLURRY"
- Low yield (~0.25%) but cheap to run

### Stage 6: FSD z-score tagging
- `uv run fsd-score --dir <path> --weights-dir validators/fsd-weights --csv > results.csv`
- **TAG only, do NOT filter** — many genuine AI images fool FSD
- z > -0.15 = almost certainly real photo (hard filter OK at this threshold)
- Source provenance > FSD for borderline cases

### Status Update: Post validation summary

After automated stages complete, post a brief summary and continue:
- How many images passed/failed each stage
- Notable patterns (e.g., "Reddit had 80% rejection, mostly screenshots")
- Do NOT wait for confirmation — proceed to next stages.

### Stage 7: Automated tag-based filtering
- Search booru tags for provenance signals: @username watermarks, other generator watermarks
- Generator safety filter violations (e.g., Grok can't generate exposed genitalia)
- ⚠️ High false-positive rate — spot-check a sample yourself before batch removal

### Stage 8: Aspect ratio / pixel count outlier scan
- Filter images that don't match any known generator ratio (±5%)
- Visually inspect outliers — catches real photos, screenshots, other generators
- This found 25 removals out of 42 outliers for Grok

### Stage 9: Manual spot-check (do this often, throughout the pipeline)
- Sort by FSD z-score descending (most suspicious first)
- Visually inspect images — use VLM to describe suspicious ones
- Remove real photos / non-target-generator content
- Spot-check should happen frequently, not just at the end — after each batch
  of scraping, after each validation stage, after filtering. Catch problems early.

## Phase 4: Metadata & Cleanup

After validation, rebuild metadata and clean up:

```bash
# Rebuild metadata.csv with all fields
uv run python -c "...rebuild script..."  # see reference.md

# Delete staging/ and rejected/ when satisfied
rm -rf data/<generator>/staging/ data/<generator>/rejected/
```

### Metadata fields:
filename, content_hash, source, url, post_id, post_title, subreddit, flair,
download_timestamp, width, height, pixels, format, file_size_bytes,
exif_artist, exif_description, exif_software, has_generator_signature,
fsd_zscore, fsd_raw, fsd_is_fake, quality_rating, quality_detail

## Key Lessons (from Grok curation)

1. **The hardest part is cleaning, not scraping** — expect 60-65% rejection rate
2. **Multi-stage filtering is mandatory** — no single filter catches everything
3. **Spot-check before batch runs** — test 5-10 known problematic cases first
4. **Source provenance > any automated signal** for borderline cases
5. **Generator safety filters are provenance signals** — content the generator can't produce indicates contamination
6. **Civitai tool_id includes multi-tool workflows** — not all results are pure generator output
7. **Aspect ratio outlier scan** is the fastest way to find contamination late in the pipeline
8. **Word boundary regex required** — `"graph"` matches `"photograph"`
9. **FSD tags, not filters** — detection rates vary 72-100% across generators
10. **Reddit re-compresses JPEGs** — only PNGs preserve forensic signal
11. **Reddit needs pre-download filtering** — flair + title keyword + self-post + domain filters catch ~57% of noise before download. Even then, manual spot-check of Reddit images is critical (48% of post-filter images were still junk in Grok run).
12. **Scout subreddit flairs early** — different subs have different flair taxonomies. Add reject flairs to config during Phase 1 research, not after discovering contamination.
13. **Maintain a worklog** — `docs/WORKLOG_<datetime>_<generator>.md` captures decisions and lessons that would otherwise be lost across context compressions.
