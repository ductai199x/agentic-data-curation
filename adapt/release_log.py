"""Trigger: turn new entries in the generator watch log into pipeline runs.

The watch writes a markdown log. Accepted row shapes (header names are matched loosely):
  | 2026-10-09 | Qwen-Image-2.1-Turbo | Alibaba Qwen | image | open | https://... |
  - 2026-10-09 | Qwen-Image-2.1-Turbo | Alibaba Qwen | image | open
Columns: date (release), name, maker, modality, optional weights (open/closed), optional link,
optional detected_at (when the watch saw it). Entries already handled are tracked in state/.
"""

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

from adapt.settings import Settings, slugify

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?(Z|[+-]\d{2}:?\d{2})?$")
HEADER_ALIASES = {
    "date": "release_date", "released": "release_date", "release": "release_date", "release date": "release_date",
    "name": "name", "generator": "name", "model": "name",
    "maker": "maker", "company": "maker", "lab": "maker",
    "modality": "modality", "type": "modality",
    "weights": "weights", "open": "weights", "access": "weights",
    "link": "link", "url": "link", "source": "link",
    "detected": "detected_at", "detected_at": "detected_at", "seen": "detected_at", "logged": "detected_at",
}
DEFAULT_COLUMNS = ["release_date", "name", "maker", "modality", "weights", "link", "detected_at"]


@dataclass
class ReleaseEntry:
    release_date: str
    name: str
    maker: str = ""
    modality: str = "image"
    weights: str = "unknown"   # open | closed | unknown
    link: str = ""
    detected_at: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str: return f"{self.release_date[:10]}|{slugify(self.name)}"

    @property
    def run_id(self) -> str: return f"{slugify(self.name)}_{self.release_date[:10].replace('-', '')}"


def _cells(line: str) -> list[str]:
    line = line.strip().lstrip("-*").strip()
    return [c.strip() for c in line.strip("|").split("|")]


def _normalize(entry: dict) -> ReleaseEntry:
    modality = entry.get("modality", "image").lower()
    modality = "video" if "video" in modality else "image"
    weights = entry.get("weights", "").lower()
    weights = "open" if "open" in weights else "closed" if any(w in weights for w in ("closed", "api", "proprietary")) else "unknown"
    link = re.sub(r"^\[.*?\]\((.*)\)$", r"\1", entry.get("link", ""))  # markdown link -> url
    known = set(DEFAULT_COLUMNS)
    return ReleaseEntry(release_date=entry["release_date"], name=entry["name"], maker=entry.get("maker", ""),
                        modality=modality, weights=weights, link=link, detected_at=entry.get("detected_at", ""),
                        extra={k: v for k, v in entry.items() if k not in known})


def parse_release_log(text: str) -> list[ReleaseEntry]:
    columns, entries = DEFAULT_COLUMNS, []
    for line in text.splitlines():
        if "|" not in line or set(line.strip()) <= set("|-: "): continue
        cells = _cells(line)
        if not DATE_RE.match(cells[0]):
            mapped = [HEADER_ALIASES.get(c.lower()) for c in cells]
            if "name" in mapped: columns = [m or f"col{i}" for i, m in enumerate(mapped)]
            continue
        row = {col: cell for col, cell in zip(columns, cells) if cell}
        if "name" in row: entries.append(_normalize(row))
    return entries


def _load_seen(settings: Settings) -> dict:
    return json.loads(settings.state_path.read_text()) if settings.state_path.exists() else {}


def new_entries(settings: Settings, log_path: Path | None = None) -> list[ReleaseEntry]:
    log_path = log_path or settings.release_log
    if not log_path.exists(): return []
    seen = _load_seen(settings)
    return [e for e in parse_release_log(log_path.read_text()) if e.key not in seen]


def mark_seen(settings: Settings, entry: ReleaseEntry, run_id: str):
    seen = _load_seen(settings)
    seen[entry.key] = {"run_id": run_id, **asdict(entry)}
    settings.state_path.parent.mkdir(parents=True, exist_ok=True)
    settings.state_path.write_text(json.dumps(seen, indent=1))
