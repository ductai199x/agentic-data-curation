# Real Video Dataset Taxonomy — vFSD Training

**Target:** 200K clips (initial milestone), stretch to 500K
**Clip duration:** 5s–60s (longer source videos cut into 60s segments)
**Purpose:** Diverse real-world video baseline for video forensic synthetic detector

---

## Dimension 1: Content (what's in the frame)

Most important dimension. No single category should exceed 15% of total.

| ID | Category | Subcategories | Target % | Target clips | Notes |
|----|----------|---------------|----------|-------------|-------|
| C1 | People — casual | walking, sitting, social, candid | 8% | 16K | Common, cap it |
| C2 | People — action | sports, dancing, fitness, fighting | 8% | 16K | High motion, important for temporal |
| C3 | Talking head | interviews, podcasts, vlogs, news anchors, video calls | 8% | 16K | Critical — counters AI talking head generators (HeyGen, Synthesia, D-ID, Kling). Tight framing, chest-up, static camera. High contamination risk (banners, logos, virtual BGs) |
| C4 | Lecture | university lectures, conference talks, classroom recordings, whiteboard sessions | 5% | 10K | Wide shot, lecturer moves/gestures/writes, whiteboard/slides visible. Ultra-clean sources (MIT OCW, Stanford). Long-form → sparse sample. Different framing + motion than talking head |
| C5 | Nature — landscape | mountains, forests, fields, desert, sky | 6% | 12K | Often static/slow — motion diversity |
| C6 | Nature — wildlife | animals in wild, birds, marine life | 4% | 8K | Unpredictable motion patterns |
| C7 | Nature — water | ocean, rivers, rain, waterfalls, underwater | 4% | 8K | Complex fluid dynamics |
| C8 | Walking/biking tour | city walks, bike rides, market walks, nature trails, real-time POV | 7% | 14K | Ultra-clean: no cuts, no overlays, continuous 4K. Sparse sample. Geographic diversity built in |
| C9 | Urban — street | pedestrians, traffic, storefronts, markets | 4% | 8K | Mixed motion, good diversity |
| C10 | Urban — architecture | buildings, interiors, skylines | 3% | 6K | Often static/pan, good for spatial |
| C11 | Vehicles — exterior | cars, bikes, trains, boats, planes | 4% | 8K | Fast motion, tracking |
| C12 | Vehicles — POV | dashcam, cycling POV, cockpit | 4% | 8K | Forward motion, unique perspective |
| C13 | Cooking | home cooking, professional kitchen, outdoor/campfire, recipe demos | 7% | 14K | Hands + food + heat/steam, diverse settings. Complex close-up interactions |
| C14 | Product review | phones, cameras, electronics, fashion, unboxing, hands-on | 5% | 10K | Close-up detail, hands + objects, high contamination risk (overlays, cuts, B-roll) |
| C15 | Animals — domestic | pets, farm animals, zoo | 3% | 6K | Unpredictable motion |
| C16 | Hands & objects | crafts, tools, instruments, writing, repair | 3% | 6K | Fine detail, close-up |
| C17 | Aerial/drone | landscapes, cities, beaches from above | 4% | 8K | Smooth motion, unique angle |
| C18 | Weather & atmosphere | storms, fog, snow, sunrise/sunset, clouds | 3% | 6K | Gradual change, atmospheric |
| C19 | Macro & texture | insects, water drops, fabric, fire, smoke | 3% | 6K | Fine spatial detail |
| C20 | Security camera | parking lots, streets, stores, homes, warehouses, night/IR | 4% | 8K | Fixed elevated angle, low quality/FPS, continuous, no editing. Day + night/IR. AI generators now mimic this style |
| C21 | Indoor — everyday | home, office, classroom, gym, shop | 2% | 4K | Controlled lighting |
| **Total** | | | **100%** | **200K** | |

## Dimension 2: Motion (how things move)

No single motion type should exceed 25% of total.

