# Worklog: ChatGPT (GPT-Image-1 / GPT-Image-1.5) Curation

**Started**: 2026-03-14 03:35 UTC
**Generator**: GPT-Image-1, GPT-Image-1.5 (OpenAI, integrated into ChatGPT)
**Target**: 5-10K validated photorealistic images

## Phase 0: Intake

- User knows Higgsfield has GPT-Image-1.5 (https://higgsfield.ai/gpt-1.5), possibly similar scraping method as nano_banana
- No official bot account on X.com (@ChatGPTapp doesn't post user-requested generations)
- Reddit likely has volume but needs very strict filtering
- Quality bar: photorealistic, strict filtering
- **User corrections**: DALL-E 2/3 ≠ GPT-Image-1/1.5 (different models). Civitai tool_id unreliable. Reddit provenance must be certain.

## Phase 1: Source Research (completed)

### Research Results

**Viable Sources:**
| Source | Model | Volume | Provenance | Format |
|--------|-------|--------|------------|--------|
| Civitai on-site gen | v1 (mvid 1733399) | ~14,000 | Guaranteed | JPEG (CDN) |
| Civitai on-site gen | v1.5 (mvid 2512167) | ~4,100 | Guaranteed | JPEG (CDN) |
| Higgsfield | openai_hazel (v1.5) | 62 | Good | PNG |
| Higgsfield | text2image_gpt (v1) | 22 | Good | JPEG |

**Rejected Sources:**
- **Reddit**: Provenance too uncertain. "ChatGPT" flairs don't distinguish GPT-Image-1 from DALL-E 3. User directive: if we can't confirm provenance, skip it.
- **X.com/Twitter**: No official bot account. Dead end.
- **Civitai tool_id**: Unreliable — anyone can upload with any tags.
- **PromptHero/NightCafe**: Provenance is user-tagged, not verified.

### Generator Profile
- **Resolutions**: 1024x1024, 1536x1024, 1024x1536 (API). v1.5 may have higher res on Civitai.
- **Aspect ratios**: 1:1, 3:2, 2:3 only (very tight — great for structural filtering)
- **Formats**: PNG (default), JPEG, WebP. Civitai CDN serves JPEG.
- **C2PA**: Present but stripped by CDNs/social media
- **Safety**: No nudity, no violence, no CSAM
- **GPT-Image-1**: April 2025, autoregressive (GPT-4o based)
- **GPT-Image-1.5**: December 2025, GPT-5 based, 4x faster, +60% instruction adherence

### Higgsfield Pagination Verification
- Fully paginated `openai_hazel`: 62 items across 2 pages (has_more=False)
- Fully paginated `text2image_gpt`: 22 items across 1 page (has_more=False)
- Confirmed genuinely tiny — GPT-Image not popular on Higgsfield (vs 12,375 for Nano Banana)

## Phase 2: Scraping (in progress)

### Scrapers Launched (2026-03-14 ~04:05 UTC)
- **Civitai** (PID 4125737): `--config configs/chatgpt.py --max-images 20000` — both model versions
- **Higgsfield** (PID 4126127): `--config configs/chatgpt.py --max-images 200` — 84 images expected

### Config Created
- `configs/chatgpt.py` — GPT-Image-1 + 1.5 profile
- Only 3 aspect ratios (very tight structural filtering)
- Reddit intentionally empty — provenance too uncertain
- Civitai tool_id = None (unreliable)

### Notes
- Civitai estimated runtime: ~50 hours (18K images × ~10s/image with delays)
- ~7-10% of Civitai entries may be mp4 videos (filtered by scraper)
- Running caption+pipeline sweeps every 15-20 min as images arrive
