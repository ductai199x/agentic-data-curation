#!/usr/bin/env bash
# End-to-end dry run of the adaptation pipeline: procedural samples, dummy detector, stub training.
# No GPU, no model downloads, no keys. Writes under data/adapt_dryrun/ (gitignored).
# Usage: scripts/adapt_dry_run.sh [--only <generator>]...   e.g. --only ltx_2_5
set -euo pipefail
cd "$(dirname "$0")/.."
export ADAPT_ROOT="${ADAPT_ROOT:-data/adapt_dryrun}" ADAPT_DATA_ROOT="${ADAPT_DATA_ROOT:-data/adapt_dryrun/data}"
# stub "training": writes a checkpoint pointer, exercising the ADAPT_TRAIN_CMD contract
export ADAPT_TRAIN_CMD='sleep 2 && echo dummy-v1-{run_id} > {output_dir}/checkpoint.txt'
uv run adapt run --dry-run --n 60 --resolution-scale 0.5 "$@"
uv run adapt status
