"""Sample storage in the repo's layout.

Images: data/images/<generator>/staging/<sha256[:16]><ext> + manifest.csv with the scrapers' MANIFEST_FIELDS, so
the existing validators (JoyCaption, structural, FSD) run on pipeline samples unchanged.
Videos: generate/'s ComfyUI workers already write data/videos/fake/<generator>/<source>/<stem>.mp4; those files are
registered in place. Either way, pipeline-only fields (run_id, prompt, seed, backend, paired real clip) go to
samples.jsonl in the generator's folder.
"""

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from curate.images.scrapers.base import MANIFEST_FIELDS


def sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): hasher.update(chunk)
    return hasher.hexdigest()


class SampleStore:
    def __init__(self, media_dir: Path):
        self.dir = media_dir
        self.staging_dir = self.dir / "staging"
        self.manifest_path = self.dir / "manifest.csv"
        self.samples_path = self.dir / "samples.jsonl"
        self.hashes, self.urls, self.sample_keys = set(), set(), set()
        if self.manifest_path.exists():
            for row in csv.DictReader(open(self.manifest_path)):
                if "content_hash" in row: self.hashes.add(row["content_hash"]); self.urls.add(row["url"])
        for row in self.samples():
            self.hashes.add(row["sha256"]); self.urls.add(row.get("url", ""))
            if row.get("sample_key"): self.sample_keys.add(row["sample_key"])

    def has_key(self, sample_key: str) -> bool: return sample_key in self.sample_keys
    def has_url(self, url: str) -> bool: return url in self.urls

    def _append_sample(self, row: dict):
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.samples_path, "a") as f: f.write(json.dumps(row) + "\n")
        self.hashes.add(row["sha256"]); self.urls.add(row.get("url", ""))
        if row.get("sample_key"): self.sample_keys.add(row["sample_key"])

    def add(self, data: bytes, ext: str, url: str, source: str, run_id: str, modality: str,
            sample_key: str = "", post_date: str = "", **extra) -> Path | None:
        # write bytes content-addressed into staging/ and log them in both manifests
        digest = hashlib.sha256(data).hexdigest()
        if digest in self.hashes: return None
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{digest[:16]}{ext}"
        path = self.staging_dir / filename
        path.write_bytes(data)
        width = height = 0; fmt = ext.lstrip(".").upper()
        if modality == "image":
            try:
                with Image.open(path) as img: (width, height), fmt = img.size, img.format or fmt
            except Exception: pass
        timestamp = datetime.now(timezone.utc).isoformat()
        write_header = not self.manifest_path.exists()
        with open(self.manifest_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            if write_header: writer.writeheader()
            writer.writerow({"filename": filename, "url": url, "content_hash": digest, "source": source,
                             "post_title": str(extra.get("prompt", ""))[:200], "flair": extra.get("flair", ""),
                             "timestamp": timestamp, "status": "downloaded", "width": width, "height": height,
                             "format": fmt, "file_size": len(data), "post_date": post_date})
        self._append_sample({"filename": filename, "path": str(path), "sha256": digest, "url": url, "source": source,
                             "run_id": run_id, "modality": modality, "collected_at": timestamp, "sample_key": sample_key,
                             "post_date": post_date, "width": width, "height": height, **extra})
        return path

    def register(self, path: Path, url: str, source: str, run_id: str, modality: str, sample_key: str = "", **extra) -> bool:
        # log a file another tool already wrote (ComfyUI outputs, repo scrapers) as a sample of this run
        digest = sha256_of_file(path)
        if digest in self.hashes: return False
        self._append_sample({"filename": path.name, "path": str(path), "sha256": digest, "url": url, "source": source,
                             "run_id": run_id, "modality": modality, "sample_key": sample_key,
                             "collected_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), **extra})
        return True

    def samples(self, run_id: str | None = None) -> list[dict]:
        if not self.samples_path.exists(): return []
        rows = [json.loads(l) for l in self.samples_path.read_text().splitlines() if l.strip()]
        return [r for r in rows if run_id is None or r["run_id"] == run_id]
