#!/usr/bin/env bash
# Multi-GPU launcher for video-SALMONN 2+ video captioning.
#
# Mirrors scripts/launch.sh. Each shard runs as a separate process pinned
# to one GPU. Stable shard split by clip index — workers don't fight for
# the same outputs.
#
# Usage:
#   scripts/launch_caption.sh start|stop|status
#
# Required env:
#   VIDEOS_DIR       directory of mp4s to caption (e.g. data/videos/real/youtube/validated)
#   OUTPUT_JSON      output JSON (e.g. data/videos/real/youtube/video_captions.json)
#                    With shards>1, "_shard{id}" is appended before .json.
#
# Optional env:
#   GPUS             space-separated GPU ids (default: 0 1 2 3 4 5 6 7)
#   MODEL            HF model ID or local path (default: tsinghua-ee/video-SALMONN2_plus_7B_full)
#   NO_AUDIO         set to 1 for visual-only captioning
#   MAX_NEW_TOKENS   default 1024
#   LOGS             log dir (default: /tmp/salmonn_caption_logs)
#
# Example:
#   VIDEOS_DIR=data/videos/real/youtube/validated \
#   OUTPUT_JSON=data/videos/real/youtube/video_captions.json \
#   scripts/launch_caption.sh start

set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
SALMONN=$REPO/third_party/SALMONN-2-plus
PY=$SALMONN/.venv/bin/python
CMD=${1:-start}

: "${GPUS:=0 1 2 3 4 5 6 7}"
: "${MODEL:=tsinghua-ee/video-SALMONN2_plus_7B_full}"
: "${MAX_NEW_TOKENS:=1024}"
: "${LOGS:=/tmp/salmonn_caption_logs}"

GPU_LIST=$(echo "$GPUS" | tr ',' ' ')

case "$CMD" in
  stop)
    echo "stopping caption_salmonn workers..."
    pkill -f "curate.videos.caption_salmonn" || true
    exit 0
    ;;
  status)
    echo "=== workers ==="
    pgrep -af "curate.videos.caption_salmonn" | grep -v grep || echo "(no workers)"
    exit 0
    ;;
  start) ;;
  *) echo "usage: $0 [start|stop|status]"; exit 1 ;;
esac

if [[ -z "${VIDEOS_DIR:-}" && -z "${VIDEOS_LIST_FILE:-}" ]]; then
    echo "error: VIDEOS_DIR=<dir> or VIDEOS_LIST_FILE=<path> is required for start"
    exit 1
fi
if [[ -z "${OUTPUT_JSON:-}" ]]; then
    echo "error: OUTPUT_JSON=<path> is required for start"
    exit 1
fi
if [[ ! -x "$PY" ]]; then
    echo "error: SALMONN venv not found at $PY"
    echo "       (try: cd $SALMONN && uv sync)"
    exit 1
fi

: "${WORKERS_PER_GPU:=1}"

mkdir -p "$LOGS"
GPU_COUNT=$(echo "$GPU_LIST" | wc -w)
SHARD_COUNT=$((GPU_COUNT * WORKERS_PER_GPU))

echo "videos:           ${VIDEOS_DIR:-(none)}"
echo "videos_list_file: ${VIDEOS_LIST_FILE:-(none)}"
echo "output:           $OUTPUT_JSON"
echo "model:            $MODEL"
echo "gpus:             $GPU_LIST  (gpus=$GPU_COUNT × workers/gpu=$WORKERS_PER_GPU = $SHARD_COUNT shards)"
echo "logs:             $LOGS"

NO_AUDIO_FLAG=""
[[ "${NO_AUDIO:-0}" == "1" ]] && NO_AUDIO_FLAG="--no-audio"

# Build the input flag based on whether we have a list file or a dir
if [[ -n "${VIDEOS_LIST_FILE:-}" ]]; then
    INPUT_FLAGS=(--videos-list-file "$VIDEOS_LIST_FILE")
else
    INPUT_FLAGS=(--videos-dir "$VIDEOS_DIR")
fi

# Each (gpu, worker_idx_on_gpu) pair gets a unique global shard_id.
# Layout: shard_id = w * GPU_COUNT + gpu_position. So GPU 0 gets shards
# 0, 8, 16, 24 (for WORKERS_PER_GPU=4); GPU 1 gets 1, 9, 17, 25; etc.
idx=0
for w in $(seq 0 $((WORKERS_PER_GPU - 1))); do
    for gpu in $GPU_LIST; do
        CUDA_VISIBLE_DEVICES=$gpu \
            PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
            PYTHONPATH=$SALMONN:$REPO \
            nohup "$PY" -m curate.videos.caption_salmonn \
                --model "$MODEL" \
                "${INPUT_FLAGS[@]}" \
                --output "$OUTPUT_JSON" \
                --shards "$SHARD_COUNT" --shard-id "$idx" \
                --max-new-tokens "$MAX_NEW_TOKENS" \
                $NO_AUDIO_FLAG \
            > "$LOGS/shard_${idx}_gpu${gpu}_w${w}.log" 2>&1 &
        disown $! 2>/dev/null || true
        echo "  shard=$idx/$SHARD_COUNT gpu=$gpu worker=$w"
        idx=$((idx + 1))
    done
done

echo ""
echo "launched $SHARD_COUNT shards."
echo "  status: $0 status"
echo "  stop:   $0 stop"
echo "  tail:   tail -f $LOGS/shard_0_gpu*.log"
