#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
while true; do
    STAGING_COUNT=$(ls data/grok/staging/ 2>/dev/null | wc -l)
    IMAGES_COUNT=$(ls data/grok/images/ 2>/dev/null | wc -l)
    echo "$(date): staging=$STAGING_COUNT, validated=$IMAGES_COUNT"
    if [ "$STAGING_COUNT" -lt 20 ]; then
        echo "  Less than 20 in staging, waiting 60s..."
        sleep 60
        continue
    fi
    echo "  Running batch_classify..."
    uv run python -m validators.batch_classify \
        --dir data/grok/staging --output data/grok/captions.json --concurrency 6 2>&1 | tail -3
    echo "  Running pipeline..."
    uv run python -m validators.pipeline --config configs/grok.py --skip-fsd 2>&1 | tail -10
    echo "  Sweep complete. Waiting 120s..."
    sleep 120
done
