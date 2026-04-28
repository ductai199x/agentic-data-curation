"""Identify + delete stretched OSS outputs so the workers re-generate them
with the aspect-fixed workflows on resume.

A clip is "stretched" iff its output aspect ratio differs from its source
clip's aspect ratio by more than `TOL` (default 3%). Within-aspect
resolution changes (e.g. source 1080×1920 → output 720×1280, both 9:16)
are NOT stretched.

For each stretched output:
  1. Delete the .mp4
  2. Remove its row from any manifest CSV in the same output_dir
     (so load_processed() stops skipping it on resume)

Usage:
    uv run python -m scripts.regen_stretched \\
        --output-dir data/videos/fake/wan_2_2/instagram \\
        --source-dir data/videos/real/instagram/validated \\
        [--dry-run]

On resume, just re-launch the generic worker via scripts/launch.sh with the
matching COMFY_CONFIG — it reads the per-shard manifest via load_processed(),
finds the deleted rows missing, and the out_path.exists() check also sees
the missing mp4, so it naturally re-queues only the stretched subset.
"""
from __future__ import annotations

import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click
import cv2
from tqdm import tqdm

from video_gen.common import is_source_clip


TOL = 0.03  # aspect-ratio equality tolerance (3%). 9:16=0.5625 vs 4:5=0.8 is 42% diff — easily caught.
WORKERS = 256  # threads for in-process header reads


def probe_dims(path: Path) -> tuple[int, int] | None:
    """Read width×height via OpenCV (reads mp4 atom header in-process —
    ~100× faster than forking ffprobe for each file)."""
    try:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap.release()
            return None
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        if w <= 0 or h <= 0:
            return None
        return w, h
    except Exception:
        return None


def ar(dims: tuple[int, int]) -> float:
    w, h = dims
    return w / max(h, 1)


def find_stretched(output_dir: Path, source_dir: Path) -> list[Path]:
    """Return the subset of output mp4s whose aspect differs from source by >TOL.

    Parallelized via ThreadPoolExecutor — OpenCV releases the GIL during IO
    so threads scale well for this workload.
    """
    outputs = sorted(p for p in output_dir.glob("*.mp4") if is_source_clip(p))
    pairs: list[tuple[Path, Path]] = []
    missing_source = 0
    for mp4 in outputs:
        src = source_dir / f"{mp4.stem}.mp4"
        if src.exists():
            pairs.append((mp4, src))
        else:
            missing_source += 1

    # Batch-probe all sources + outputs in parallel
    probe_paths: set[Path] = set()
    for mp4, src in pairs:
        probe_paths.add(mp4)
        probe_paths.add(src)
    probe_list = list(probe_paths)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        dims = list(tqdm(pool.map(probe_dims, probe_list),
                         total=len(probe_list), desc="probing dims", unit="mp4"))
    dims_by_path = dict(zip(probe_list, dims))

    stretched: list[Path] = []
    aspect_ok = 0
    unreadable = 0
    for mp4, src in pairs:
        s_dims = dims_by_path.get(src)
        o_dims = dims_by_path.get(mp4)
        if s_dims is None or o_dims is None:
            unreadable += 1
            continue
        s_ar = ar(s_dims)
        o_ar = ar(o_dims)
        if abs(s_ar - o_ar) / s_ar > TOL:
            stretched.append(mp4)
        else:
            aspect_ok += 1

    print(f"scanned:          {len(pairs)} pairs ({len(outputs)} output mp4s)", flush=True)
    print(f"  aspect OK:      {aspect_ok}")
    print(f"  aspect off >3%: {len(stretched)}  (will be deleted)")
    print(f"  missing source: {missing_source}  (skipped)")
    print(f"  unreadable:     {unreadable}  (skipped)")
    return stretched


