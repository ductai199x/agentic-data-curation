"""Merge per-category YouTube manifests from multiple NAS sources into the
local dataset. Union by `filename` (first-seen wins, local first).

Local layout is flat at the dataset root:
    <root>/download_manifests/<cat>.csv  — one per category

NAS sources keep the legacy layout (<root>/<cat>/manifest.csv) since that's
how Hamed/Aref's scripts dump them.

Usage:
    uv run python -m curate.videos.merge_yt_manifests \\
        --local data/videos/real/youtube \\
        --source ~/nas3/Hamed/youtube_downloads \\
        --source ~/nas3/Aref/yt-downloader/youtube_downloads

Safety:
  * Writes to `<local>/download_manifests/<cat>.csv.merged` first, then
    atomically renames onto the final path. Previous local manifest
    preserved with a `.bak.<timestamp>` suffix under `_backups/`.
  * Header is taken from the local manifest; mismatched headers abort.
  * Rows with `status != "downloaded"` are DROPPED — the merged manifest
    is a golden success-only record.
"""
from __future__ import annotations

import click
import csv
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path) as f:
        r = csv.DictReader(f)
        return list(r.fieldnames or []), list(r)


SUCCESS_STATUS = "downloaded"


def merge_category(local_mf: Path, source_mfs: list[Path]) -> tuple[int, int, int, int]:
    """Merge sources into local. Returns (local_rows, added_rows, total_rows, dropped_errors)."""
    all_fields: list[str] = []
    rows: list[dict] = []
    seen: set[str] = set()
    dropped_errors = 0

    def accept(row: dict) -> bool:
        nonlocal dropped_errors
        # Status check MUST come first — failed rows often have empty
        # filename, which would otherwise silently skip them.
        if row.get("status", "").strip() != SUCCESS_STATUS:
            dropped_errors += 1
            return False
        fn = row.get("filename", "").strip()
        if not fn or fn in seen:
            return False
        seen.add(fn)
        return True

    existing_local = local_mf.exists()
    if existing_local:
        fields, local_rows = read_csv(local_mf)
        all_fields = fields
        for row in local_rows:
            if accept(row):
                rows.append(row)

    local_count = len(rows)
    added = 0
    for src in source_mfs:
        if not src.exists():
            continue
        fields, src_rows = read_csv(src)
        if not all_fields:
            all_fields = fields
        elif fields != all_fields:
            print(f"  SCHEMA MISMATCH in {src}: expected {all_fields}, got {fields}",
                  file=sys.stderr)
            raise SystemExit(2)
        for row in src_rows:
            if accept(row):
                rows.append(row)
                added += 1

    if not all_fields:
        return 0, 0, 0, dropped_errors

    # Write merged file
    tmp = local_mf.with_suffix(".csv.merged")
    local_mf.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in all_fields})

    # Back up original if it exists, then atomic rename
    if existing_local:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bak = local_mf.with_suffix(f".csv.bak.{ts}")
        shutil.copy2(local_mf, bak)
    tmp.replace(local_mf)
    return local_count, added, len(rows), dropped_errors


@click.command()
@click.option("--local", type=click.Path(path_type=Path), required=True,
              help="Local youtube root (contains CNN_* subdirs with manifest.csv)")
@click.option("--source", "sources", type=click.Path(path_type=Path), multiple=True, required=True,
              help="NAS source root — same CNN_* layout. Pass multiple times.")
def main(local: Path, sources: tuple[Path, ...]):
    # Category set = union of all subdirs across local + sources
    cats: set[str] = set()
    for root in [local, *sources]:
        if root.exists():
            for p in root.iterdir():
                if p.is_dir() and p.name.startswith("C"):
                    cats.add(p.name)
    cats_sorted = sorted(cats)

    local_manifest_dir = local / "download_manifests"
    local_manifest_dir.mkdir(parents=True, exist_ok=True)
    print(f"merging {len(cats_sorted)} categories from "
          f"{len(sources)} sources into {local_manifest_dir}")

    # Use parent directory name as source label (distinguishes Hamed vs Aref
    # when both sources are literally called "youtube_downloads").
    def src_label(p: Path) -> str:
        return p.parent.name if p.parent.name else p.name

    total_added = 0
    total_rows = 0
    total_dropped = 0
    for cat in cats_sorted:
        local_mf = local_manifest_dir / f"{cat}.csv"
        source_mfs = [s / cat / "manifest.csv" for s in sources]
        try:
            before, added, after, dropped = merge_category(local_mf, source_mfs)
        except SystemExit:
            print(f"  {cat}: ABORT — schema mismatch")
            sys.exit(2)
        total_added += added
        total_rows += after
        total_dropped += dropped
        src_present = [src_label(s) for s, p in zip(sources, source_mfs) if p.exists()]
        print(f"  {cat:30s}  local={before:>5d}  +added={added:>4d}  "
              f"total={after:>5d}  err_dropped={dropped:>3d}  "
              f"sources=[{','.join(src_present) or '-'}]")
    print(f"\ntotal added: {total_added}  err rows dropped: {total_dropped}  "
          f"final manifest rows: {total_rows}")


if __name__ == "__main__":
    main()