| ID | Motion type | Description | Target % | Source hints |
|----|------------|-------------|----------|--------------|
| M1 | Static/tripod | Locked-off camera, subject moves | 12% | Landscape, security cam, studio |
| M2 | Handheld — stable | Casual phone/camera, mild shake | 20% | Vloggers, casual content |
| M3 | Handheld — shaky | Running, walking, chaotic | 10% | Action, protests, events |
| M4 | Gimbal/smooth tracking | Stabilized follow shots | 10% | Wedding, cinema, travel |
| M5 | Pan/tilt | Deliberate camera rotation | 10% | Architecture, panoramas |
| M6 | Fast action | Sports, vehicles, impacts | 10% | GoPro, sports channels |
| M7 | Slow motion | 120fps+, temporal stretching | 8% | Phone slo-mo, sports replays |
| M8 | Timelapse/hyperlapse | Compressed time | 5% | Nature, city, construction |
| M9 | Drone/aerial movement | Orbit, flyover, reveal | 8% | DJI, aerial videography |
| M10 | Zoom | Optical or digital zoom during clip | 3% | Wildlife, events, surveillance |
| M11 | Dolly/slide | Linear camera translation | 4% | Cinema, product shots |
| **Total** | | | **100%** | |

## Dimension 3: Camera (what captured it)

No single camera type should exceed 30% of total.

| ID | Camera type | Typical specs | Target % | Source hints |
|----|------------|---------------|----------|--------------|
| K1 | Modern smartphone | 1080p-4K, 30-60fps, H.264/HEVC | 30% | Phone videography, casual |
| K2 | DSLR/mirrorless | 1080p-4K+, 24-60fps, shallow DOF | 15% | Wedding, travel, cinema |
| K3 | Action camera | 1080p-4K, 60-240fps, wide angle | 12% | GoPro, Insta360, sports |
| K4 | Drone | 1080p-4K, 24-60fps, aerial | 10% | DJI, Autel, aerial accounts |
| K5 | Dashcam | 1080p-2K, 30fps, forward-facing | 8% | Dashcam subreddits, YouTube |
| K6 | Webcam/video call | 720p-1080p, 30fps, front-facing | 5% | Podcast recordings, streams |
| K7 | Security/CCTV | 480p-1080p, 15-30fps, fixed | 5% | Security cam compilations |
| K8 | Cinema/professional | 4K+, 24fps, cinema color | 10% | Short films, commercials |
| K9 | Vintage/older phone | 480p-720p, 30fps, older sensors | 5% | Older YouTube uploads |
| **Total** | | | **100%** | |

## Dimension 4: Source / Technical

No single source should exceed 40% of total.

| ID | Source | Compression | Typical codec | Target % |
|----|--------|-------------|---------------|----------|
| S1 | YouTube | Heavy | VP9, AV1 | 35% |
| S2 | Instagram (Reels + video posts) | Heavy | H.264 | 25% |
| S3 | Pexels | Light | H.264, H.265 | 15% |
| S4 | Pixabay | Light | H.264, H.265 | 10% |
| S5 | TikTok | Heavy | H.264 | 10% |
| S6 | Vimeo | Medium | H.264, H.265 | 5% |
| **Total** | | | | **100%** |

---

## Balancing Strategy

These 4 dimensions are **not independent**. A dashcam clip (K5) is always vehicle-POV
content (C9) with forward motion (M2/M6). A drone clip (K4) maps to aerial content (C13)
with drone motion (M9). This is fine — the quotas are **marginal distributions**, not
a 4D grid.

### Clip sampling rule (prevent source video overfitting):

Long source videos must NOT be fully segmented. A 1-hour walking tour cut into 60 clips
creates 60 highly correlated samples (same camera, city, lighting, gait). Instead:

- **Max N clips per source video** (e.g., 3–5 clips from a 1hr video)
- **Evenly spaced** across the video timeline for maximum within-video diversity
- **Skip first/last 2 minutes** (intros, outros, setup)
- **Pick cleanest segments** — skip any segment where JoyCaption flags issues
- **Result:** 14K walking tour clips requires ~3K–5K unique source videos, not 230

