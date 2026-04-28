# Project Refactor Plan — Option A (`curate` + `generate` + `shared`)

**Goal:** end the image/video naming asymmetry, give every module a clear home, expose two top-level CLIs (`curate`, `generate`).

**Scope:** ~80 imports across 60+ files, 35 config files, 4 packages + workflows + tests + docs. ~6 hours of focused work.

**Strategy:** small atomic phases. Smoke-test after every phase. Each phase = one commit so we can `git revert` if anything breaks.

---

## Final target layout

```
curate/                             # ALL dataset curation
  __init__.py
  cli.py                          # `curate <subcmd>`
  images/
    __init__.py
    scrapers/
      __init__.py
      base.py
      civitai.py, civitai_simple.py, twitter.py, reddit.py
      instagram.py, midjourney.py
      grok_imagine.py, higgsfield.py, openart.py, recraft.py
      tensorart.py, yodayo.py, freepik.py, aigcarena.py
    validators/
      __init__.py
      pipeline.py
      image_validator.py, border_detector.py, classify.py
      serve_joycaption.py, batch_classify.py
      vlm_filter.py, split_grids.py
      batch_review.py                 # candidate for deletion
  videos/
    __init__.py
    scrapers/
      __init__.py
      instagram.py                    # was video/instagram.py
      youtube.py                      # was video/youtube.py
      sora.py                         # was scrapers/sora.py
    validate.py                       # was video/process.py
    download.py, discover.py, screen.py
    validate_channels.py
    merge_yt_manifests.py
    backfill_orphan_manifest.py
    scene_detect.py, cutter.py
    content_filter.py, watermark_detect.py
    quality_filter.py, quality_sweep.py
    metadata.py
    rate_limiter.py

generate/                           # was video_gen/
  __init__.py
  cli.py                          # `generate <subcmd>`
  comfy_batch_run.py
  comfy_config.py
  comfy_spawn.py
  workflows/                      # 15 per-model files
    __init__.py, _aspect.py
    wan22.py, wan21_flf.py
    cogvideox_i2v.py
    hunyuan_video_1_5_i2v.py, hunyuan_video_i2v.py
    ltx_i2v.py
    hailuo02_i2v.py, kling2_i2v.py, kling26_i2v.py
    luma_ray2_i2v.py, runway_gen4_i2v.py
    sora2_i2v.py, veo3_i2v.py
  extract_frames.py
  taxonomy.py, taxonomy_label.py, diversity_rank.py
  clean_captions.py, rewrite_captions.py
  build_dataset_metadata.py
  calibrate_credits.py
  interpolate_fps.py

shared/                             # cross-cutting utilities
  __init__.py
  clip_utils.py                   # is_source_clip
  manifest.py                     # ClipJob, manifest field constants
  loaders.py                      # load_captions, load_ranking
  shard.py                        # shard splitting helpers
  fs.py                           # extract_frame, list_clips, etc.

configs/                            # split by purpose
  __init__.py
  curate/
    __init__.py
    images/                       # 11 image scrape configs
      grok.py, flux1.py, flux2.py, midjourney_v7.py, soul2.py
      recraft_3_4.py, gpt_image_1.py, nano_banana_1_2.py
      seedream4.py, instagram_ai_influencer.py, sora.py
    videos/                       # 3 real-video ingest configs
      youtube.py                    # was youtube_real_video.py
      instagram.py                  # was instagram_real_video.py
      instagram_wave2.py            # was instagram_real_video_wave2.py
  generate/                       # 21 fake-video gen configs
    wan22_instagram.py, wan22_youtube.py
    wan21_flf_instagram.py, wan21_flf_youtube.py
    hunyuan_video_instagram.py, hunyuan_video_youtube.py
    cogvideox_instagram.py, cogvideox_youtube.py, cogvideox_smoketest.py
    ltx_instagram.py, ltx_youtube.py
    _smoke_hy15.py
    commercial_pilots.py
    hailuo02_instagram_pilot.py, kling2_instagram_pilot.py
    luma_ray2_instagram_pilot.py, runway_gen4_instagram_pilot.py
    sora2_instagram_pilot.py, veo3_instagram_pilot.py

data/                               # unchanged (output trees)
docs/                               # this doc + LESSONS_*.md + WORKLOG_*.md
scripts/                            # entry points + sync + stats
  launch.sh, launch_interpolate.sh, playwright-mcp.sh, sync_data.sh
  stats.py                        # eventually moves to curate/cli.py subcommand
  build_all_metadata.py           # moves to curate/cli.py subcommand
  regen_stretched.py              # moves to generate/cli.py subcommand
  youtube_standalone_downloader.py  # keep — multi-machine deploy artifact

tests/                              # pytest-compatible tests
third_party/                        # vendored deps
```

