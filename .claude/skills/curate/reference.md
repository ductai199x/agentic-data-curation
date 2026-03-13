# Curate Skill — Reference

## Known Generator Profiles

### Grok — `configs/grok.py`
- Civitai on-site generation: model_version_id=2738377, model_id=2435474 (very trustworthy)
- Civitai tool_id: 284 (fallback only — user-uploaded, less trustworthy, skipped if on-site gen exists)
- X.com: @grok/media timeline (every image IS a Grok generation — posted as replies)
- grok.com/imagine: REST API, 100% provenance, full-res PNGs + prompts
- Aspects: 1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 11:6, 6:11, 19.5:9, 9:19.5, 20:9, 9:20
- Pixel count: ~915k (1k tier), ~4M (2k tier)
- Format: JPEG (avg_q 1.0-5.8) or PNG
- EXIF: Artist=UUID, ImageDescription="Signature: <base64>" (C2PA)
- Safety: Blocks exposed genitalia
- Watermark: Optional "Grok" logo corner
- API docs: https://docs.x.ai/developers/model-capabilities/images/generation
- FSD detection: 72% at z < -2.0
- Reddit subs: r/grok, r/GrokAI, r/GrokImagine
- Reddit reject flairs: Discussion, Meme, Defending AI, Luddite Logic, Sloppost/Fard, + 19 more
- Reddit reject title keywords: 54 patterns (vs, comparison, censored, POV:, generator names, etc.)
- Reddit yield: 11.3% (1,500 scraped → 169 validated after automated + manual review)

### ChatGPT (GPT-Image-1 and GPT-Image-1.5) / DALL-E 3 (partially known)
- FSD detection: 100% (11/11), mean z = -15.56
- Watermark: Rainbow square in corner (DALL-E), C2PA metadata
- Civitai on-site generation: OpenAI's GPT-image-1 (check for model_version_ids)
- Reddit subs: r/ChatGPT, r/dalle, r/OpenAI

### Gemini / Imagen (partially known)
- FSD detection: 90.9% (10/11), mean z = -6.75
- Watermark: SynthID (invisible), possibly visible watermark
- Civitai on-site generation: Imagen 4, Google's Nano Banana (check for model_version_ids)
- X.com: @NanoBanana/media (Nano Banana bot — verify if official Google account before using)
- Reddit subs: r/Gemini, r/GoogleGemini

### Known Civitai's on-site generations:
Alibaba, Qwen, Qwen 2, Alibaba - Tongyi Lab, ZImage, Black Forest Labs, Flux.1, Flux.1 Krea, Flux.1 Kontext, Flux.2, Flux.2 Klein, ByteDance, Seedream, Google, Imagen 4, Nano Banana, OpenAI, OpenAI, Pony Diffusion, Pony Diffusion, Pony Diffusion V7, SDXL Community, Illustrious, NoobAI, Stability AI, Stable Diffusion 1.x, Stable Diffusion XL, xAI, Grok, Other, Chroma, HiDream

## Tool Commands

### Scraping (all config-driven via `--config`)
```bash
# Civitai — prefers on-site generation (model versions), falls back to tool_id
uv run python -m scrapers.civitai --config configs/<generator>.py --max-images N

# Civitai — explicit model version (on-site generation, most trustworthy)
uv run python -m scrapers.civitai --config configs/<generator>.py --model-version 2738377 --max-images N

# Civitai — explicit tool ID (user-uploaded, only if no on-site generation)
uv run python -m scrapers.civitai --config configs/<generator>.py --tool-id 284 --max-images N

# Twitter/X — scrapes bot's media timeline (TWITTER_MEDIA_URL from config)
# Requires cookies.txt (Netscape format)
uv run python -m scrapers.twitter --config configs/<generator>.py --max-images N

# Reddit — reads subreddits, search queries, and post-level filters from config
# Filters: REDDIT_REJECT_FLAIRS, REDDIT_REJECT_TITLE_KEYWORDS, REDDIT_SKIP_SELF_POSTS, REDDIT_ALLOWED_IMAGE_DOMAINS
uv run python -m scrapers.reddit --config configs/<generator>.py --max-images N

# grok.com/imagine — 100% Grok provenance, requires SSO cookies
uv run python -m scrapers.grok_imagine -c configs/grok.py --cookies data/cookies-grok.txt -n 3000

# All scrapers support: --output DIR (default: data/<generator>)
```

### Validation Pipeline
```bash
# Full pipeline (JoyCaption + structural + FSD)
uv run python -m validators.pipeline --config configs/<generator>.py

# With options
uv run python -m validators.pipeline --config configs/<generator>.py --relaxed --skip-fsd
uv run python -m validators.pipeline --config configs/<generator>.py --captions data/grok/captions.json
```