This forces diversity at the source level — many unique videos/channels/cameras/locations
rather than dense sampling from a few long videos.

### How to enforce balance:

1. **Source list curation by taxonomy cell.** Don't just find "YouTube channels" — find
   "50 dashcam channels, 30 underwater videographers, 40 slow-motion accounts, ..."
   Each source list explicitly targets underfilled cells.

2. **Track marginal distributions during collection.** After each batch, compute the
   distribution across each dimension. If any category exceeds its cap or falls below
   half its target, adjust the next sourcing batch.

3. **Auto-tagging pipeline:**
   - **Content:** JoyCaption on 3 sampled frames → keyword classification into C1-C16
   - **Motion:** Optical flow magnitude + variance → classify into M1-M11
   - **Camera:** Combination of resolution, FPS, aspect ratio, lens distortion heuristics
   - **Source:** Known from download metadata

4. **Oversample hard-to-fill cells early.** Some cells will be naturally scarce:
   - Underwater (C5 subset): deliberately seek out dive channels
   - Security cam (K7): specific sourcing needed
   - Slow motion (M7): search "slow motion" + "120fps" + "240fps"
   - Timelapse (M8): search "timelapse" + "hyperlapse"

### Natural co-occurrence matrix (expected, not enforced):

```
               K1-Phone  K2-DSLR  K3-Action  K4-Drone  K5-Dash  K7-Security
C1-People        ★★★      ★★       ★          -         -        ★★
C2-Action        ★★       ★        ★★★        -         -        ★
C3-Landscape     ★★       ★★★      ★          ★★★       -        -
C5-Water         ★        ★★       ★★★        ★★        -        -
C9-Vehicle POV   ★        -        ★★         -         ★★★      -
C13-Aerial       -        -        -          ★★★       -        -
M7-Slow-mo       ★★★      ★★       ★★★        -         -        -
M8-Timelapse     ★★       ★★★      ★★         ★★        ★        ★
```

---

## Cleaning Pipeline (per clip)

```
1. Download at ≤1080p (or native if lower). Record max available resolution in metadata.
2. ffprobe → extract duration, resolution, fps, codec, bitrate
3. Reject if: duration < 3s, resolution < 480p, fps < 15
4. Cut to ≤ 60s segments (max 4 clips per source video, evenly spaced, skip first/last 2min)
5. Scene cut detection → reject any clip with cuts or scene transitions
6. Sample 1 frame every 2 seconds
7. JoyCaption each frame → keyword-stop on first reject:
   - REJECT: watermark, logo, text overlay, banner, lower third,
             animated, cartoon, CGI, 3D render, video game,
             screenshot, screen recording, slideshow, montage,
             compilation, intro, outro, subscribe, like and share,
             AI generated, artificial, synthetic,
             green screen, chroma key, virtual background,
             picture-in-picture, split screen, news ticker,
             graphics overlay, infographic
8. Content-address: SHA256[:16] + ext
9. Auto-tag: content category, motion type, camera type (from metadata + CLIP)
10. Append to manifest with taxonomy tags + max available resolution
```

---

## Resolved Decisions

- **Download resolution:** Cap at 1080p (or native if lower). Record highest available
  resolution in metadata so we can selectively re-download at higher res later.
- **Minimum resolution:** 480p — needed for security cam (K7) and vintage phone (K9).
- **Audio:** Preserve — minimal storage cost, enables future audio forensics.
- **TikTok:** Skip — persistent watermark contaminates spatial signal. YouTube + Instagram
  already cover heavy H.264 compression.
- **Geographic diversity:** Light explicit effort — include non-English search terms for
  walking tours, cooking, street scenes. No hard quota.
- **Mixed content clips:** Tag primary + secondary content category.
- **Clips per source video:** Max 4. Evenly spaced across timeline, skip first/last 2min.
- **Scene cuts:** Zero tolerance. Any detected cut/scene transition → reject the clip.
  Use frame-to-frame histogram discontinuity or similar to detect cuts. This ensures
  every clip is a single continuous real-world recording.

## Open Questions

(none)
