#!/usr/bin/env bash
# Multi-GPU launcher for generate.interpolate_fps (RIFE 4.26).
#
# Each shard runs as a separate process pinned to one GPU. Stable shard
# split by clip index — workers don't fight for the same outputs.
#
# Workers per GPU defaults to 4 (the sweet spot on H200/1280×720 — going
# higher than 4 yields rapidly diminishing returns; going to 8 only buys
# ~1.2× more throughput).
#
# Usage:
#   scripts/launch_interpolate.sh start|stop|status
#
# Env (all optional):
#   ROOT             source root (default: data/videos/fake)
#   OUT_ROOT         output root (default: data/videos/fake_30fps_rife)
#   GPUS             space-separated GPU ids (default: 0 1 2 3 4 5 6 7)
#   WORKERS_PER_GPU  parallel workers on each GPU (default: 4)
#   TARGET_FPS       output fps (default: 30)
#   LOGS             log dir (default: /tmp/rife_logs)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
PY=$REPO/third_party/ComfyUI/.venv/bin/python
CMD=${1:-start}
: "${ROOT:=data/videos/fake}"
: "${OUT_ROOT:=data/videos/fake_30fps_rife}"
: "${GPUS:=0 1 2 3 4 5 6 7}"
: "${WORKERS_PER_GPU:=4}"
: "${TARGET_FPS:=30}"
: "${LOGS:=/tmp/rife_logs}"

GPU_LIST=$(echo "$GPUS" | tr ',' ' ')
GPU_COUNT=$(echo "$GPU_LIST" | wc -w)
SHARD_COUNT=$((GPU_COUNT * WORKERS_PER_GPU))

case "$CMD" in
  stop)
    echo "stopping rife interpolate workers..."
    pkill -f "generate.interpolate_fps" || true
    exit 0
    ;;
  status)
    echo "=== workers ==="
    pgrep -af "generate.interpolate_fps" | grep -v grep || echo "(none)"
    exit 0
    ;;
  start) ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac

mkdir -p "$LOGS"
cd "$REPO"
echo "root:            $ROOT"
echo "out:             $OUT_ROOT"
echo "gpus:            $GPU_LIST  ($GPU_COUNT GPUs)"
echo "workers/GPU:     $WORKERS_PER_GPU"
echo "total shards:    $SHARD_COUNT"
echo "target fps:      $TARGET_FPS"
echo "logs:            $LOGS"
echo

shard_id=0
for gpu in $GPU_LIST; do
  for w in $(seq 1 $WORKERS_PER_GPU); do
    CUDA_VISIBLE_DEVICES=$gpu \
      PYTHONPATH=$REPO \
      SHARDS=$SHARD_COUNT SHARD_ID=$shard_id \
      nohup "$PY" -m generate.interpolate_fps \
        --root "$ROOT" \
        --out-root "$OUT_ROOT" \
        --target-fps "$TARGET_FPS" \
        > "$LOGS/shard_${shard_id}_gpu${gpu}_w${w}.log" 2>&1 &
    disown $! 2>/dev/null || true
    echo "  shard=$shard_id  gpu=$gpu  worker=$w/${WORKERS_PER_GPU}  pid=$!"
    shard_id=$((shard_id + 1))
  done
done
echo
echo "launched $SHARD_COUNT shards. tail logs: tail -f $LOGS/shard_*.log"
