# Lessons from FLUX.2 Curation

Distilled from the March 2026 curation run. 1,832 validated images from Civitai.
See `WORKLOG_20260316_0100_flux2.md` for timeline.

## Source Viability

| Source | Viability | Notes |
|--------|-----------|-------|
| Civitai on-site gen | **Only viable source** | 100% of dataset. Dev gallery deepest (~3K). |
| Higgsfield | **All rejected structurally** | 301 downloads, 0 passed (bad aspect ratios from input_images mixing). |
| Tensor.Art | **Cloudflare blocked** | Could not capture signing headers. ~269 Klein posts exist. |
| AIGCArena | **Not tested** | Likely has max/pro but requires browser context. Small volume. |
| OpenArt | **Can't distinguish FLUX.1 vs FLUX.2** | Broken ai_model filter. |
| Yodayo | **No FLUX.2 models** | 0 content. |

## Key Findings

### 1. FLUX.2 Has Much Less Community Content Than FLUX.1
FLUX.1 had 20M+ on-site generations on Civitai. FLUX.2 has ~157K total — 100x less.
Galleries exhausted quickly: Dev at 3,109, Pro at 1,103, Max at 444, Flex at 524.
This makes sense — FLUX.2 is newer (Nov 2025 vs Aug 2024) and the 32B model is harder
to run locally.

### 2. No Official BFL Model Entry on Civitai
Unlike FLUX.1 (model_id=618692 by Black Forest Labs), FLUX.2's model_id=2165902 is
by "theally" (community member), not official. This caused confusion during research —
one agent initially reported 0 on-site generations because it was looking at user-uploaded
checkpoint models (2165923) instead of the correct model (2165902).

### 3. FSD Detection: 86.3%
Mean z-score: -8.96 (vs FLUX.1's -7.07). Slightly higher detection than FLUX.1 despite
being the same architectural family (MMDiT). The new 32B architecture with different VAE
produces slightly more detectable artifacts.

### 4. Higgsfield FLUX.2 Is All input_images
All 301 Higgsfield flux_2 posts have non-standard aspect ratios from input_images mixing
(image-to-image generation). These fail structural validation and have contamination risk
(real content mixed in). Not usable for photorealistic dataset.

### 5. Safety Filters Reduce NSFW
FLUX.2 has built-in safety_tolerance filters (unlike FLUX.1 open-weight). On Civitai
on-site gen, this means less NSFW content compared to FLUX.1 (which had 42% NSFW-tagged).

## Dataset Summary

| Metric | Value |
|--------|-------|
| Validated images | 1,832 |
| FSD detection rate | 86.3% |
| Mean z-score | -8.96 |
| Source mix | Civitai 100% |
| Model versions | Dev 83.5%, Pro 16.5% |
| Total downloads | 5,714 |
| Pass rate | 32% |
