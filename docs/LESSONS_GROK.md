# Lessons Learned: Grok Data Curation

> Collected ~1,713 validated Grok images across multiple sessions (2026-03-11/12/13).
> Manual review of 325 Reddit images rejected 156 (48%) — memes, screenshots, advocacy, other generators.
> Sources: Twitter (@grok), grok.com/imagine API, Civitai, Reddit.
> Only scrape official @grok account — third-party bot accounts have unverified provenance.

## 1. Sources (Best → Worst)

| Source | Quality | Auth | Notes |
|--------|---------|------|-------|
| **Civitai** | Full-res PNG, guaranteed AI | None | Best forensic quality. On-site generation (model_version_id) is most trustworthy — no multi-tool contamination. Tool_id fallback includes multi-tool workflows (e.g. Grok+ComfyUI); skipped if on-site gen exists. |
| **X.com** | Full-res orig via gallery-dl | cookies.txt (Netscape format, expires ~2 weeks) | Scrape `@grok/media` timeline — every image IS a Grok generation. `name=orig` URLs. Sometimes downloads MP4 as .jpg — verify with PIL. |
| **Reddit** | Re-compressed JPEG (avg_q≈29) | None (public JSON API) | Only PNGs survive intact. ~10% of r/grok is actual AI art; rest is screenshots/memes/text. |

| **grok.com/imagine** | Full-res PNG, 100% Grok | cookies.txt (Netscape, SSO JWT) | Best provenance — xAI's own platform. REST API: `POST /rest/media/post/list` with `MEDIA_POST_SOURCE_PUBLIC` filter. Paginated via `nextCursor`. 40 posts/page, returns direct CDN URLs + prompts + resolution. |

**Dead ends**: Brave Search for grok.com/imagine UUIDs (429 rate limit instantly), DuckDuckGo (0 results for grok.com), Nitter (dead), generic AI art subs (cross-generator contamination), `from:grok filter:images` search (returns 0/404 after 14min).

**Twitter pagination cap**: `@grok/media` hard-caps at ~616 images (server-side GraphQL limit, exhaustively tested). Despite 8.6M media items on the account, the `UserMedia` endpoint stops paginating after 3 pages. Not bypassable via gallery-dl config (tested: replies, timeline, retweets, quoted, limit). No known workaround — do NOT scrape third-party bot accounts (unverified provenance).

**Reddit search**: Use exact phrases (`"made with grok"`, `"grok aurora"`). Scrape dedicated subs (`r/grok`, `r/GrokAI`, `r/GrokImagine`) + flair-based search (`flair:Imagine subreddit:grok`). Broad keyword search returns too much noise.

**Reddit post-level filtering** (implemented in `scrapers/reddit.py`, config-driven):
- **Flair rejection**: Skip posts with flairs like Discussion, Meme, Defending AI, Luddite Logic, Sloppost/Fard, News, etc. (24 rejected flairs in `REDDIT_REJECT_FLAIRS`). Catches 48% of noise alone.
- **Title keyword rejection**: Skip posts with "vs", "comparison", "censored", "banned", "POV:", "when you", "midjourney", "goodbye", etc. (54 keywords in `REDDIT_REJECT_TITLE_KEYWORDS`). Catches an additional 8%.
- **Self-post skip**: Text-only discussion threads have no direct image content.
- **Domain allowlist**: Only download from i.redd.it, preview.redd.it, i.imgur.com — skip external links.
- Combined: **57% of Reddit posts would be pre-filtered** before download (retroactive analysis of 1,500 posts).

**Reddit manual review stats** (325 images that passed automated validation):
- 48% rejected manually — memes/text overlays (35%), other generator watermarks (10%), screenshots (16%), celebrity deepfakes (10%), real photos (6%), comparisons (6%), non-AI fan art (6%), advocacy (11%)
- Top contamination: memes about AI censorship/moderation, jackhammer/squirrel prompt from multiple generators (Seedream, GPT Image, Kling, Qwen), "GOODBYE GROK" / "BRING BACK OLD GROK" signs, political deepfakes, newspaper/screenshot photos

