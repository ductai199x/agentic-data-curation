#!/usr/bin/env bash
# Unified launcher for any ComfyUI-driven video-gen batch.
#
# Every worker is self-contained: `video_gen.comfy_batch_run` spawns its own
# ComfyUI child on a random free port via `video_gen.comfy_spawn`, and the
# child dies with the parent (PR_SET_PDEATHSIG). No pre-booted ComfyUI
# servers, no shared ports, no state to clean up beyond killing workers.
#
# Usage:
#   scripts/launch.sh start|stop|status
#
# Env (all optional):
#   COMFY_CONFIG   config module (required for start). e.g. configs.wan22_instagram
#   GPUS           space/comma-separated GPU ids (default: 0 1 2 3 4 5 6 7)
#   LOGS           log dir (default: /tmp/comfy_batch_logs/<config_slug>)
#
# Examples:
#   COMFY_CONFIG=configs.wan22_instagram scripts/launch.sh start
#   COMFY_CONFIG=configs.ltx_instagram GPUS="4 5 6 7" scripts/launch.sh start
#   COMFY_CONFIG=configs.hunyuan_video_instagram scripts/launch.sh stop
#   scripts/launch.sh status

set -euo pipefail

REPO=/home/tai/1-workdir/09-agent-data-curation
COMFY=$REPO/third_party/ComfyUI
CMD=${1:-start}

: "${GPUS:=0 1 2 3 4 5 6 7}"
: "${PY:=$COMFY/.venv/bin/python}"

GPU_LIST=$(echo "$GPUS" | tr ',' ' ')

config_slug() { echo "${COMFY_CONFIG:-unknown}" | tr '.' '_'; }
: "${LOGS:=/tmp/comfy_batch_logs/$(config_slug)}"

case "$CMD" in
  stop)
    # Match by COMFY_CONFIG value in cmdline so we only kill our own workers.
    if [[ -n "${COMFY_CONFIG:-}" ]]; then
        echo "stopping workers for $COMFY_CONFIG..."
        pkill -f "COMFY_CONFIG=$COMFY_CONFIG" || true
    else
        echo "stopping ALL comfy_batch_run workers..."
        pkill -f "video_gen.comfy_batch_run" || true
    fi
    # Child ComfyUIs die with parents via PR_SET_PDEATHSIG — nothing else to do.
    exit 0
    ;;
  status)
    echo "=== workers ==="
    pgrep -af "video_gen.comfy_batch_run" | grep -v grep || echo "(no workers)"
    echo "=== comfy children ==="
    pgrep -af "ComfyUI/main.py" | grep -v grep || echo "(no comfy)"
    exit 0
    ;;
  start) ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac

if [[ -z "${COMFY_CONFIG:-}" ]]; then
    echo "error: COMFY_CONFIG=<module> is required for start"
    echo "  e.g. COMFY_CONFIG=configs.wan22_instagram $0 start"
    exit 1
fi

mkdir -p "$LOGS"
SHARD_COUNT=$(echo "$GPU_LIST" | wc -w)

echo "config:  $COMFY_CONFIG"
echo "gpus:    $GPU_LIST  (shards=$SHARD_COUNT)"
echo "logs:    $LOGS"

idx=0
for gpu in $GPU_LIST; do
    CUDA_VISIBLE_DEVICES=$gpu \
        PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
        PYTHONPATH=$REPO \
        COMFY_CONFIG=$COMFY_CONFIG \
        SHARDS=$SHARD_COUNT SHARD_ID=$idx \
        nohup "$PY" -m video_gen.comfy_batch_run \
        > "$LOGS/shard_${idx}_gpu${gpu}.log" 2>&1 &
    disown $! 2>/dev/null || true
    echo "  shard=$idx/$SHARD_COUNT gpu=$gpu"
    idx=$((idx + 1))
done

echo ""
echo "launched $SHARD_COUNT shards. each self-spawns its own ComfyUI."
echo "  status: COMFY_CONFIG=$COMFY_CONFIG $0 status"
echo "  stop:   COMFY_CONFIG=$COMFY_CONFIG $0 stop"
echo "  tail:   tail -f $LOGS/shard_0_gpu*.log"
