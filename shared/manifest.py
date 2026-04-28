"""Manifest dataclass + read/write helpers for video generation runs."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


MANIFEST_FIELDS = [
    "real_clip", "first_frame", "last_frame",
    "prompt_source", "prompt_preview",
    "output_path", "duration_s", "status",
    "model_name", "elapsed_s", "error",
]


@dataclass
class ClipJob:
    real_clip: Path
    first_frame: Path
    last_frame: Path
    prompt: str
    duration: float


def load_processed(manifest_path: Path) -> set[str]:
    """Load clip names that have already been processed from a manifest."""
    if not manifest_path.exists():
        return set()
    processed = set()
    with open(manifest_path) as f:
        for row in csv.DictReader(f):
            rc = row.get("real_clip", "")
            if rc and row.get("status") in ("generated", "failed_permanent"):
                processed.add(rc)
    return processed


def append_manifest(manifest_path: Path, row: dict):
    write_header = not manifest_path.exists()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if write_header:
            w.writeheader()
        w.writerow(row)
