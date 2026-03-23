#!/bin/bash
# Sync data/ to destination.
# Source (data/) is ground truth — destination is made to match exactly.
# Only syncs images/ staging/ and metadata.csv per dataset.
# Excludes cookies, other CSVs, JSONs.
#
# Usage:
#   ./scripts/sync_data.sh                          # defaults
#   ./scripts/sync_data.sh --dst /path/to/dest      # custom destination
#   ./scripts/sync_data.sh --src other_data/         # custom source
#   ./scripts/sync_data.sh --dry-run                 # preview only
#   ./scripts/sync_data.sh --dataset grok            # sync single dataset

cd "$(dirname "$0")/.." || exit 1

# Defaults
SRC="data/"
DST="$HOME/weka_data/tai/agentic-data-curation/ai_generated/"
DRY_RUN=false
DATASET_FILTER=""

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --src)      SRC="$2"; shift 2 ;;
        --dst)      DST="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=true; shift ;;
        --dataset)  DATASET_FILTER="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--src DIR] [--dst DIR] [--dry-run] [--dataset NAME]"
            echo ""
            echo "Options:"
            echo "  --src DIR       Source directory (default: data/)"
            echo "  --dst DIR       Destination directory (default: ~/weka_data/tai/agentic-data-curation/ai_generated/)"
            echo "  --dry-run       Preview what would be synced without copying"
            echo "  --dataset NAME  Sync only this dataset (e.g. grok, flux1)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1. Use --help for usage."
            exit 1
            ;;
    esac
done

# Ensure trailing slash
SRC="${SRC%/}/"
DST="${DST%/}/"

if [ ! -d "$SRC" ]; then
    echo "Error: source $SRC not found"
    exit 1
fi

echo "Source: $SRC"
echo "Destination: $DST"
$DRY_RUN && echo "Mode: DRY RUN"
[ -n "$DATASET_FILTER" ] && echo "Filter: $DATASET_FILTER only"
echo ""

$DRY_RUN || mkdir -p "$DST"

RSYNC_FLAGS="-a --delete"
$DRY_RUN && RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"

# Get all dataset dirs
for dataset_dir in "$SRC"*/; do
    dataset=$(basename "$dataset_dir")

    # Filter to single dataset if specified
    [ -n "$DATASET_FILTER" ] && [ "$dataset" != "$DATASET_FILTER" ] && continue

    # Skip if no images or staging
    if [ ! -d "${dataset_dir}images" ] && [ ! -d "${dataset_dir}staging" ]; then
        continue
    fi

    echo "=== Syncing $dataset ==="

    # Sync images/ (delete extras at destination)
    if [ -d "${dataset_dir}images" ]; then
        $DRY_RUN || mkdir -p "${DST}${dataset}/images"
        rsync $RSYNC_FLAGS "${dataset_dir}images/" "${DST}${dataset}/images/"
        echo "  images/: $(ls "${dataset_dir}images/" | wc -l) files"
    fi

    # Sync staging/ (delete extras at destination)
    if [ -d "${dataset_dir}staging" ]; then
        $DRY_RUN || mkdir -p "${DST}${dataset}/staging"
        rsync $RSYNC_FLAGS "${dataset_dir}staging/" "${DST}${dataset}/staging/"
        echo "  staging/: $(ls "${dataset_dir}staging/" | wc -l) files"
    fi

    # Copy metadata.csv only
    if [ -f "${dataset_dir}metadata.csv" ]; then
        $DRY_RUN || cp "${dataset_dir}metadata.csv" "${DST}${dataset}/metadata.csv"
        echo "  metadata.csv: copied"
    fi

    if ! $DRY_RUN; then
        # Remove files at destination that we don't want
        for f in "${DST}${dataset}"/*.json "${DST}${dataset}"/*.csv; do
            fname=$(basename "$f")
            if [ "$fname" != "metadata.csv" ] && [ -f "$f" ]; then
                rm "$f"
                echo "  removed: $fname"
            fi
        done

        # Remove rejected/ and other dirs we don't need
        [ -d "${DST}${dataset}/rejected" ] && rm -rf "${DST}${dataset}/rejected" && echo "  removed: rejected/"
    fi
done

# Remove destination datasets not in source (skip if filtering)
if [ -z "$DATASET_FILTER" ] && ! $DRY_RUN; then
    for dest_dir in "$DST"*/; do
        dataset=$(basename "$dest_dir")
        if [ ! -d "${SRC}${dataset}" ]; then
            echo "=== Removing $dataset (not in source) ==="
            rm -rf "$dest_dir"
        fi
    done
fi

echo ""
echo "=== Sync complete ==="
echo "Destination: $DST"
$DRY_RUN || du -sh "$DST" 2>/dev/null
