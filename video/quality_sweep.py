"""Post-hoc sweep: apply `video.quality_filter` to already-validated clips.

Safe to run in parallel with a live validation pipeline — only reads clips,
moves failures to `<root>/rejected/<cat>/` (or a custom dir), and appends
a one-row CSV explaining why each clip was rejected.

Usage:
    uv run python -m video.quality_sweep \\
        --validated-root data/videos/real/youtube/validated \\
        --rejected-root data/videos/real/youtube/rejected_quality \\
        --workers 64

Dry-run (report only, don't move):
    uv run python -m video.quality_sweep --validated-root ... --dry-run
"""
from __future__ import annotations

import csv
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import click
from tqdm import tqdm

from video_gen.common import is_source_clip
from video.quality_filter import (
    MIN_BPPS,
    MIN_MEAN_LUM,
    MIN_MEAN_MOTION,
    check_quality,
)


REJECT_CSV_FIELDS = [
    "filename", "category", "reason",
    "bpps", "mbps", "mean_lum", "mean_motion_pct",
    "width", "height", "fps", "duration_s", "size_mb",
    "timestamp",
]


def _scan(args):
    path, min_b, min_l, min_m = args
    ok, reason, stats = check_quality(path, min_b, min_l, min_m)
    return path, ok, reason, stats


@click.command()
@click.option("--validated-root", type=click.Path(path_type=Path), required=True,
              help="e.g. data/videos/real/youtube/validated")
@click.option("--rejected-root", type=click.Path(path_type=Path), default=None,
              help="Where to move failed clips; default = <validated>/../rejected_quality")
@click.option("--workers", type=int, default=32,
              help="Parallel probe threads (OpenCV releases GIL, scale well)")
@click.option("--min-bpps", type=float, default=MIN_BPPS,
              help="Bits per pixel per second threshold (auto-adjusts for resolution)")
@click.option("--min-mean-lum", type=float, default=MIN_MEAN_LUM)
@click.option("--min-mean-motion", type=float, default=MIN_MEAN_MOTION)
@click.option("--category", default=None,
              help="Only scan this category (e.g. C18_weather_atmosphere)")
@click.option("--dry-run", is_flag=True, help="Report only, don't move anything")
def main(validated_root: Path, rejected_root: Path, workers: int,
         min_bpps: float, min_mean_lum: float, min_mean_motion: float,
         category: str | None, dry_run: bool):
    if not validated_root.is_dir():
        raise click.UsageError(f"validated-root not found: {validated_root}")
    rejected_root = rejected_root or (validated_root.parent / "rejected_quality")

    # Build work list
    if category:
        cat_dirs = [validated_root / category]
    else:
        cat_dirs = sorted(p for p in validated_root.iterdir() if p.is_dir())
    mp4s: list[Path] = []
    for d in cat_dirs:
        if d.is_dir():
            mp4s.extend(sorted(p for p in d.glob("*.mp4") if is_source_clip(p)))

    print(f"scanning {len(mp4s)} clips across {len(cat_dirs)} categories", flush=True)
    print(f"  thresholds: bpps>={min_bpps}  lum>={min_mean_lum}  motion>={min_mean_motion*100:.0f}%", flush=True)
    if dry_run:
        print(f"  [DRY RUN] — no files will be moved", flush=True)

    fails: list[tuple[Path, str, object]] = []
    args_iter = [(p, min_bpps, min_mean_lum, min_mean_motion) for p in mp4s]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pbar = tqdm(pool.map(_scan, args_iter), total=len(mp4s),
                    desc="quality sweep", unit="clip", smoothing=0.1)
        for path, ok, reason, stats in pbar:
            if not ok:
                fails.append((path, reason, stats))
            pbar.set_postfix(fails=len(fails), refresh=False)

    print(f"\ndone scanning. {len(fails)} / {len(mp4s)} failed quality gates", flush=True)
    if not fails:
        return

    # Write rejection report + move files
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = rejected_root / f"quality_sweep_{ts}.csv"
    rejected_root.mkdir(parents=True, exist_ok=True)

    with open(report_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REJECT_CSV_FIELDS)
        w.writeheader()
        for path, reason, stats in tqdm(fails, desc="moving rejects", unit="clip"):
            row = {
                "filename": path.name,
                "category": path.parent.name,
                "reason": reason,
                "bpps": f"{stats.bpps:.4f}" if stats else "",
                "mbps": f"{stats.mbps:.2f}" if stats else "",
                "mean_lum": f"{stats.mean_lum:.1f}" if stats else "",
                "mean_motion_pct": f"{stats.mean_motion*100:.2f}" if stats else "",
                "width": stats.width if stats else "",
                "height": stats.height if stats else "",
                "fps": f"{stats.fps:.1f}" if stats else "",
                "duration_s": f"{stats.duration:.1f}" if stats else "",
                "size_mb": f"{stats.size_mb:.1f}" if stats else "",
                "timestamp": ts,
            }
            w.writerow(row)
            if not dry_run:
                dst_dir = rejected_root / path.parent.name
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dst_dir / path.name))

    action = "would move" if dry_run else "moved"
    print(f"\n{action} {len(fails)} clips → {rejected_root}/")
    print(f"report: {report_path}")

    # Summary by category + reason
    by_cat: dict[str, int] = {}
    for path, _, _ in fails:
        by_cat[path.parent.name] = by_cat.get(path.parent.name, 0) + 1
    print("\nby category:")
    for cat, n in sorted(by_cat.items(), key=lambda kv: -kv[1]):
        print(f"  {cat:<30} {n:>5}")


if __name__ == "__main__":
    main()
