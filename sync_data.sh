#!/bin/bash
# Sync data/ to weka destination.
# Source (data/) is ground truth — destination is made to match exactly.
# Only syncs images/ staging/ and metadata.csv per dataset.
# Excludes cookies, other CSVs, JSONs.

SRC="data/"
DST="$HOME/weka_data/tai/agentic-data-curation/ai_generated/"

if [ ! -d "$SRC" ]; then
    echo "Error: source $SRC not found"
    exit 1
fi

mkdir -p "$DST"

# Get all dataset dirs
for dataset_dir in "$SRC"*/; do
    dataset=$(basename "$dataset_dir")

    # Skip if no images or staging
    if [ ! -d "${dataset_dir}images" ] && [ ! -d "${dataset_dir}staging" ]; then
        continue
    fi

    echo "=== Syncing $dataset ==="

    # Sync images/ (delete extras at destination)
    if [ -d "${dataset_dir}images" ]; then
        mkdir -p "${DST}${dataset}/images"
        rsync -a --delete "${dataset_dir}images/" "${DST}${dataset}/images/"
        echo "  images/: $(ls "${DST}${dataset}/images/" | wc -l) files"
    fi

    # Sync staging/ (delete extras at destination)
    if [ -d "${dataset_dir}staging" ]; then
        mkdir -p "${DST}${dataset}/staging"
        rsync -a --delete "${dataset_dir}staging/" "${DST}${dataset}/staging/"
        echo "  staging/: $(ls "${DST}${dataset}/staging/" | wc -l) files"
    fi

    # Copy metadata.csv only
    if [ -f "${dataset_dir}metadata.csv" ]; then
        cp "${dataset_dir}metadata.csv" "${DST}${dataset}/metadata.csv"
        echo "  metadata.csv: copied"
    fi

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
done

# Remove destination datasets not in source
for dest_dir in "$DST"*/; do
    dataset=$(basename "$dest_dir")
    if [ ! -d "${SRC}${dataset}" ]; then
        echo "=== Removing $dataset (not in source) ==="
        rm -rf "$dest_dir"
    fi
done

echo ""
echo "=== Sync complete ==="
echo "Destination: $DST"
du -sh "$DST" 2>/dev/null