---

## Pre-flight (Phase 0)

**Hard gates before starting:**

1. **Pair 2 must finish first.** Hunyuan + CogVideoX YT round-3 is in-flight using `salmonn_captions_cleaned.json` + `configs.hunyuan_video_youtube` + `configs.cogvideox_youtube`. Renaming any of those mid-run is risky. **ETA: ~9h** (check before starting any phase).

2. **Working tree clean.** `git status` should be clean before each phase.

3. **Test-anchor command works:** `uv run python -c "from video_gen.common import is_source_clip; print('ok')"` — used to verify Phase 1.

4. **Snapshot current shape:**
   ```bash
   git ls-tree -r HEAD --name-only | grep -E "\.(py|sh|md)$" > /tmp/refactor_files_before.txt
   ```

5. **Branch:** `git checkout -b refactor/option-a`

---

## Phase 1 — Promote `video_gen/common.py` to top-level `shared/`

**Goal:** decouple cross-cutting helpers from `video_gen/`. No file deletions yet; old path still works via re-export.

**Risk:** LOW. Pure additive. Won't break in-flight Pair 2 (workers have already imported old path).

### Steps
1. `mkdir -p shared` and add `shared/__init__.py`.
2. Split `video_gen/common.py` into thematic modules:
   - `shared/clip_utils.py` — `is_source_clip`, `VIDEO_EXTS`, `list_clips`, `extract_frame`, `extract_last_frame`, `_resize_to_fit`.
   - `shared/manifest.py` — `ClipJob`, `MANIFEST_FIELDS`.
   - `shared/loaders.py` — `load_captions`, `load_ranking`, `build_jobs`.
   - `shared/shard.py` — `shard_jobs`, `load_processed`.
3. Replace `video_gen/common.py` content with re-exports:
   ```python
   from shared.clip_utils import *  # noqa
   from shared.manifest import *    # noqa
   from shared.loaders import *     # noqa
   from shared.shard import *       # noqa
   ```
   This keeps the old import path working as a back-compat shim.

### Tests
```bash
# Each must pass:
uv run python -c "from shared.clip_utils import is_source_clip, list_clips, VIDEO_EXTS; print('ok')"
uv run python -c "from shared.manifest import ClipJob, MANIFEST_FIELDS; print('ok')"
uv run python -c "from shared.loaders import load_captions, build_jobs, load_ranking; print('ok')"
uv run python -c "from video_gen.common import is_source_clip, ClipJob; print('shim ok')"
# Smoke run:
uv run python -m video_gen.build_dataset_metadata --root data/videos/fake --workers 8 2>&1 | tail -5
```

**Commit message:** `refactor(shared): promote video_gen.common to top-level shared/ package (back-compat shim retained)`

---

## Phase 2 — Reorganize `configs/` directory

**Goal:** split the 35-file flat `configs/` into `configs.curate.images`, `configs.curate.videos`, `configs.generate`.

**Risk:** MEDIUM. `COMFY_CONFIG=configs.X` strings in `scripts/launch.sh` and Makefile must be updated. Configs are dynamically imported by string, so any miss causes runtime failures.

