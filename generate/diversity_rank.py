"""Produce a deterministic diversity ranking over labeled clips.

Round-robin stratified sort:
  1. Group all clips by content category
  2. Within each content bin, group by motion
  3. Within each (content, motion) cell, sort by stem (deterministic tiebreak)
  4. Outer round-robin across content bins
  5. Inner round-robin across motion bins
  6. Clips with missing labels (`?`) go last, still ranked for completeness

Result: a total ordering where `top-K` is always a strict subset of `top-(K+1)`.
Re-runs with an expanded labels file are stable: the ranks of previously-labeled
clips only shift if new clips fill earlier positions in the round-robin (fair
game at a new K).

Usage:
    uv run python -m generate.diversity_rank \\
        --labels data/videos/real/instagram/taxonomy_labels.csv \\
        --out data/videos/real/instagram/diversity_rank.csv
"""

from __future__ import annotations

import click
import csv
from collections import defaultdict
from pathlib import Path

from generate.taxonomy import CONTENT_IDS, MOTION_IDS

RANK_FIELDS = ["rank", "stem", "content", "motion", "confidence"]


def load_labels(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def round_robin_rank(rows: list[dict]) -> list[dict]:
    """Apply stratified round-robin over (content, motion) cells.

    Rows with content='?' or motion='?' are bucketed into a special "unknown"
    slot at the end. Well-labeled rows come first in round-robin order.
    """
    # --- 1. Bucket by (content, motion). Stems sorted inside each cell. ---
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    unknown: list[dict] = []
    for row in rows:
        c = row.get("content", "?")
        m = row.get("motion", "?")
        if c in CONTENT_IDS and m in MOTION_IDS:
            cells[(c, m)].append(row)
        else:
            unknown.append(row)
    for cell in cells.values():
        cell.sort(key=lambda r: r["stem"])
    unknown.sort(key=lambda r: r["stem"])

    # --- 2. Round-robin: outer over content (fixed taxonomy order), ---
    #       inner over motion (fixed taxonomy order), cycling through each
    #       cell's clips until all cells are drained.
    ordered: list[dict] = []

    max_per_cell = max((len(c) for c in cells.values()), default=0)
    for depth in range(max_per_cell):
        for content_id in CONTENT_IDS:
            for motion_id in MOTION_IDS:
                cell = cells.get((content_id, motion_id))
                if cell and depth < len(cell):
                    ordered.append(cell[depth])

    # --- 3. Unknown rows at the end, stable-sorted by stem. ---
    ordered.extend(unknown)

    # --- 4. Assign ranks (1-indexed, dense). ---
    for rank, row in enumerate(ordered, start=1):
        row["rank"] = rank
    return ordered


def write_rank(rows: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RANK_FIELDS)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in RANK_FIELDS})


def print_summary(rows: list[dict]):
    by_content: dict[str, int] = defaultdict(int)
    by_motion: dict[str, int] = defaultdict(int)
    unknown = 0
    for r in rows:
        c = r.get("content", "?")
        m = r.get("motion", "?")
        if c == "?" or m == "?":
            unknown += 1
            continue
        by_content[c] += 1
        by_motion[m] += 1

    print(f"\ntotal: {len(rows)}  (well-labeled: {len(rows) - unknown}, unknown: {unknown})")
    print("\ncontent distribution:")
    for cid in CONTENT_IDS:
        n = by_content.get(cid, 0)
        bar = "█" * min(n, 50)
        print(f"  {cid:3s}  {n:5d}  {bar}")
    print("\nmotion distribution:")
    for mid in MOTION_IDS:
        n = by_motion.get(mid, 0)
        bar = "█" * min(n, 50)
        print(f"  {mid:3s}  {n:5d}  {bar}")


@click.command()
@click.option("--labels", type=click.Path(path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--quiet", is_flag=True)
def main(labels: Path, out: Path, quiet: bool):
    rows = load_labels(labels)
    print(f"loaded {len(rows)} labels from {labels}")

    ranked = round_robin_rank(rows)
    write_rank(ranked, out)
    print(f"wrote {out} ({len(ranked)} ranked rows)")
    if not quiet:
        print_summary(ranked)


if __name__ == "__main__":
    main()
