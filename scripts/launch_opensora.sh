#!/usr/bin/env bash
# Multi-GPU launcher for Open-Sora 2.0 video generation.
#
# Mirrors scripts/launch.sh but routes to `generate.opensora_run` (which
# subprocesses Open-Sora's own torchrun-based inference.py) instead of
# `generate.comfy_batch_run` (ComfyUI HTTP).
#
# Usage:
#   scripts/launch_opensora.sh start|stop|status
#
# Required env:
#   OPENSORA_CONFIG   config module (e.g. configs.generate.opensora_youtube)
#
# Optional env:
#   GPUS              space-separated GPU ids (default: 0 1 2 3 4 5 6 7)
#   LOGS              log dir (default: /tmp/opensora_logs/<config_slug>)

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
OPENSORA=$REPO/third_party/Open-Sora
PY=$OPENSORA/.venv/bin/python
CMD=${1:-start}

: "${GPUS:=0 1 2 3 4 5 6 7}"

GPU_LIST=$(echo "$GPUS" | tr ',' ' ')

config_slug() { echo "${OPENSORA_CONFIG:-unknown}" | tr '.' '_'; }
: "${LOGS:=/tmp/opensora_logs/$(config_slug)}"

case "$CMD" in
  stop)
    if [[ -n "${OPENSORA_CONFIG:-}" ]]; then
        echo "stopping opensora workers for $OPENSORA_CONFIG..."
        pkill -f "OPENSORA_CONFIG=$OPENSORA_CONFIG" || true
    else
        echo "stopping ALL opensora_run workers..."
        pkill -f "generate.opensora_run" || true
    fi
    pkill -f "scripts/diffusion/inference.py" || true
    exit 0
    ;;
  status)
    echo "=== opensora workers ==="
    pgrep -af "generate.opensora_run" | grep -v grep || echo "(no workers)"
    echo "=== opensora torchrun children ==="
    pgrep -af "scripts/diffusion/inference.py" | grep -v grep || echo "(no torchrun)"
    exit 0
    ;;
  start) ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac

if [[ -z "${OPENSORA_CONFIG:-}" ]]; then
    echo "error: OPENSORA_CONFIG=<module> is required for start"
    echo "  e.g. OPENSORA_CONFIG=configs.generate.opensora_youtube $0 start"
    exit 1
fi
if [[ ! -x "$PY" ]]; then
    echo "error: Open-Sora venv not found at $PY"
    echo "       (run: cd $OPENSORA && uv sync)"
    exit 1
fi

mkdir -p "$LOGS"
SHARD_COUNT=$(echo "$GPU_LIST" | wc -w)

echo "config: $OPENSORA_CONFIG"
echo "gpus:   $GPU_LIST  (shards=$SHARD_COUNT)"
echo "logs:   $LOGS"

idx=0
for gpu in $GPU_LIST; do
    CUDA_VISIBLE_DEVICES=$gpu \
        PYTHONPATH=$REPO:$OPENSORA \
        OPENSORA_CONFIG=$OPENSORA_CONFIG \
        SHARDS=$SHARD_COUNT SHARD_ID=$idx \
        nohup "$PY" -m generate.opensora_run \
        > "$LOGS/shard_${idx}_gpu${gpu}.log" 2>&1 &
    disown $! 2>/dev/null || true
    echo "  shard=$idx/$SHARD_COUNT gpu=$gpu"
    idx=$((idx + 1))
done

echo ""
echo "launched $SHARD_COUNT shards."
echo "  status: $0 status"
echo "  stop:   $0 stop"
echo "  tail:   tail -f $LOGS/shard_0_gpu*.log"