### Steps
1. `git mv` files into new sub-dirs:
   ```bash
   mkdir -p configs/curate/images configs/curate/videos configs/generate
   touch configs/curate/__init__.py configs/curate/images/__init__.py configs/curate/videos/__init__.py configs/generate/__init__.py
   # 11 image configs
   git mv configs/{grok,flux1,flux2,midjourney_v7,soul2,recraft_3_4,gpt_image_1,nano_banana_1_2,seedream4,instagram_ai_influencer,sora}.py configs/curate/images/
   # 3 real-video configs (with rename)
   git mv configs/youtube_real_video.py configs/curate/videos/youtube.py
   git mv configs/instagram_real_video.py configs/curate/videos/instagram.py
   git mv configs/instagram_real_video_wave2.py configs/curate/videos/instagram_wave2.py
   # 21 generate configs
   git mv configs/{wan22_instagram,wan22_youtube,wan21_flf_instagram,wan21_flf_youtube,hunyuan_video_instagram,hunyuan_video_youtube,cogvideox_instagram,cogvideox_youtube,cogvideox_smoketest,ltx_instagram,ltx_youtube,_smoke_hy15,commercial_pilots,hailuo02_instagram_pilot,kling2_instagram_pilot,luma_ray2_instagram_pilot,runway_gen4_instagram_pilot,sora2_instagram_pilot,veo3_instagram_pilot,instagram_real}.py configs/generate/
   ```

   Note: `configs/instagram_real.py` is an image config — verify before move. Same for any ambiguous file.

2. Update import paths in `scrapers/`, `validators/`, `video/`, `video_gen/`:
   ```bash
   grep -rln "from configs\b\|from configs\." --include="*.py" .
   # All `from configs.<name>` → check if name is correct after move
   # Most are like `configs.grok` → `configs.curate.images.grok`
   ```

3. Update `scripts/launch.sh`:
   - `COMFY_CONFIG=configs.wan22_instagram` → `COMFY_CONFIG=configs.generate.wan22_instagram`
   - Same for all 21 generate configs.

4. Update `Makefile` if it has any config refs.

5. Update `docs/` references.

### Tests
```bash
# Every config must still load:
uv run python -c "
from importlib import import_module
import os
for root, _, files in os.walk('configs'):
    for f in files:
        if f.endswith('.py') and f != '__init__.py':
            mod = (root + '/' + f[:-3]).replace('/', '.').lstrip('.')
            try:
                m = import_module(mod)
                print(f'OK  {mod}')
            except Exception as e:
                print(f'FAIL {mod}: {e}')
                exit(1)
"
# Dry-run a launch.sh status (should not actually start):
COMFY_CONFIG=configs.generate.wan22_instagram bash scripts/launch.sh status
```

**Commit message:** `refactor(configs): split into configs/curate/{images,videos} and configs/generate`

---

## Phase 3 — Move `video/` → `curate/videos/`

**Goal:** real-video ingestion lives under `curate/videos/`. Rename `process.py` → `validate.py` (matches what it does).

**Risk:** MEDIUM-HIGH. Many imports from `video.X` to update. `video/instagram.py` and `video/youtube.py` are scraper-shaped, move to `curate/videos/scrapers/`. **Don't run during in-flight Pair 2** (uses no `video.*` modules though, so technically safe — but easier to wait).

### Steps
1. Create new tree:
   ```bash
   mkdir -p curate/videos/scrapers
   touch curate/__init__.py curate/videos/__init__.py curate/videos/scrapers/__init__.py
   ```

2. Move scrapers:
   ```bash
   git mv video/instagram.py curate/videos/scrapers/instagram.py
   git mv video/youtube.py curate/videos/scrapers/youtube.py
   git mv scrapers/sora.py curate/videos/scrapers/sora.py
   ```

3. Move + rename validation pipeline:
   ```bash
   git mv video/process.py curate/videos/validate.py
   ```

4. Move all other `video/` files:
   ```bash
   git mv video/download.py curate/videos/
   git mv video/discover.py curate/videos/
   git mv video/screen.py curate/videos/
   git mv video/validate_channels.py curate/videos/
   git mv video/merge_yt_manifests.py curate/videos/
   git mv video/backfill_orphan_manifest.py curate/videos/
   git mv video/scene_detect.py curate/videos/
   git mv video/cutter.py curate/videos/
   git mv video/content_filter.py curate/videos/
   git mv video/watermark_detect.py curate/videos/
   git mv video/quality_filter.py curate/videos/
   git mv video/quality_sweep.py curate/videos/
   git mv video/metadata.py curate/videos/
   git mv video/rate_limiter.py curate/videos/
   ```

5. Remove empty `video/` and `scrapers/` dirs (if scrapers/ is now image-only — see Phase 4).