def purge_manifest_rows(output_dir: Path, stems: set[str], dry_run: bool) -> int:
    """For every manifest CSV in output_dir, remove rows whose real_clip stem
    is in `stems`. Returns total removed. Preserves header + column order.

    Write strategy: read all rows into memory, then atomic replace via
    {manifest}.tmp. Backup of original is saved once as {manifest}.bak.
    """
    from datetime import datetime, timezone
    removed_total = 0
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for mf in sorted(output_dir.glob("manifest*.csv")):
        if mf.suffix.endswith(".bak") or ".bak." in mf.name:
            continue  # ignore prior backups
        with open(mf) as f:
            reader = csv.DictReader(f)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
        def stem_of(row: dict) -> str:
            rc = row.get("real_clip", "")
            return rc[:-4] if rc.endswith(".mp4") else rc
        keep = [row for row in rows if stem_of(row) not in stems]
        removed_here = len(rows) - len(keep)
        if removed_here == 0:
            continue
        if dry_run:
            print(f"  [dry-run] would drop {removed_here} rows from {mf.name}")
        else:
            bak = mf.with_suffix(f".csv.bak.{ts}")
            tmp = mf.with_suffix(".csv.tmp")
            # Copy original to backup first (safer than rename)
            import shutil
            shutil.copy2(mf, bak)
            with open(tmp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                for row in keep:
                    w.writerow({k: row.get(k, "") for k in fields})
            tmp.replace(mf)
            print(f"  dropped {removed_here} rows from {mf.name} (backup: {bak.name})")
        removed_total += removed_here
    return removed_total


@click.command()
@click.option("--output-dir", type=click.Path(file_okay=False, path_type=Path),
              required=True, help="e.g. data/videos/fake/wan_2_2/instagram")
@click.option("--source-dir", type=click.Path(file_okay=False, path_type=Path),
              required=True, help="e.g. data/videos/real/instagram/validated")
@click.option("--dry-run", is_flag=True, help="Print plan, don't delete anything")
def main(output_dir: Path, source_dir: Path, dry_run: bool):
    if not output_dir.is_dir():
        click.echo(f"ERR: output dir not found: {output_dir}", err=True)
        sys.exit(2)
    if not source_dir.is_dir():
        click.echo(f"ERR: source dir not found: {source_dir}", err=True)
        sys.exit(2)

    print(f"scanning {output_dir} vs {source_dir} (tolerance={TOL:.0%})")
    stretched = find_stretched(output_dir, source_dir)
    if not stretched:
        print("nothing stretched — nothing to do.")
        return

    # Preview the worst offenders so you can sanity-check before deleting
    print("\nsample of stretched (first 10):")
    for mp4 in stretched[:10]:
        src = source_dir / mp4.name
        s_dims = probe_dims(src) or (0, 0)
        o_dims = probe_dims(mp4) or (0, 0)
        print(f"  {mp4.name}  src={s_dims[0]}×{s_dims[1]} → out={o_dims[0]}×{o_dims[1]}")

    if dry_run:
        print(f"\n[dry-run] would delete {len(stretched)} mp4s + purge manifest rows")
        purge_manifest_rows(output_dir, {mp4.stem for mp4 in stretched}, dry_run=True)
        return

    # Confirm before destructive action
    print(f"\nDELETING {len(stretched)} stretched mp4s in 3 seconds. Ctrl-C to abort.",
          flush=True)
    import time
    time.sleep(3)

    deleted = 0
    for mp4 in stretched:
        try:
            mp4.unlink()
            deleted += 1
        except Exception as e:
            print(f"  failed to delete {mp4}: {e}")

    print(f"deleted {deleted} mp4s")
    purged = purge_manifest_rows(output_dir, {mp4.stem for mp4 in stretched}, dry_run=False)
    print(f"purged {purged} manifest rows")
    print("\ndone. Re-launch the worker to backfill:")
    print(f"  COMFY_CONFIG=configs.<matching> scripts/launch.sh start")
    print(f"    (workers skip existing mp4s and re-gen the deleted ones)")


if __name__ == "__main__":
    main()
