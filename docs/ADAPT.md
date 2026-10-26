# New-generator adaptation pipeline (`adapt`)

The goal is to make "a new generator dropped" into a routine, timed job: collect samples, build a ready-to-train batch, score the current detector before and after the update on the new generator plus a regression set through the processing ladder, and log every step so the time-to-adapt curve shows whether we keep halving it.

```
releases.md row ─► trigger ─► collect ─► dedupe ─► batch ─► eval --phase before ─► train ─► eval --phase after ─► report
                 (run + release/detected)  (first_samples)   (batch_ready)          (train_started/model_updated)
```

`uv run adapt run` does all of it for every new row; each stage is also its own command and is resumable (`uv run adapt status` shows where every run stands).

## Inputs

**Release log** — `configs/adapt/releases.md`, a markdown table (`Date | Name | Maker | Modality | Weights | Link | Detected`). The watch routines can't keep files, so an agent (or Tai) appends a row from each "Your watch on new generators" post. `trigger` turns every unseen row into a run (`runs/<slug>_<YYYYMMDD>/`) and drafts a profile if none exists.

**Profiles** — `configs/adapt/profiles/<name>.py`, plain Python like `configs/curate/images/*`. Defaults are in `adapt/profiles.py`. The important fields:

- `MODALITY` (`image`/`video`), `WEIGHTS` (`open`/`closed`), `LICENSE` (non-commercial or research licences put a warning in the batch note).
- Open image models: `HF_REPO`, `HF_REVISION`, `TORCH_DTYPE`, `GENERATION_KWARGS`, `RESOLUTIONS` (diffusers backend).
- Open video models: `VIDEO_BACKEND = "comfy"`, `COMFY_WORKFLOW` (a `generate.workflows.*` builder), `COMFY_MODEL_KWARGS`, `COMFY_SOURCE` (which real set's first frames + SALMONN captions condition I2V, so each fake has a paired real).
- Paid API nodes: `PAID_PROVIDER = True`, `COST_PER_CLIP_USD`, `MAX_COST_USD`; only runs with `ADAPT_ALLOW_PAID=1`, and `comfy_batch_run`'s own budget gate still applies.
- Closed models: `COLLECT_SOURCES` (a curated URL list or a repo scraper command); see "Source terms" below.
- `TARGET_SAMPLES`, `SPLIT`, `MIN_PIXELS`, `PHASH_MAX_DISTANCE`.

## Outputs

Samples land in the repo's usual layout, so the existing validators run on them unchanged: images in `data/images/<gen>/staging/` with the scrapers' `manifest.csv` columns, videos in `data/videos/fake/<gen>/<source>/` exactly as `generate/` writes them. Pipeline fields (run, prompt, seed, backend, paired real) go to `samples.jsonl` beside them.

Everything else is under `data/adapt/` (`$ADAPT_ROOT`):

| Path | What |
|---|---|
| `batches/<gen>/<run>/{train,val,eval_holdout}/` | hardlinked files; `manifest.csv` (label, source URL, timestamps, sha256, pHash, licence, split), `batch.json`, `READY.md` |
| `notifications/*.md` | short notes ("batch ready", "awaiting training") for the coordinator to relay; nothing is sent from code |
| `runs/<run>/` | `run.json` stage state, dedupe report, eval sets and scores, `comparison.json` |
| `index/phash_index.csv` | pHash of every batched sample, so later runs dedupe across generators |
| `index/regression_set.csv` | every run's `eval_holdout`; later runs are scored on it to catch regressions |
| `logs/time_to_adapt.jsonl` | one row per event: `release, detected, first_samples, batch_ready, eval_before, train_started, model_updated, eval_after` |
| `reports/TIME_TO_ADAPT.md`, `time_to_adapt.csv`, `halving_curve.svg` | the per-run table and the halving curve (log2 hours, release → model updated) |

`eval_holdout` never enters training. "Detected" means a ladder-mean AUC of at least `ADAPT_TARGET_AUC` (default 0.95); if the current model already meets it, time-to-adapt is recorded as 0. A regression is any older generator whose ladder-mean AUC drops by more than `ADAPT_REGRESSION_TOL` (default 0.02). The processing ladder is the one from the competitor benchmark (vendored in `adapt/processing/`): for images JPEG 85/65, resizes, WebP, simulated Facebook, X and phone-screenshot pipelines and an Instagram-then-WhatsApp chain; for video H.264 at two CRFs, 480p, and simulated TikTok, WhatsApp and X re-encodes.

## What plugs in (Tai's side)

| Variable | Needed for | Notes |
|---|---|---|
| `ADAPT_TRAIN_CMD` | `adapt train` | Shell template with `{batch_dir} {manifest} {train_dir} {val_dir} {base_checkpoint} {output_dir} {generator} {run_id}`. Write the new checkpoint path to `{output_dir}/checkpoint.txt` (or leave the checkpoint in `{output_dir}`). Without it, `train` marks the run "awaiting training" and you finish with `adapt mark-trained <run> --checkpoint <path>`. |
| `ADAPT_DETECT_CMD` + `ADAPT_DETECTOR=command` | `adapt eval` | Template with `{checkpoint} {file_list} {out_csv}`; write `path,score` (higher = more likely fake). Or `ADAPT_DETECTOR=fsd` (default) to use `fsd-score --weights-dir <checkpoint>`. Register the starting model once: `adapt register-model <tag> --checkpoint <path>`. |
| `ADAPT_REAL_EVAL_DIR` | `adapt eval` | Held-out real images/videos for the AUC negatives; keep them out of training. |
| `GPUS`, `PY` | comfy video collect | Same meaning as `scripts/launch.sh` (default GPU 0, ComfyUI venv python). |
| `HF_TOKEN` | gated HF repos | Read from the environment only. Diffusers isn't a repo dependency: `uv run --with diffusers --with torch adapt collect ...`. `ADAPT_DEVICE`, `ADAPT_CPU_OFFLOAD` are optional. |
| `ADAPT_ALLOW_SOURCES` | closed-model collect | Comma list of sources whose terms are barred or restricted by default (see below), once you've decided they're OK. |
| `ADAPT_ALLOW_PAID=1` | paid API nodes | Required on top of `MAX_COST_USD`. |
| `ADAPT_ROOT`, `ADAPT_DATA_ROOT`, `ADAPT_RELEASE_LOG`, `ADAPT_PROFILES_DIR` | optional | Override the default paths (the dry run uses these to stay in a sandbox). |

No key or token is ever written to a file by the pipeline.

## Source terms (closed models)

`adapt/collect.py` keeps a table of source terms. Twitter/X, Instagram and Discord are barred by default (their terms bar automated collection), Reddit is restricted, and Civitai, Higgsfield, official galleries and model pages are "check the page first". Every request honours robots.txt and backs off on 429s. Several recent closed releases (Seedance 2.5 4K, VideoGen Model 1, Canva Craft) have no public gallery to collect from yet, so their runs stop at `collect: empty` until a source exists.

## Dry run

```bash
scripts/adapt_dry_run.sh --only ltx_2_5
```

Safe on any machine: procedural stand-in samples, procedural reals, a dummy detector, a stub training command, all under `data/adapt_dryrun/`. For video profiles it also writes the real ComfyUI run config and checks it loads and that the workflow builder emits a graph, which is the step that breaks first on a new model.

## Running a real one

```bash
# 1. add the row to configs/adapt/releases.md, review the drafted profile
uv run adapt trigger
# 2. collect -> batch (video: on the GPU box with ComfyUI and the weights in place)
GPUS="0 1" uv run adapt collect <run>; uv run adapt dedupe <run>; uv run adapt batch <run>
# 3. evaluate, train, evaluate, report
uv run adapt eval <run> --phase before
uv run adapt train <run>            # or train by hand, then: uv run adapt mark-trained <run> --checkpoint <path>
uv run adapt eval <run> --phase after
uv run adapt report
```