**X.com strategy**: Scrape `@grok/media` (bot's media timeline) — every image posted by @grok is a generated reply. Do NOT use search queries: `"@grok generate" filter:images` matches the user's request tweet (with their reference photos), and `"made with grok"` etc. are self-reported and unreliable. Uses gallery-dl Python API with `ratelimit: "abort"` for partial results.

## 2. Validation Pipeline

No single filter catches everything. Use all stages in order:

| Stage | Catches | Notes |
|-------|---------|-------|
| Format check | GIFs, MP4s mislabeled as .jpg, corrupt files | gallery-dl downloads X.com videos as .jpg |
| Pixel count (800k–5M) | Thumbnails, real DSLR uploads | Don't enumerate resolutions — too many aspect ratios × tiers |
| Aspect ratio (15 known, ±5%) | Screenshots, composites | From [xAI API docs](https://docs.x.ai/developers/model-capabilities/images/generation#aspect-ratio) + observed 11:6 from Twitter |
| JoyCaption booru tags | Screenshots, memes, charts, comics, anime | Use booru tag mode, not descriptive captions |
| JoyCaption quality | Blurry/compressed images | Low yield (5/2001) but cheap |
| FSD z-score **tag only** | Flags likely-real photos | Don't filter — 28% of real Grok images fool FSD |
| Booru tag keyword filter | @username watermarks, non-AI content | High false-positive rate — must spot-check |
| Manual spot-check | Everything else | ~15 min per 50 images |

## 3. JoyCaption

- **Booru tag mode** (`"Write a list of Booru-like tags for this image."`) is reliable and structured. Descriptive captions cause ~25% false reject rate from words like "painting" in background descriptions.
- **6 parallel replicas** on Ray Serve with `ThreadPoolExecutor(max_workers=6)` — always parallelize.
- **Tag filter false positives**: "door handle"/"shower handle" match "handle"; "brazzers watermark"/"metart watermark" are fake watermarks Grok adds to AI images (keep!). Use word-boundary regex (`\b`).
- **Non-deterministic** at temperature=0.6 — bracket classification sometimes missing. Must have keyword fallback. Multi-value brackets like `[line drawing, cartoon]` need list parsing.

## 4. FSD Detector

- **Tag, don't filter.** 28% of genuine Grok AI images score z > -2.0 (FSD calls them "real").
- **Photorealistic selfies/portraits** fool FSD the most (z up to +0.43 for confirmed AI).
- **Recompression weakens signal** — Reddit JPEGs: z ≈ -0.3 to -2.0 vs uncompressed: z < -4.
- **z > -0.15** is a reasonable hard-filter threshold for "almost certainly real photo".
- **Source provenance > FSD** for borderline cases — if it came from Civitai or a "@grok make" tweet, it's AI regardless of z-score.

## 5. Process

- **Spot-check before batch runs** — test 5-10 known problematic cases first. Saves hours.
- **Content-addressed storage** (SHA-256 prefix) — zero duplicates across 3 sources.
- **Multi-stage filtering is necessary** — each stage catches different contamination.
- **The tricky zone is photorealistic selfies** — AI selfies with phones, bathrooms, Instagram overlays look identical to real. Source provenance is the strongest signal.
- **Non-Grok AI contamination** — Seedream, Midjourney appear in Grok discussions. Look for other generators' watermarks (DALL-E rainbow square, NightCafe, clideo.com).
- **Aspect ratio / pixel count outlier scan** — Grok outputs at fixed ratios and pixel counts. Filter images that don't match any known Grok ratio (±5%) or fall outside 800k–5M pixels, then visually inspect. This catches: real photos, screenshots, other generators, UI captures, composites. Found 25 removals out of 42 outliers in one pass.
- **Civitai multi-tool contamination** — Civitai `tool_id=284` returns images where Grok is *one of* the tools, not necessarily the generator. ComfyUI workflows using diffusion checkpoints (Z Image Turbo, LoRAs) show up. Check CDN filenames for `ComfyUI_*` and post metadata for non-Grok resources.
- **Grok safety filter = provenance signal** — Grok blocks exposed genitalia. Images tagged with genital content are almost certainly not pure Grok output (either jailbroken, post-processed, or from another generator).
- **Word boundary matching** — `"graph"` matches `"photograph"`. Always use `\b` regex.
- **Qwen 3.5 (text-only LLM) can't classify images** — even from booru tag descriptions, it produces garbage. Only useful for text processing tasks.

## 6. Grok Generator Profile

```
Format:      JPEG (avg_q ≈ 1.0–5.8) or PNG
Pixel count: ~915k (1k tier), ~4M (2k tier, TBD)
Aspects:     1:1, 16:9, 9:16, 4:3, 3:4, 3:2, 2:3, 2:1, 1:2, 11:6, 6:11, 19.5:9, 9:19.5, 20:9, 9:20
EXIF:        Some have Artist=UUID + Signature=base64 (C2PA). No camera EXIF.
Watermark:   Optional Grok logo in corner
API docs:    https://docs.x.ai/developers/model-capabilities/images/generation
```

## 7. Reddit Filtering (Lesson: Pre-filter Before Download)

Reddit is the noisiest source by far. Of ~1,500 Reddit posts scraped for Grok:
- Only ~10% contained actual Grok-generated images
- 48% of images that passed automated validation were still memes/screenshots/advocacy
- Manual review of ALL Reddit images was required

**Solution**: Config-driven post-level filtering in the scraper itself (`REDDIT_REJECT_FLAIRS`,
`REDDIT_REJECT_TITLE_KEYWORDS`, `REDDIT_ALLOWED_IMAGE_DOMAINS`, `REDDIT_SKIP_SELF_POSTS`).
Retroactive analysis shows this would pre-filter 57% of posts before download.

**Common Reddit contamination categories** (by frequency):
1. Memes with text overlays (AI advocacy, censorship drama, "POV:" memes)
2. Screenshots (app UI, social media, Grok chat interface, newspaper clippings)
3. Other generator watermarks (Seedream, GPT Image, Kling Kolors, Qwen Image, Nano Banana)
4. Celebrity deepfakes / political memes
5. Comparison images (side-by-side generator outputs)
6. Real photos (selfies, landscapes, historical photos)
7. Non-AI fan art / hand-drawn art

**Rule of thumb**: Only flairs like "Imagine", "AI ART", "Grok Art" contain actual image showcases.
Everything else (Discussion, Defending AI, Luddite Logic, Sloppost/Fard, News) is noise.

## 8. Final Dataset Stats (v3)

```
Total validated:  1,713 images (after automated + manual review)
Sources:          Twitter 698 (40.7%), grok.com/imagine 600 (35.0%),
                  Reddit 169 (9.9%), Civitai 184 (10.7%)
Non-Reddit:       90.1% (target was 80-85%)
Formats:          JPEG (~75%), PNG (~25%)
Total scraped:    3,682 → 1,713 passed all validation (46.5% pass rate)
Reddit yield:     1,500 scraped → 169 validated (11.3% pass rate)
```
