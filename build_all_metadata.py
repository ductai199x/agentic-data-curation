#!/usr/bin/env python3
"""Build metadata.csv for all 10 datasets.

For each dataset, reads manifest.csv, filters to images present in images/
(or staging/ for instagram_ai_influencer), maps model_version from
source/flair, and writes metadata.csv with columns:
  filename, source, model_version, width, height, format, file_size, url, timestamp
"""

import csv
import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

METADATA_COLUMNS = [
    "filename", "source", "model_version",
    "width", "height", "format", "file_size",
    "url", "timestamp",
]

# ── Model version mapping functions ──────────────────────────────────────

def _mv_grok(source: str, flair: str) -> str:
    if "grok_imagine" in source:
        return "grok"
    if source == "civitai":
        return "grok_civitai"
    if source == "twitter":
        return "grok_twitter"
    if source == "reddit":
        return "grok"
    return "grok"


def _mv_flux1(source: str, flair: str) -> str:
    # Civitai model_version_id mapping
    civitai_map = {
        "onsite:model_version:691639": "dev",
        "onsite:model_version:699279": "schnell",
        "onsite:model_version:922358": "pro_1.1",
        "onsite:model_version:1088507": "pro_1.1_ultra",
        "onsite:model_version:1892509": "kontext_pro",
        "onsite:model_version:2068000": "krea_dev",
    }
    if source == "civitai" and flair in civitai_map:
        return civitai_map[flair]

    if "flux_kontext" in source or "flux_kontext" in flair:
        return "kontext"

    if source == "openart":
        return "unknown_openart"

    if source == "tensorart":
        fl = flair.lower()
        if "schnell" in fl:
            return "schnell"
        # Check for dev variants
        for kw in ["dev", "dev fp32", "dev-fp16", "dev-fp8", "dev-q6"]:
            if kw in fl:
                return "dev"
        return "unknown_tensorart"

    if "yodayo" in source or "yodayo" in flair:
        if "schnell" in flair.lower() or "schnell" in source.lower():
            return "schnell"
        return "dev"

    return "unknown"


def _mv_flux2(source: str, flair: str) -> str:
    civitai_map = {
        "onsite:model_version:2439047": "max",
        "onsite:model_version:2439067": "dev",
        "onsite:model_version:2439442": "pro",
        "onsite:model_version:2547175": "flex",
    }
    if source == "civitai" and flair in civitai_map:
        return civitai_map[flair]

    if "flux_2" in flair or "flux_2" in source:
        return "dev"

    return "unknown"


def _mv_midjourney_v7(source: str, flair: str) -> str:
    fl = flair.lower()
    if "v8" in fl:
        return "v8"
    if "v7" in fl:
        return "v7"
    if "vunknown" in fl:
        return "v7_default"
    return "v7"


def _mv_soul2(source: str, flair: str) -> str:
    fl = flair.lower()
    if "soul_v2" in fl or "text2image_soul_v2" in fl:
        return "soul_v2"
    if "soul_cinematic" in fl:
        return "soul_cinematic"
    if "ai_influencer" in fl:
        return "ai_influencer"
    if "text2image_soul" in fl or "soul" in fl:
        return "soul_v1"
    return "unknown"


def _mv_nano_banana(source: str, flair: str) -> str:
    if "nano_banana_2" in source or "nano_banana_2" in flair:
        return "v2"
    if "nano_banana" in source or "nano_banana" in flair:
        return "v1"
    # Reddit/twitter fallback
    return "unknown"


def _mv_seedream4(source: str, flair: str) -> str:
    fl = flair.lower()
    src = source.lower()
    if "5.0_lite" in fl or "5_lite" in fl or "50_lite" in src or "v5_lite" in fl or "v5_lite" in src:
        return "seedream_5.0_lite"
    if "4.5" in fl or "v4_5" in src or "v45" in src or "model_version:2470991" in flair:
        return "seedream_4.5"
    if "4.0" in fl or "model_version:2208278" in flair or "seedream" in fl:
        return "seedream_4.0"
    return "seedream_4.0"