6. Find + replace imports across the repo:
   ```bash
   # Replace import paths
   grep -rln "from video\." --include="*.py" .
   # Each occurrence: from video.X → from curate.videos.X
   #                  from video.process → from curate.videos.validate
   #                  from video.instagram → from curate.videos.scrapers.instagram
   #                  from video.youtube → from curate.videos.scrapers.youtube
   grep -rln "from scrapers.sora" --include="*.py" .
   #                  → from curate.videos.scrapers.sora
   ```

7. Update `scripts/launch.sh` if it invokes `python -m video.process` (etc.).

8. Update `Makefile`, docs, memory files.

### Tests
```bash
# Imports
uv run python -c "from curate.videos.validate import process_directory; print('ok')"
uv run python -c "from curate.videos.scrapers.instagram import *; print('ok')"
uv run python -c "from curate.videos.scrapers.youtube import *; print('ok')"
uv run python -c "from curate.videos.scrapers.sora import *; print('ok')"
uv run python -c "from curate.videos.quality_sweep import *; print('ok')"
# Help works:
uv run python -m curate.videos.validate --help | head
uv run python -m curate.videos.quality_sweep --help | head
# Smoke a dry-run:
uv run python -m curate.videos.validate --config configs.curate.videos.youtube --dry-run 2>&1 | tail
```

**Commit message:** `refactor(curate/videos): move video/ → curate/videos/ + rename process.py → validate.py`

---

## Phase 4 — Move `scrapers/` + `validators/` → `curate/images/`

**Goal:** image curation lives under `curate/images/`.

**Risk:** MEDIUM. Many image scraper invocations use `python -m scrapers.X`. Update Make targets + docs.

### Steps
1. Move:
   ```bash
   mkdir -p curate/images/scrapers curate/images/validators
   touch curate/images/__init__.py curate/images/scrapers/__init__.py curate/images/validators/__init__.py

   git mv scrapers/*.py curate/images/scrapers/
   rmdir scrapers/

   git mv validators/*.py curate/images/validators/
   rmdir validators/
   ```

2. Update imports:
   ```bash
   grep -rln "from scrapers\.\|from validators\." --include="*.py" .
   # from scrapers.X → from curate.images.scrapers.X
   # from validators.X → from curate.images.validators.X
   ```

3. Update `scripts/sync_data.sh`, `Makefile`, docs.

### Tests
```bash
uv run python -c "from curate.images.scrapers.base import BaseScraper; print('ok')"
uv run python -c "from curate.images.scrapers.civitai import *; print('ok')"
uv run python -c "from curate.images.validators.pipeline import *; print('ok')"
uv run python -c "from curate.images.validators.classify import *; print('ok')"
# Help works:
uv run python -m curate.images.validators.pipeline --help | head
uv run python -m curate.images.scrapers.civitai --help | head
```

**Commit message:** `refactor(curate/images): move scrapers/ and validators/ → curate/images/`

---

## Phase 5 — Rename `video_gen/` → `generate/`

**Goal:** clearer name; matches CLI design.

