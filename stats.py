#!/usr/bin/env python3
"""Print stats on all curated datasets.

Usage:
    uv run python stats.py              # short summary
    uv run python stats.py --detailed   # detailed per-dataset breakdown
"""

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path

from tabulate import tabulate


DATA_DIR = Path("data")

DATASETS = [
    "midjourney_v7", "soul2", "flux1", "nano_banana_1_2",
    "instagram_ai_influencer", "recraft_3_4", "gpt_image_1",
    "grok", "flux2", "seedream4",
]


def count_dir(path):
    try:
        return len(os.listdir(path))
    except FileNotFoundError:
        return 0


def load_csv(path):
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def get_fsd_stats(fsd_path):
    rows = load_csv(fsd_path)
    if not rows:
        return None
    scores = []
    for r in rows:
        z = r.get("z_score") or r.get("zscore") or "0"
        try:
            scores.append(float(z))
        except ValueError:
            continue
    if not scores:
        return None
    detected = sum(1 for z in scores if z < -2.0)
    return {
        "total": len(scores),
        "detected": detected,
        "rate": detected / len(scores) * 100,
        "mean_z": sum(scores) / len(scores),
    }


def get_model_versions(metadata_path):
    rows = load_csv(metadata_path)
    if not rows:
        return {}
    versions = Counter()
    for r in rows:
        v = r.get("model_version", "unknown")
        versions[v] += 1
    return versions


def get_source_breakdown(metadata_path):
    rows = load_csv(metadata_path)
    if not rows:
        return {}
    sources = Counter()
    for r in rows:
        src = r.get("source", "unknown")
        # Simplify source to platform name
        if ":" in src:
            src = src.split(":")[0]
        sources[src] += 1
    return sources


def get_format_breakdown(d):
    from PIL import Image
    img_dir = DATA_DIR / d / "images"
    staging_dir = DATA_DIR / d / "staging"
    target = img_dir if img_dir.exists() and count_dir(img_dir) > 0 else staging_dir
    if not target.exists():
        return {}
    formats = Counter()
    # Sample up to 100 images
    files = sorted(target.iterdir())[:100]
    for f in files:
        try:
            img = Image.open(f)
            formats[img.format] += 1
        except Exception:
            continue
    return formats


def short_summary():
    rows = []
    grand_total = 0
    for d in DATASETS:
        imgs = count_dir(DATA_DIR / d / "images")
        staging = count_dir(DATA_DIR / d / "staging")
        total = imgs + staging
        grand_total += total

        fsd = get_fsd_stats(DATA_DIR / d / "fsd_scores.csv")
        fsd_str = f"{fsd['rate']:.1f}%" if fsd else "—"
        mean_z = f"{fsd['mean_z']:.2f}" if fsd else "—"

        status = "done" if staging == 0 else f"{staging} staging"
        if d == "instagram_ai_influencer":
            status = "eval set"

        rows.append([d, f"{total:,}", f"{imgs:,}", fsd_str, mean_z, status])

    rows.append(["", "", "", "", "", ""])
    rows.append(["TOTAL", f"{grand_total:,}", "", "", "", ""])

    print(tabulate(
        rows,
        headers=["Dataset", "Total", "Validated", "FSD Det%", "Mean Z", "Status"],
        tablefmt="rounded_outline",
        colalign=("left", "right", "right", "right", "right", "left"),
    ))


def detailed_summary():
    for d in DATASETS:
        imgs = count_dir(DATA_DIR / d / "images")
        staging = count_dir(DATA_DIR / d / "staging")
        rejected = count_dir(DATA_DIR / d / "rejected")
        total = imgs + staging

        print(f"\n{'=' * 60}")
        print(f"  {d}")
        print(f"{'=' * 60}")

        # Basic counts
        info_rows = [
            ["Validated", f"{imgs:,}"],
            ["Staging", f"{staging:,}"],
            ["Rejected", f"{rejected:,}"],
        ]
        if imgs + staging + rejected > 0:
            pass_rate = imgs / (imgs + rejected) * 100 if (imgs + rejected) > 0 else 0
            info_rows.append(["Pass rate", f"{pass_rate:.1f}%"])

        print(tabulate(info_rows, tablefmt="plain"))

        # FSD
        fsd = get_fsd_stats(DATA_DIR / d / "fsd_scores.csv")
        if fsd:
            print(f"\n  FSD Detection:")
            fsd_rows = [
                ["Detected (z < -2.0)", f"{fsd['detected']:,} / {fsd['total']:,} ({fsd['rate']:.1f}%)"],
                ["Mean z-score", f"{fsd['mean_z']:.2f}"],
            ]
            print(tabulate(fsd_rows, tablefmt="plain"))

        # Model versions
        versions = get_model_versions(DATA_DIR / d / "metadata.csv")
        if versions:
            print(f"\n  Model Versions:")
            total_v = sum(versions.values())
            v_rows = []
            for v, cnt in versions.most_common(8):
                v_rows.append([v, f"{cnt:,}", f"{cnt/total_v*100:.1f}%"])
            if len(versions) > 8:
                others = sum(c for _, c in versions.most_common()[8:])
                v_rows.append(["(others)", f"{others:,}", f"{others/total_v*100:.1f}%"])
            print(tabulate(v_rows, headers=["Version", "Count", "%"], tablefmt="plain"))

        # Sources
        sources = get_source_breakdown(DATA_DIR / d / "metadata.csv")
        if sources and len(sources) > 1:
            print(f"\n  Sources:")
            total_s = sum(sources.values())
            s_rows = []
            for s, cnt in sources.most_common(6):
                s_rows.append([s, f"{cnt:,}", f"{cnt/total_s*100:.1f}%"])
            print(tabulate(s_rows, headers=["Source", "Count", "%"], tablefmt="plain"))

        # Formats (sampled)
        formats = get_format_breakdown(d)
        if formats:
            fmt_str = ", ".join(f"{f}: {c}" for f, c in formats.most_common())
            print(f"\n  Formats (sampled): {fmt_str}")


def main():
    parser = argparse.ArgumentParser(description="Print stats on curated datasets")
    parser.add_argument("--detailed", "-d", action="store_true", help="Detailed per-dataset breakdown")
    args = parser.parse_args()

    if args.detailed:
        detailed_summary()
    else:
        short_summary()


if __name__ == "__main__":
    main()
