"""Detector adapters for before/after scoring. Each scores a list of files -> {path: fake_score} (higher = more fake).

- command: Tai's own scorer. ADAPT_DETECT_CMD is a template, e.g.
    python score.py --checkpoint {checkpoint} --file-list {file_list} --out {out_csv}
  It must write a CSV with columns path,score (score higher = more fake; any monotone scale works for AUC).
- fsd: the fsd-score CLI already used by validators/pipeline.py; score = -z_score (more negative z = more fake).
- dummy: deterministic random scores, for dry runs only.
Model checkpoints are tracked in models.json: {"current": tag, "models": {tag: {"checkpoint": ..., ...}}}.
"""

import csv
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path

from adapt.timeline import now_iso


class ModelRegistry:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {"current": None, "models": {}}

    def register(self, tag: str, checkpoint: str, make_current: bool = True, **info):
        self.data["models"][tag] = {"checkpoint": checkpoint, "registered_at": now_iso(), **info}
        if make_current: self.data["current"] = tag
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=1))

    @property
    def current(self) -> str | None: return self.data["current"]

    def checkpoint(self, tag: str) -> str: return self.data["models"][tag]["checkpoint"]


class DummyDetector:
    name = "dummy"
    def __init__(self, checkpoint: str): self.checkpoint = checkpoint
    def score(self, paths: list[Path]) -> dict[str, float]:
        return {str(p): int(hashlib.md5(f"{self.checkpoint}:{p.name}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF for p in paths}


class CommandDetector:
    name = "command"
    def __init__(self, checkpoint: str):
        self.checkpoint, self.template = checkpoint, os.environ.get("ADAPT_DETECT_CMD")
        assert self.template, "set ADAPT_DETECT_CMD (see adapt/detectors.py)"

    def score(self, paths: list[Path]) -> dict[str, float]:
        with tempfile.TemporaryDirectory() as tmp:
            file_list, out_csv = Path(tmp) / "files.txt", Path(tmp) / "scores.csv"
            file_list.write_text("\n".join(str(p) for p in paths) + "\n")
            command = self.template.format(checkpoint=shlex.quote(self.checkpoint), file_list=file_list, out_csv=out_csv)
            subprocess.run(command, shell=True, check=True)
            return {r["path"]: float(r.get("score", r.get("fake_probability"))) for r in csv.DictReader(open(out_csv))}


class FsdDetector:
    name = "fsd"
    def __init__(self, checkpoint: str): self.checkpoint = checkpoint  # a --weights-dir

    def score(self, paths: list[Path]) -> dict[str, float]:
        by_dir, scores = defaultdict(list), {}
        for p in paths: by_dir[p.parent].append(p)
        for directory, wanted in by_dir.items():
            result = subprocess.run(["uv", "run", "fsd-score", "--dir", str(directory.resolve()), "--csv",
                                     "--weights-dir", self.checkpoint], capture_output=True, text=True, check=True)
            names = {p.name: p for p in wanted}
            for row in csv.DictReader(result.stdout.strip().splitlines()):
                name = Path(row["file"]).name
                if name in names: scores[str(names[name])] = -float(row["z_score"])
        return scores


DETECTORS = {"dummy": DummyDetector, "command": CommandDetector, "fsd": FsdDetector}


def make_detector(kind: str, checkpoint: str):
    return DETECTORS[kind](checkpoint)