def _mv_gpt_image(source: str, flair: str) -> str:
    if "model_version:2512167" in flair or "openai_hazel" in flair or "openai_hazel" in source:
        return "gpt-image-1.5"
    if "model_version:1733399" in flair or "text2image_gpt" in flair or "text2image_gpt" in source:
        return "gpt-image-1"
    return "unknown"


def _mv_recraft(source: str, flair: str) -> str:
    fl = flair.lower()
    if "recraftv4_pro" in fl:
        return "v4_pro"
    if "recraftv4" in fl:
        return "v4"
    if "recraftv3" in fl:
        return "v3"
    return "unknown"


def _mv_instagram(source: str, flair: str) -> str:
    return "unknown"


MODEL_VERSION_FN = {
    "grok": _mv_grok,
    "flux1": _mv_flux1,
    "flux2": _mv_flux2,
    "midjourney_v7": _mv_midjourney_v7,
    "soul2": _mv_soul2,
    "nano_banana_1_2": _mv_nano_banana,
    "seedream4": _mv_seedream4,
    "gpt_image_1": _mv_gpt_image,
    "recraft_3_4": _mv_recraft,
    "instagram_ai_influencer": _mv_instagram,
}

# ── Main build logic ─────────────────────────────────────────────────────

DATASETS = [
    "midjourney_v7", "soul2", "flux1", "nano_banana_1_2",
    "instagram_ai_influencer", "recraft_3_4", "gpt_image_1",
    "grok", "flux2", "seedream4",
]


def build_metadata(dataset: str) -> int:
    ds_dir = DATA_DIR / dataset

    # Determine image directory
    if dataset == "instagram_ai_influencer":
        img_dir = ds_dir / "staging"
    else:
        img_dir = ds_dir / "images"

    manifest_path = ds_dir / "manifest.csv"
    output_path = ds_dir / "metadata.csv"

    if not manifest_path.exists():
        print(f"  SKIP: no manifest.csv")
        return 0
    if not img_dir.exists():
        print(f"  SKIP: no {img_dir.name}/ directory")
        return 0

    # Build set of filenames present in image directory
    present = set(os.listdir(img_dir))

    # Read manifest
    mv_fn = MODEL_VERSION_FN[dataset]
    rows = []

    with open(manifest_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = row.get("filename", "")
            if fn not in present:
                continue

            source = row.get("source", "")
            flair = row.get("flair", "")
            model_version = mv_fn(source, flair)

            rows.append({
                "filename": fn,
                "source": source,
                "model_version": model_version,
                "width": row.get("width", ""),
                "height": row.get("height", ""),
                "format": row.get("format", ""),
                "file_size": row.get("file_size", ""),
                "url": row.get("url", ""),
                "timestamp": row.get("timestamp", ""),
            })

    # Sort by filename for deterministic output
    rows.sort(key=lambda r: r["filename"])

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=METADATA_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def main():
    print("Building metadata.csv for all datasets\n")
    total = 0
    for ds in DATASETS:
        print(f"[{ds}]")
        n = build_metadata(ds)
        print(f"  -> {n} images")
        total += n
        # Print model_version distribution
        if n > 0:
            dist: dict[str, int] = {}
            for row_path in [DATA_DIR / ds / "metadata.csv"]:
                with open(row_path, newline="", encoding="utf-8") as f:
                    for row in csv.DictReader(f):
                        mv = row["model_version"]
                        dist[mv] = dist.get(mv, 0) + 1
            for mv, count in sorted(dist.items(), key=lambda x: -x[1]):
                print(f"     {mv}: {count} ({100*count/n:.1f}%)")
        print()

    print(f"Total: {total} images across {len(DATASETS)} datasets")


if __name__ == "__main__":
    main()
