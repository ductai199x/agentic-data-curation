"""Ready-to-train batch: deduped, labeled samples split into train / val / eval_holdout, plus a manifest and a READY note.

Layout:
  batches/<generator>/<run_id>/
    train/ val/ eval_holdout/      # files (hardlinked from data/ when possible)
    manifest.csv                   # one row per file with labels and provenance (columns below)
    batch.json                     # counts, sources, license, dedupe summary
    READY.md                       # what's in it and the one command to train on it
eval_holdout never enters training: it scores this generator before/after and joins the regression set afterwards.
"""

import csv
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image

from adapt.dedupe import PhashIndex
from adapt.settings import Settings
from adapt.timeline import now_iso

BATCH_FIELDS = ["path", "split", "label", "generator", "generator_display", "modality", "source", "source_url", "page_url",
                "collected_at", "post_date", "processing_seen", "sha256", "phash", "width", "height", "prompt", "seed",
                "category", "backend", "paired_real", "license", "run_id", "dry_run"]
REGRESSION_FIELDS = ["path", "label", "generator", "run_id", "modality"]


def _hash_point(sha256: str) -> float:
    return int(hashlib.md5(sha256.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def assign_splits(shas: list[str], split: dict[str, float], eval_min: int = 30) -> dict[str, str]:
    # deterministic by content hash; eval_holdout gets at least min(eval_min, n/4) files so small batches still score
    ordered = sorted(shas, key=_hash_point)
    n = len(ordered)
    n_eval = max(round(split.get("eval_holdout", 0.1) * n), min(eval_min, n // 4))
    n_val = max(round(split.get("val", 0.1) * n), 1 if n >= 10 else 0)
    return {sha: "eval_holdout" if i < n_eval else "val" if i < n_eval + n_val else "train" for i, sha in enumerate(ordered)}


def _processing_seen(sample: dict, profile) -> str:
    if sample.get("backend") in ("diffusers", "procedural"):
        return "none:local_generation_mp4_crf10" if sample.get("modality") == "video" else "none:local_generation_png"
    if sample.get("backend") == "comfy": return "none:local_generation_comfy_h264"
    fmt = Path(sample["filename"]).suffix.lstrip(".").lower()
    seen = [f"served_as:{fmt}"]
    try:
        w, h = int(sample.get("width") or 0), int(sample.get("height") or 0)
        if w and h and (w, h) not in [tuple(r) for r in profile.RESOLUTIONS] and (h, w) not in [tuple(r) for r in profile.RESOLUTIONS]:
            seen.append("non_native_size")
    except (TypeError, ValueError): pass
    return ";".join(seen)


def _passes_structural(path: Path, sample: dict, profile) -> tuple[bool, str]:
    # light stand-in for validators/ (JoyCaption + structural + FSD run there once integrated)
    if sample["modality"] == "video": return path.stat().st_size > 10_000, "video_too_small"
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            w, h = img.size
    except Exception: return False, "undecodable"
    return w * h >= profile.MIN_PIXELS, f"too_small:{w}x{h}"


def _place(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists(): return
    try: os.link(src, dst)
    except OSError: shutil.copy2(src, dst)


def build_batch(settings: Settings, run, profile, deduped: list[dict]) -> dict:
    generator = profile.NAME
    batch_dir = settings.batches_dir / generator / run.run_id
    index = PhashIndex(settings.phash_index_path)
    rows, rejected, accepted = [], Counter(), []
    for sample in deduped:
        if sample.get("dedupe") != "kept": rejected[sample.get("dedupe", "?").split(":")[0]] += 1; continue
        src = Path(sample["path"])
        ok, reason = _passes_structural(src, sample, profile)
        if not ok: rejected[reason.split(":")[0]] += 1; continue
        accepted.append(sample)
    splits = assign_splits([s["sha256"] for s in accepted], profile.SPLIT, getattr(profile, "EVAL_MIN", 30))
    for sample in accepted:
        src, split = Path(sample["path"]), splits[sample["sha256"]]
        dst = batch_dir / split / sample["filename"]
        _place(src, dst)
        rows.append({"path": str(dst), "split": split, "label": "fake", "generator": generator,
                     "generator_display": getattr(profile, "DISPLAY_NAME", generator), "modality": sample["modality"],
                     "source": sample["source"], "source_url": sample["url"], "page_url": sample.get("page_url", ""),
                     "collected_at": sample["collected_at"], "post_date": sample.get("post_date", ""),
                     "processing_seen": _processing_seen(sample, profile), "sha256": sample["sha256"], "phash": sample["phash"],
                     "width": sample.get("width", ""), "height": sample.get("height", ""), "prompt": sample.get("prompt", ""),
                     "seed": sample.get("seed", ""), "category": sample.get("category", ""), "backend": sample.get("backend", ""),
                     "paired_real": sample.get("paired_real", ""),
                     "license": profile.LICENSE, "run_id": run.run_id, "dry_run": run.dry_run})
        if sample["sha256"] not in index.shas:
            index.add([int(h, 16) for h in sample["phash"].split(";")], sha256=sample["sha256"], generator=generator,
                      run_id=run.run_id, split=split, path=str(dst))
    index.save()
    batch_dir.mkdir(parents=True, exist_ok=True)
    with open(batch_dir / "manifest.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BATCH_FIELDS); writer.writeheader(); writer.writerows(rows)
    summary = {"run_id": run.run_id, "generator": generator, "modality": profile.MODALITY, "license": profile.LICENSE,
               "dry_run": run.dry_run, "built_at": now_iso(), "batch_dir": str(batch_dir),
               "counts": dict(Counter(r["split"] for r in rows)), "sources": dict(Counter(r["source"] for r in rows)),
               "dropped": dict(rejected)}
    (batch_dir / "batch.json").write_text(json.dumps(summary, indent=1))
    _add_to_regression(settings, [r for r in rows if r["split"] == "eval_holdout"])
    (batch_dir / "READY.md").write_text(_ready_note(summary, profile))
    return summary


def _add_to_regression(settings: Settings, holdout_rows: list[dict]):
    path = settings.regression_index_path
    existing = {r["path"] for r in csv.DictReader(open(path))} if path.exists() else set()
    new = [r for r in holdout_rows if r["path"] not in existing]
    if not new: return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGRESSION_FIELDS, extrasaction="ignore")
        if write_header: writer.writeheader()
        writer.writerows(new)


def _ready_note(summary: dict, profile) -> str:
    counts = summary["counts"]
    warn = []
    if summary["dry_run"]: warn.append("DRY RUN: samples are procedural stand-ins. Do not train on this batch.")
    if "non-commercial" in str(profile.LICENSE).lower() or "research" in str(profile.LICENSE).lower():
        warn.append(f"License: {profile.LICENSE}. Check whether training a commercial detector on these outputs is allowed.")
    return "\n".join([
        f"# Batch ready: {getattr(profile, 'DISPLAY_NAME', profile.NAME)}", "",
        *[f"> {w}" for w in warn], "" if warn else "",
        f"- Modality: {summary['modality']}",
        f"- Files: train {counts.get('train', 0)}, val {counts.get('val', 0)}, eval_holdout {counts.get('eval_holdout', 0)}",
        f"- Sources: {', '.join(f'{k} ({v})' for k, v in summary['sources'].items())}",
        f"- Dropped: {', '.join(f'{k} ({v})' for k, v in summary['dropped'].items()) or 'none'}",
        f"- Manifest: {summary['batch_dir']}/manifest.csv", "",
        "Train (runs ADAPT_TRAIN_CMD and logs the time):",
        f"    uv run adapt train {summary['run_id']}",
        "Or, after training by hand:",
        f"    uv run adapt mark-trained {summary['run_id']} --checkpoint <path>", ""])
