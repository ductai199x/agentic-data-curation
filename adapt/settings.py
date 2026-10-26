"""Paths and environment for the adaptation pipeline.

Everything is overridable by env var so the same code runs in the repo, on the GPU box, or in a dry run.
Secrets (HF_TOKEN, CIVITAI_API_KEY, ...) are only ever read from the environment, never written anywhere.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from shared.paths import DATA_DIR, REPO_ROOT


@dataclass
class Settings:
    root: Path              # pipeline working root (runs/, batches/, logs/, ...), default data/adapt
    data_root: Path         # repo data/ (images under data/images/<gen>, videos under data/videos/fake/<gen>)
    release_log: Path       # configs/adapt/releases.md, appended from the generator watch posts
    profiles_dir: Path      # configs/adapt/profiles/<generator>.py
    real_eval_dir: Path | None  # real images/videos for AUC (never trained on)

    def media_dir(self, generator: str, modality: str) -> Path:
        return self.data_root / ("videos/fake" if modality == "video" else "images") / generator

    @property
    def comfy_configs_dir(self) -> Path: return self.root / "comfy_configs"
    @property
    def runs_dir(self) -> Path: return self.root / "runs"
    @property
    def batches_dir(self) -> Path: return self.root / "batches"
    @property
    def logs_dir(self) -> Path: return self.root / "logs"
    @property
    def timeline_path(self) -> Path: return self.logs_dir / "time_to_adapt.jsonl"
    @property
    def state_path(self) -> Path: return self.root / "state" / "release_log_seen.json"
    @property
    def phash_index_path(self) -> Path: return self.root / "index" / "phash_index.csv"
    @property
    def regression_index_path(self) -> Path: return self.root / "index" / "regression_set.csv"
    @property
    def models_path(self) -> Path: return self.root / "models.json"
    @property
    def notifications_dir(self) -> Path: return self.root / "notifications"
    @property
    def reports_dir(self) -> Path: return self.root / "reports"


def load_settings(root: str | Path | None = None) -> Settings:
    data_root = Path(os.environ.get("ADAPT_DATA_ROOT", DATA_DIR)).resolve()
    root = Path(root or os.environ.get("ADAPT_ROOT", data_root / "adapt")).resolve()
    real_eval = os.environ.get("ADAPT_REAL_EVAL_DIR")
    return Settings(
        root=root,
        data_root=data_root,
        release_log=Path(os.environ.get("ADAPT_RELEASE_LOG", REPO_ROOT / "configs/adapt/releases.md")),
        profiles_dir=Path(os.environ.get("ADAPT_PROFILES_DIR", REPO_ROOT / "configs/adapt/profiles")),
        real_eval_dir=Path(real_eval).resolve() if real_eval else None,
    )


def slugify(name: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "_" for c in name)
    while "__" in out: out = out.replace("__", "_")
    return out.strip("_")
