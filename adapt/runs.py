"""Per-run state: runs/<run_id>/run.json records the release entry and which stages finished.

Every stage checks run.json first and skips if already done (resumable from any point, like the scrapers).
"""

import json
from dataclasses import asdict
from pathlib import Path

from adapt.release_log import ReleaseEntry
from adapt.settings import Settings
from adapt.timeline import now_iso

STAGES = ["collect", "dedupe", "batch", "eval_before", "train", "eval_after"]


class Run:
    def __init__(self, settings: Settings, run_id: str):
        self.settings, self.run_id = settings, run_id
        self.dir = settings.runs_dir / run_id
        self.path = self.dir / "run.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}

    @classmethod
    def create(cls, settings: Settings, entry: ReleaseEntry, profile_name: str, dry_run: bool = False) -> "Run":
        run = cls(settings, entry.run_id)
        if not run.state:
            run.state = {"run_id": entry.run_id, "entry": asdict(entry), "profile": profile_name, "dry_run": dry_run,
                         "created_at": now_iso(), "stages": {}}
            run.save()
        return run

    @property
    def exists(self) -> bool: return bool(self.state)
    @property
    def dry_run(self) -> bool: return self.state.get("dry_run", False)
    @property
    def entry(self) -> ReleaseEntry: return ReleaseEntry(**self.state["entry"])
    @property
    def generator(self) -> str: return self.state["profile"]

    def done(self, stage: str) -> bool:
        return self.state["stages"].get(stage, {}).get("status") == "done"

    def mark(self, stage: str, status: str = "done", **details):
        assert stage in STAGES, stage
        self.state["stages"][stage] = {"status": status, "at": now_iso(), **details}
        self.save()

    def info(self, stage: str) -> dict:
        return self.state["stages"].get(stage, {})

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=1))


def list_runs(settings: Settings) -> list[Run]:
    if not settings.runs_dir.exists(): return []
    return [Run(settings, p.name) for p in sorted(settings.runs_dir.iterdir()) if (p / "run.json").exists()]