**Risk:** HIGH if Pair 2 still running. Pair 2 workers have `video_gen.comfy_batch_run` loaded in memory; mid-run rename of the **module** is safe (Python doesn't re-import) but starting NEW workers requires updated `scripts/launch.sh`. Wait for Pair 2 to fully drain.

### Steps
1. Move:
   ```bash
   git mv video_gen generate
   ```

2. Update imports:
   ```bash
   grep -rln "from video_gen\.\|video_gen\." --include="*.py" .
   # from video_gen.X → from generate.X
   # video_gen.workflows.X → generate.workflows.X
   ```

3. Update `workflow_module` strings in all 21 generate configs:
   ```python
   workflow_module="video_gen.workflows.wan22"  →  workflow_module="generate.workflows.wan22"
   ```
   (Done by sed; do it carefully because configs are imported as strings.)

4. Update `scripts/launch.sh` and `scripts/launch_interpolate.sh`:
   ```
   python -m video_gen.comfy_batch_run  →  python -m generate.comfy_batch_run
   python -m video_gen.interpolate_fps  →  python -m generate.interpolate_fps
   ```

5. Remove the back-compat shim added in Phase 1 (`video_gen/common.py` no longer needed).

6. Update `pyproject.toml` if it lists `video_gen` as a package.

### Tests
```bash
uv run python -c "from generate.comfy_batch_run import main; print('ok')"
uv run python -c "from generate.workflows.wan22 import build_workflow; print('ok')"
uv run python -c "from generate.workflows._aspect import pick_dims; print('ok')"
uv run python -c "from generate.interpolate_fps import main; print('ok')"
uv run python -c "from generate.build_dataset_metadata import main; print('ok')"
# Smoke launch (verify workflow_module strings resolve):
COMFY_CONFIG=configs.generate.wan22_instagram bash scripts/launch.sh status
# Full smoke: kick off 1 clip
uv run python -m generate.build_dataset_metadata --root data/videos/fake --workers 8 2>&1 | tail -5
```

**Commit message:** `refactor(generate): rename video_gen/ → generate/`

---

## Phase 6 — Add `curate/cli.py` + `generate/cli.py` (top-level CLIs)

**Goal:** unify all CLI entry points behind `curate <subcmd>` and `generate <subcmd>`.

**Risk:** LOW (additive). Old `python -m X.Y.Z` invocations still work.

### Steps
1. `curate/cli.py`:
   ```python
   import click
   from curate.images.scrapers import civitai, twitter, reddit, instagram, midjourney, ...
   from curate.images.validators import pipeline as validate_images
   from curate.videos import validate as validate_videos
   from curate.videos import download as download_videos
   ...

   @click.group()
   def main():
       """Image + real-video dataset curation."""

   @main.group()
   def images():
       """Image dataset curation."""

   images.add_command(civitai.main, name="scrape-civitai")
   images.add_command(validate_images.main, name="validate")
   ...

   @main.group()
   def videos():
       """Real-video dataset ingestion."""
   videos.add_command(download_videos.main, name="download")
   videos.add_command(validate_videos.main, name="validate")
   ```

2. Same shape for `generate/cli.py`.

3. Add to `pyproject.toml`:
   ```toml
   [project.scripts]
   curate = "curate.cli:main"
   generate = "generate.cli:main"
   ```

4. `uv pip install -e .` to register the entry points.

### Tests
```bash
curate --help
generate --help
curate images --help
curate videos --help
generate run --help                              # if defined
# Old paths still work:
uv run python -m curate.images.validators.pipeline --help
```

**Commit message:** `feat(cli): add curate and generate top-level CLIs`

---

## Phase 7 — Caption + manifest file renames

**Pre-req:** Pair 2 finished (not just shards exited — confirm `pgrep` shows zero workers and metadata.csv has been rebuilt).

### Steps
1. Rename data files:
   ```bash
   for src in youtube instagram; do
     mv "data/videos/real/$src/captions.json" "data/videos/real/$src/validation_captions.json"
     mv "data/videos/real/$src/salmonn_captions_cleaned.json" "data/videos/real/$src/video_captions.json"
     mv "data/videos/real/$src/process_manifest.csv" "data/videos/real/$src/validation_manifest.csv"
   done
   ```

2. Update `curate/videos/validate.py` (was process.py):
   - `captions.json` → `validation_captions.json`
   - `captions_shard{shard_id}.json` → `validation_captions_shard{shard_id}.json`
   - `process_manifest.csv` → `validation_manifest.csv`
   - `process_manifest_shard*.csv` → `validation_manifest_shard*.csv`

3. Update **15 generate configs** to point `captions_path=` at `video_captions.json`.

4. Update `generate/build_dataset_metadata.py:_load_source_captions()` path.

5. Update `generate/rewrite_captions.py` and `generate/taxonomy_label.py` docstrings.

6. Update CLAUDE.md, LESSONS_*.md, WORKLOG_*.md.

### Tests
```bash
# Verify each renamed file exists and is non-zero:
for src in youtube instagram; do
  for f in validation_captions.json video_captions.json validation_manifest.csv; do
    p="data/videos/real/$src/$f"
    [ -s "$p" ] && echo "OK  $p" || echo "MISSING $p"
  done
done

# Verify code finds them:
uv run python -c "
from generate.build_dataset_metadata import _load_source_captions
caps = _load_source_captions('youtube')
assert len(caps) > 20000, f'expected ~24K, got {len(caps)}'
print(f'youtube captions: {len(caps)} entries')
"

# Smoke a config load:
uv run python -c "
from configs.generate import wan22_youtube
assert 'video_captions.json' in str(wan22_youtube.CONFIG.captions_path)
print('config path updated correctly')
"
```

**Commit message:** `refactor(data): rename caption files for clarity (validation_captions, video_captions, validation_manifest)`

---

## Phase 8 — Move scripts/ utilities into CLIs (optional polish)

- `scripts/stats.py` → `curate.cli:stats` subcommand
- `scripts/build_all_metadata.py` → `curate.cli:build-metadata` subcommand
- `scripts/regen_stretched.py` → `generate.cli:regen-stretched` subcommand
- Keep `scripts/sync_data.sh`, `scripts/launch*.sh`, `scripts/playwright-mcp.sh` as bash launchers.
- Keep `scripts/youtube_standalone_downloader.py` as multi-machine artifact.

### Tests
```bash
curate stats
curate stats --detailed
curate build-metadata
generate regen-stretched --output-dir data/videos/fake/wan_2_2/instagram --source-dir data/videos/real/instagram/validated --dry-run | head
```

**Commit message:** `refactor(cli): wire scripts utilities into curate/generate CLIs`

---

## Phase 9 — Final cleanup

- Delete `validators/batch_review.py` if user confirms (no callers, was already orphan).
- Delete `scrapers/civitai_simple.py` if folded into `civitai.py --sync`, otherwise keep.
- Update CLAUDE.md "Project Structure" section to reflect new tree.
- Run a full grep for stale references:
  ```bash
  grep -rln "video_gen\.\|from scrapers\b\|from validators\b\|from video\b" \
    --include="*.py" --include="*.sh" --include="*.md" .
  # Should return nothing under our code (third_party may have hits — ignore)
  ```
- Add a `CHANGELOG_REFACTOR.md` summarizing what moved where, for future devs.

**Commit message:** `chore(refactor): final cleanup, update docs, remove stale orphans`

---

## Rollback strategy

- Each phase is one commit. If a smoke test fails, `git revert <hash>` immediately.
- Keep the branch isolated until Phase 9 completes; merge only after a full rerun of:
  ```bash
  curate stats
  generate metadata --root data/videos/fake --workers 8
  COMFY_CONFIG=configs.generate.wan22_instagram bash scripts/launch.sh status
  ```

---

## Acceptance criteria

- [ ] All 80+ imports across the codebase use new paths.
- [ ] `curate --help` and `generate --help` show all subcommands.
- [ ] All 35 configs load without error.
- [ ] All 15 workflow modules load via `generate.workflows.X`.
- [ ] `make stats` produces same output as before.
- [ ] `make metadata` rebuilds image metadata.
- [ ] `generate run <config>` launches a 1-clip smoke run successfully.
- [ ] No file imports `video_gen.*`, `from scrapers.X`, `from validators.X`, or `from video.X`.
- [ ] CLAUDE.md updated.
- [ ] Pair 2 + Pair 3 (LTX) generation completed before refactor started, so no in-flight collisions.

---

## Estimated wall time per phase (assuming Pair 2 already finished)

| Phase | Time | Risk |
|---|---|---|
| 0. Pre-flight | 10 min | — |
| 1. shared/ package | 30 min | low |
| 2. configs/ split | 45 min | medium |
| 3. video/ → curate/videos/ | 60 min | medium-high |
| 4. scrapers+validators → curate/images/ | 30 min | low-medium |
| 5. video_gen/ → generate/ | 45 min | high (config strings) |
| 6. CLI wiring | 60 min | low |
| 7. Caption/manifest renames | 30 min | low |
| 8. Scripts → CLI subcommands | 45 min | low |
| 9. Final cleanup | 30 min | trivial |
| **Total** | **~6 hours** | |

---

## Open questions for the user

1. **Drop `validators/batch_review.py`** (orphan — no callers). Confirmed in Phase 9?
2. **Fold `civitai_simple.py` into `civitai.py --sync`**, or keep as-is?
3. **`scripts/youtube_standalone_downloader.py`** — keep as standalone uv-script for multi-machine deploy, or fold into `curate videos download --standalone`?
4. **Move `scripts/launch.sh` → `generate run`** (CLI subcommand) or keep as bash launcher? Bash easier for `nohup` + log redirection.
