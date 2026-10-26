"""Near-duplicate removal with perceptual hashes (64-bit pHash; videos hash 3 frames at 10/50/90%).

Checked within the run and against a global index of every earlier batch and the regression set, so the same
picture reposted on two sites is kept once and nothing in a training split leaks into an eval split later.
"""

import csv
import json
import subprocess
import tempfile
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

INDEX_FIELDS = ["phash", "sha256", "generator", "run_id", "split", "path"]


def image_phash(path: Path) -> list[int]:
    with Image.open(path) as img: return [int(str(imagehash.phash(img.convert("RGB"))), 16)]


def video_phash(path: Path) -> list[int]:
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                    capture_output=True, text=True, check=True).stdout.strip() or 0)
    hashes = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, frac in enumerate((0.1, 0.5, 0.9)):
            frame = Path(tmp) / f"{i}.png"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{duration * frac:.3f}", "-i", str(path),
                            "-frames:v", "1", str(frame)], check=True)
            if frame.exists(): hashes += image_phash(frame)
    return hashes


def phash_of(path: Path, modality: str) -> list[int]:
    return video_phash(path) if modality == "video" else image_phash(path)


def _popcount(values: np.ndarray) -> np.ndarray:
    return np.unpackbits(values.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)


class PhashIndex:
    # hashes stored as hex strings joined by ';' (one per frame for video); distance = mean over frames
    def __init__(self, path: Path):
        self.path = path
        self.rows = list(csv.DictReader(open(path))) if path.exists() else []
        self.shas = {r["sha256"] for r in self.rows}
        self._first = np.array([int(r["phash"].split(";")[0], 16) for r in self.rows], dtype=np.uint64)

    def nearest(self, hashes: list[int]) -> tuple[int, dict | None]:
        if not len(self._first): return 64, None
        distances = _popcount(self._first ^ np.uint64(hashes[0]))
        best = int(distances.argmin())
        return int(distances[best]), self.rows[best]

    def add(self, hashes: list[int], **fields):
        row = {"phash": ";".join(f"{h:016x}" for h in hashes), **fields}
        self.rows.append(row); self.shas.add(fields["sha256"])
        self._first = np.append(self._first, np.uint64(hashes[0]))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS, extrasaction="ignore")
            writer.writeheader(); writer.writerows(self.rows)


def dedupe_run(samples: list[dict], global_index: PhashIndex, max_distance: int) -> list[dict]:
    # returns samples annotated with phash + dedupe status; does not touch the global index (batch.py adds kept rows)
    run_index = PhashIndex(Path("/nonexistent"))
    out = []
    for sample in samples:
        path = Path(sample["path"])
        if not path.exists():
            out.append({**sample, "dedupe": "missing"}); continue
        hashes = phash_of(path, sample["modality"])
        sample = {**sample, "phash": ";".join(f"{h:016x}" for h in hashes)}
        if sample["sha256"] in global_index.shas:
            owner = next(r for r in global_index.rows if r["sha256"] == sample["sha256"])
            if owner.get("run_id") == sample["run_id"]:  # re-run of this same batch: still ours
                run_index.add(hashes, sha256=sample["sha256"]); out.append({**sample, "dedupe": "kept"})
            else:
                out.append({**sample, "dedupe": f"already_indexed:{owner.get('generator')}"})
            continue
        d_run, hit_run = run_index.nearest(hashes)
        d_global, hit_global = global_index.nearest(hashes)
        if d_run <= max_distance:
            out.append({**sample, "dedupe": f"near_dup_in_run:{hit_run['sha256'][:16]}:d{d_run}"})
        elif d_global <= max_distance:
            out.append({**sample, "dedupe": f"near_dup_of_{hit_global['generator']}:{hit_global['sha256'][:16]}:d{d_global}"})
        else:
            run_index.add(hashes, sha256=sample["sha256"])
            out.append({**sample, "dedupe": "kept"})
    return out


def write_dedupe_report(rows: list[dict], path: Path):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
