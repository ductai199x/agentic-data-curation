"""Closed-model collection: pull samples from official galleries, model pages and public posts, with provenance.

Each profile lists COLLECT_SOURCES; each source names an adapter:
- url_list: download URLs from a curated text/CSV file (one per line: url[,post_date[,page_url]]).
  Honors robots.txt, rate-limits, records source URL + timestamp per sample.
- repo_scraper: run one of the repo's existing scrapers (civitai, higgsfield, recraft, ...) as a command, then
  register the rows it added to data/<generator>/manifest.csv as samples of this run.
Sources whose terms bar automated collection are skipped unless Tai lists them in ADAPT_ALLOW_SOURCES.
"""

import csv
import json
import os
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from adapt.store import SampleStore

USER_AGENT = "DataCuration/1.0 (research; image dataset collection)"  # same UA as scrapers/base.py

# Terms status per source family: ok | check | restricted | barred. A summary, not legal advice; verify with counsel.
SOURCE_TERMS = {
    "twitter": ("barred", "X terms bar crawling or scraping without prior written consent"),
    "instagram": ("barred", "Meta terms bar automated collection without permission"),
    "discord": ("barred", "Discord terms bar self-bots and automated user accounts"),
    "reddit": ("restricted", "Reddit Data API terms; commercial use needs Reddit's approval"),
    "civitai": ("check", "on-site generation gallery; check current terms before commercial use"),
    "higgsfield": ("check", "community gallery API; check current terms before commercial use"),
    "official_gallery": ("check", "maker's own showcase; robots.txt enforced, check site terms"),
    "model_page": ("check", "maker's model page or blog examples; robots.txt enforced"),
}


def source_allowed(source: str) -> tuple[bool, str]:
    family = source.split(":")[0].split("_")[0] if source not in SOURCE_TERMS else source
    status, note = SOURCE_TERMS.get(source, SOURCE_TERMS.get(family, ("check", "unknown source; check terms")))
    allow = {s.strip() for s in os.environ.get("ADAPT_ALLOW_SOURCES", "").split(",") if s.strip()}
    if status == "barred" and source not in allow and family not in allow:
        return False, f"skipped: {note} (add to ADAPT_ALLOW_SOURCES to override)"
    return True, f"{status}: {note}"


class RobotsCache:
    def __init__(self):
        self.parsers: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        host = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        if host not in self.parsers:
            parser = RobotFileParser()
            try:
                resp = requests.get(f"{host}/robots.txt", timeout=15, headers={"User-Agent": USER_AGENT})
                parser.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                parser.parse([])
            self.parsers[host] = parser
        return self.parsers[host].can_fetch(USER_AGENT, url)


def _ext(url: str, content_type: str, modality: str) -> str:
    ct, path = content_type.lower(), urlparse(url).path.lower()
    for ext in (".mp4", ".webm", ".mov", ".png", ".webp", ".jpg", ".jpeg"):
        if path.endswith(ext) or ext.strip(".") in ct: return ".jpg" if ext == ".jpeg" else ext
    return ".mp4" if modality == "video" else ".jpg"


def collect_url_list(source_cfg: dict, profile, store: SampleStore, run_id: str, n: int, base_dir: Path) -> dict:
    path = Path(source_cfg["path"]); path = path if path.is_absolute() else base_dir / path
    rows = [r for r in csv.reader(open(path)) if r and not r[0].startswith("#")]
    robots, session = RobotsCache(), requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    delay = source_cfg.get("delay", (1.0, 3.0))
    stats = {"downloaded": 0, "robots_disallowed": 0, "duplicate": 0, "failed": 0}
    for row in rows:
        if stats["downloaded"] >= n: break
        url, post_date, page_url = (row + ["", ""])[:3]
        if store.has_url(url): stats["duplicate"] += 1; continue
        if not robots.allowed(url): stats["robots_disallowed"] += 1; continue
        for attempt in range(4):  # backoff on 429, like the repo scrapers
            try:
                resp = session.get(url, timeout=60)
                if resp.status_code == 429: time.sleep(2 ** (attempt + 2)); continue
                resp.raise_for_status()
                added = store.add(resp.content, _ext(url, resp.headers.get("content-type", ""), profile.MODALITY), url=url,
                                  source=source_cfg.get("source", "official_gallery"), run_id=run_id, modality=profile.MODALITY,
                                  post_date=post_date, page_url=page_url, backend="download")
                stats["downloaded" if added else "duplicate"] += 1
                break
            except requests.RequestException:
                if attempt == 3: stats["failed"] += 1
        time.sleep(random.uniform(*delay))
    return stats


def collect_repo_scraper(source_cfg: dict, profile, store: SampleStore, run_id: str, n: int, base_dir: Path) -> dict:
    before = set(store.hashes)
    command = [part.format(n=n, output=str(store.dir), generator=profile.NAME) for part in source_cfg["command"]]
    result = subprocess.run(command, cwd=source_cfg.get("cwd", base_dir))
    # adopt rows the scraper appended to manifest.csv as this run's samples
    adopted = 0
    known = {s["sha256"] for s in store.samples()}
    for row in csv.DictReader(open(store.manifest_path)) if store.manifest_path.exists() else []:
        if row["content_hash"] in before or row["content_hash"] in known: continue
        with open(store.samples_path, "a") as f:
            f.write(json.dumps({"filename": row["filename"], "sha256": row["content_hash"], "url": row["url"],
                                "source": row["source"] or source_cfg.get("source", ""), "run_id": run_id,
                                "modality": profile.MODALITY, "collected_at": row["timestamp"], "post_date": row.get("post_date", ""),
                                "width": row.get("width"), "height": row.get("height"), "backend": "repo_scraper"}) + "\n")
        adopted += 1
    return {"returncode": result.returncode, "adopted": adopted}


ADAPTERS = {"url_list": collect_url_list, "repo_scraper": collect_repo_scraper}


def collect_closed(profile, store: SampleStore, run_id: str, n: int, base_dir: Path) -> list[dict]:
    report = []
    sources = profile.COLLECT_SOURCES
    per_source = max(1, n // max(1, len(sources)))
    for source_cfg in sources:
        source = source_cfg.get("source", source_cfg["adapter"])
        ok, note = source_allowed(source)
        entry = {"source": source, "adapter": source_cfg["adapter"], "terms": note,
                 "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if ok: entry["stats"] = ADAPTERS[source_cfg["adapter"]](source_cfg, profile, store, run_id, per_source, base_dir)
        report.append(entry)
    return report
