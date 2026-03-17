# Lessons from ChatGPT (GPT-Image-1 / 1.5) Curation

Distilled from the March 2026 curation run. 2,725 validated images from Civitai,
Reddit, and Higgsfield. See `WORKLOG_20260314_0335_gpt_image_1.md` for the full timeline.

## Source Viability

| Source | Viability | Notes |
|--------|-----------|-------|
| Civitai on-site gen | **Best provenance, unreliable CDN** | 83.7% of final dataset. model_version_id guaranteed. But 85-97% of CDN URLs return 500. |
| Reddit (date+flair gated) | **Good supplement** | 14% of dataset. Date gate (April 1, 2025+) excludes DALL-E 3 era. Flair gate ("Image - ChatGPT", "GPT-4o") isolates generator. |
| Higgsfield | **Clean but tiny** | 2.3% of dataset. Model-specific galleries (openai_hazel, text2image_gpt). |
| X.com/Twitter | **Dead end** | No official bot. @ChatGPTapp doesn't post generations. |
| Civitai tool_id | **Do not use** | Unreliable provenance — anyone can upload with any tags. |

## Key Findings

### 1. Civitai CDN Purges Are Catastrophic
18K images in API metadata, but only ~15% of v1.5 and ~3% of v1 CDN URLs are alive.
This is permanent, confirmed from multiple IPs. **Lesson**: scrape Civitai early. CDN
availability degrades rapidly with age. If you wait months, most images are gone.

### 2. GPT-Image Has Extreme Non-Photorealistic Usage
65% rejection rate — the highest of any generator we've curated (vs 18% Nano Banana,
~50% Grok Reddit). GPT-Image is uniquely popular for Ghibli-style, anime, illustration,
cartoon, and text-heavy content. Content filtering keywords must be comprehensive.

### 3. Speech Bubbles / Memes Require Explicit Keywords
JoyCaption tags "speech bubbles" but not necessarily "meme". Standard REJECT_KEYWORDS
must include: `speech bubble`, `speech bubbles`, `thought bubble`, `word balloon`,
`dialogue bubble`. These are always reject signals for photorealistic datasets.

### 4. Reject Keywords Must Be Narrow
Tested and reverted: "logo", "icon", "silhouette", "sticker", "badge", "emblem".
These match elements WITHIN photorealistic images (Nike logo on a shoe, silhouette
of a person at sunset, police badge on a uniform). Only use unambiguous non-photo
style descriptors.

### 5. Error-Captioned Images Are a Pipeline Hole
When JoyCaption fails (FileNotFoundError from race conditions), the caption entry
is `{"error": "..."}` with no `caption` or `should_reject` fields. The pipeline
previously treated these as "not rejected" and passed them through. **Fix**: pipeline
now explicitly rejects any entry with an `error` key.

### 6. FSD Detection Rate: 96%
Much higher than Grok (72%) or Nano Banana (33%). GPT-Image artifacts are distinctive
and well-detected by FSD. An earlier micro-sample showed 0% — sample size matters.

### 7. Model Version Annotation
- **Civitai**: model_version_id in flair → exact version (v1 or v1.5)
- **Higgsfield**: gallery name → exact version (openai_hazel=v1.5, text2image_gpt=v1)
- **Reddit**: No reliable signal. Date heuristic possible (before Dec 16, 2025 = likely
  v1, after = possibly v1.5) but not certain since v1 remains available.

### 8. Reddit Date Gating Is Essential
Before April 1, 2025, ChatGPT used DALL-E 3 — a completely different model.
`REDDIT_MIN_CREATED_UTC = 1743465600` (April 1, 2025 00:00 UTC) is the hard boundary.
Without this, the dataset would be contaminated with DALL-E 3 images.

### 9. Concurrent Download Workers + Skip Delay Optimization
4 concurrent CDN workers maximizes throughput when most URLs fail. But workers must
NOT sleep on download delay for skipped (already-downloaded) items — this causes
artificial slowdown when processing large skip-heavy batches.

## Generator Profile Summary

```
Resolutions: 1024x1024, 1536x1024, 1024x1536
Aspect ratios: 1:1, 3:2, 2:3 (only 3 — very tight structural filter)
Formats: PNG (native), JPEG (CDN-recompressed)
Safety blocks: nudity, CSAM, extreme violence, deepfake sexual
C2PA: Present natively but stripped by CDNs
```

## Dataset Summary

| Metric | Value |
|--------|-------|
| Validated images | 2,725 |
| FSD detection rate | 96.0% |
| Source mix | Civitai 83.7%, Reddit 14.0%, Higgsfield 2.3% |
| Model versions | v1.5: 68.9%, v1: 17.1%, Unknown: 14.0% |
| Rejection rate | ~65% |
