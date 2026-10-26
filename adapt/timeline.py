"""Time-to-adapt log: one JSON line per pipeline event, append-only.

Events per run (in order): release (when the maker shipped it), detected (when the watch logged it),
first_samples, batch_ready, eval_before, train_started, model_updated, eval_after.
Time to adapt = model_updated - release; if the old model already detects the generator, it is 0.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

EVENT_ORDER = ["release", "detected", "first_samples", "batch_ready", "eval_before",
               "train_started", "model_updated", "eval_after"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def log_event(timeline_path: Path, run_id: str, event: str, at: str | None = None, dry_run: bool = False, **details):
    assert event in EVENT_ORDER, f"unknown event {event}"
    timeline_path.parent.mkdir(parents=True, exist_ok=True)
    row = {"run_id": run_id, "event": event, "at": at or now_iso(), "dry_run": dry_run, **details}
    with open(timeline_path, "a") as f: f.write(json.dumps(row) + "\n")
    return row


def load_events(timeline_path: Path) -> dict[str, dict[str, dict]]:
    # run_id -> event -> latest row (re-running a stage overwrites the earlier timestamp)
    runs: dict[str, dict[str, dict]] = {}
    if not timeline_path.exists(): return runs
    for line in timeline_path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            runs.setdefault(row["run_id"], {})[row["event"]] = row
    return runs


def has_event(timeline_path: Path, run_id: str, event: str) -> bool:
    return event in load_events(timeline_path).get(run_id, {})


def hours_between(start: str | None, end: str | None) -> float | None:
    if not start or not end: return None
    return (parse_time(end) - parse_time(start)).total_seconds() / 3600