### vLLM (Vision Language Model)
```bash
# Start vLLM on a free GPU (e.g. GPU 3), port 8001
CUDA_VISIBLE_DEVICES=3 uv run vllm serve Qwen/Qwen2.5-VL-7B-Instruct \
  --port 8001 --max-model-len 8192 --trust-remote-code --gpu-memory-utilization 0.5

# Test with curl
curl http://localhost:8001/v1/models

# VLM classify (single images or batch)
uv run python -m validators.vlm_filter --config configs/<generator>.py --dir <staging_dir> --output <output.json>
uv run python -m validators.vlm_filter --config configs/<generator>.py --image <path>
```
Notes:
- Use port 8001 (JoyCaption Ray Serve uses 8000)
- 8192 context recommended (images consume many tokens)
- 50% GPU util leaves room for other workloads on same GPU
- Qwen2.5-VL-7B fits comfortably on 1 H200 at 50% util

### JoyCaption
```bash
# Start Ray Serve (6 replicas, GPUs 0-3)
source .venv/bin/activate
CUDA_VISIBLE_DEVICES=0,1,2,3 python -m validators.serve_joycaption serve \
  --config configs/<generator>.py --gpu 0.5 --replicas 6

# Batch classify (async, 6 parallel workers)
uv run python -m validators.batch_classify --dir <staging_dir> --output <output.json> --concurrency 6

# Or classify via serve_joycaption directly (synchronous)
uv run python -m validators.serve_joycaption classify --dir <staging_dir> --output <output.json>
```

### FSD Scoring
```bash
# FSD is a local dependency — run from this project, not 07-fsd-public
uv run fsd-score --dir /path/to/images/ --weights-dir validators/fsd-weights --csv > results.csv
# Single image:
uv run fsd-score --weights-dir validators/fsd-weights image.jpg
```

## Validator Architecture

```
classify.py          — Config-driven classification logic (shared library)
serve_joycaption.py  — Ray Serve deployment + HTTP client (uses classify.py)
batch_classify.py    — Async batch HTTP client with concurrency control
vlm_filter.py        — Alternative VLM classifier via vLLM (Qwen2.5-VL)
image_validator.py   — Structural validation (pixels, aspect ratio, EXIF, format)
pipeline.py          — Full orchestrator: JoyCaption → structural → FSD → sort
batch_review.py      — HTML contact sheets for manual review
```

## Reusable Code Patterns

### Aspect ratio checker
```python
def matches_known_ratio(w, h, known_ratios, tolerance=0.05):
    """Check if image matches any known generator aspect ratio."""
    img_ratio = w / h
    for rw, rh in known_ratios:
        expected = rw / rh
        if abs(img_ratio - expected) / expected <= tolerance:
            return f"{rw}:{rh}"
    return None
```

### Genital/safety filter (tag-based)
```python
GENITAL_KEYWORDS = ['penis', 'vagina', 'vulva', 'genitals', 'testicle', 'labia', 'clitoris', 'phallus']

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

### CDN filename contamination check
```python
def check_civitai_contamination(manifest_path, existing_files):
    """Find Civitai images from multi-tool workflows."""
    comfy = set()
    with open(manifest_path) as f:
        for row in csv.DictReader(f):
            if row['filename'] in existing_files and 'comfyui' in row['url'].lower():
                comfy.add(row['filename'])
    return comfy
```

## Workflow Checklist

- [ ] Worklog created: `docs/WORKLOG_<datetime>_<generator>.md`
- [ ] Generator profile created in `configs/<generator>.py`
- [ ] Scrapers configured (Civitai model versions, X.com media URL, Reddit subs)
- [ ] Reddit flairs scouted and `REDDIT_REJECT_FLAIRS` populated
- [ ] Reddit title keywords populated in `REDDIT_REJECT_TITLE_KEYWORDS`
- [ ] Small test batch (50 images) scraped and validated
- [ ] JoyCaption Ray Serve running (6 replicas)
- [ ] Full scrape to target count
- [ ] Format + resolution + aspect ratio validation
- [ ] JoyCaption content filter
- [ ] FSD z-score tagging
- [ ] Safety filter (generator-specific blocked content)
- [ ] Civitai multi-tool contamination check
- [ ] Aspect ratio outlier visual scan
- [ ] Manual spot-check (highest z-scores first, Reddit images especially)
- [ ] Metadata CSV rebuilt
- [ ] staging/ and rejected/ cleaned up
- [ ] Worklog finalized with lessons and stats
- [ ] Lessons distilled into `docs/LESSONS_<GENERATOR>.md`
