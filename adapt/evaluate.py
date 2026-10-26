"""Before/after scoring through the real-world processing ladder.

Eval set per run = this generator's eval_holdout (new fakes) + a capped sample of every older generator's holdout
(regression fakes) + real media from ADAPT_REAL_EVAL_DIR. Every file goes through the ladder below (transforms from
the benchmark's transforms.json), is scored by the detector at a model tag, and reduces to:
- new generator: AUC / TPR@1%,5% FPR vs reals, per transform, and the ladder mean
- regression: AUC per older generator per transform, so an update that forgets an old generator is caught
"""

import csv
import json
import os
import random
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from adapt.detectors import make_detector, ModelRegistry
from adapt.metrics import detection_metrics, mean
from adapt.processing import make_processed_set as processing
from adapt.settings import Settings

IMAGE_LADDER = ["clean_png", "jpeg_q85", "jpeg_q65", "resize_long1024", "resize_long512_jpeg85", "webp_q80",
                "sim_facebook_2025", "sim_x_2025", "sim_phone_screenshot", "chain_instagram_then_whatsapp"]
VIDEO_LADDER = ["h264_crf23", "h264_crf33", "h264_480p_crf23", "sim_tiktok", "sim_whatsapp", "sim_x"]
TRANSFORMS = json.loads((Path(processing.__file__).with_name("transforms.json")).read_text())
TARGET_AUC = float(os.environ.get("ADAPT_TARGET_AUC", 0.95))          # "detected" = ladder-mean AUC at or above this
REGRESSION_TOLERANCE = float(os.environ.get("ADAPT_REGRESSION_TOL", 0.02))
MEDIA_EXT = {"image": processing.IMAGE_EXTENSIONS, "video": processing.VIDEO_EXTENSIONS}


def _ladder(modality: str) -> list[dict]:
    names = VIDEO_LADDER if modality == "video" else IMAGE_LADDER
    pool = TRANSFORMS["video_transforms" if modality == "video" else "image_transforms"]
    return [t for t in pool if t["name"] in names]


def assemble_eval_set(settings: Settings, run, profile, per_generator: int = 200, max_real: int = 1000,
                      real_dir: Path | None = None) -> list[dict]:
    rng = random.Random(run.run_id)
    batch_manifest = settings.batches_dir / profile.NAME / run.run_id / "manifest.csv"
    items = [{"path": r["path"], "label": "fake", "generator": profile.NAME, "role": "new"}
             for r in csv.DictReader(open(batch_manifest)) if r["split"] == "eval_holdout"]
    if settings.regression_index_path.exists():
        by_gen = defaultdict(list)
        for r in csv.DictReader(open(settings.regression_index_path)):
            if r["generator"] != profile.NAME and r["modality"] == profile.MODALITY: by_gen[r["generator"]].append(r)
        for gen, rows in sorted(by_gen.items()):
            for r in rng.sample(rows, min(per_generator, len(rows))):
                items.append({"path": r["path"], "label": "fake", "generator": gen, "role": "regression"})
    real_dir = real_dir or settings.real_eval_dir
    assert real_dir and real_dir.exists(), "set ADAPT_REAL_EVAL_DIR to a folder of real media (never trained on)"
    reals = sorted(p for p in real_dir.rglob("*") if p.suffix.lower() in MEDIA_EXT[profile.MODALITY])
    for p in rng.sample(reals, min(max_real, len(reals))):
        items.append({"path": str(p), "label": "real", "generator": "real", "role": "real"})
    return items


def _process(job):
    source, transform, out_dir, modality = job
    worker = processing.process_one_video if modality == "video" else processing.process_one_image
    return worker((Path(source), transform, out_dir))


def build_processed_set(items: list[dict], modality: str, out_dir: Path, workers: int | None = None) -> list[dict]:
    # resumable: manifest.jsonl records finished (source, transform) pairs
    manifest_path = out_dir / "manifest.jsonl"
    done = {(r["source"], r["transform"]) for r in map(json.loads, open(manifest_path))} if manifest_path.exists() else set()
    jobs = [(i["path"], t, out_dir / i["role"], modality) for i in items for t in _ladder(modality) if (i["path"], t["name"]) not in done]
    out_dir.mkdir(parents=True, exist_ok=True)
    if jobs:
        with ProcessPoolExecutor(workers or os.cpu_count()) as pool, open(manifest_path, "a") as manifest:
            for record in pool.map(_process, jobs, chunksize=4): manifest.write(json.dumps(record) + "\n")
    return [json.loads(l) for l in open(manifest_path)]


def score_processed(records: list[dict], detector_kind: str, checkpoint: str, model_tag: str, scores_path: Path) -> dict[str, float]:
    cached = {r["output"]: r["score"] for r in map(json.loads, open(scores_path))} if scores_path.exists() else {}
    todo = [Path(r["output"]) for r in records if r["output"] not in cached]
    if todo:
        new_scores = make_detector(detector_kind, checkpoint).score(todo)
        with open(scores_path, "a") as f:
            for output, score in new_scores.items():
                f.write(json.dumps({"output": output, "score": score, "model_tag": model_tag}) + "\n")
        cached.update(new_scores)
    return cached


def summarize(items: list[dict], records: list[dict], scores: dict[str, float], profile, model_tag: str) -> dict:
    info = {i["path"]: i for i in items}
    groups = defaultdict(lambda: defaultdict(list))  # transform -> generator -> scores
    for r in records:
        if r["output"] in scores and r["source"] in info:
            groups[r["transform"]][info[r["source"]]["generator"]].append(scores[r["output"]])
    new_by_transform, regression = {}, defaultdict(dict)
    for transform, by_gen in groups.items():
        reals = by_gen.get("real", [])
        new_by_transform[transform] = detection_metrics(by_gen.get(profile.NAME, []), reals)
        for gen, fakes in by_gen.items():
            if gen not in ("real", profile.NAME): regression[gen][transform] = detection_metrics(fakes, reals)["auc"]
    ladder_auc = mean(m["auc"] for m in new_by_transform.values())
    return {"model_tag": model_tag, "generator": profile.NAME, "new": new_by_transform,
            "headline": {"ladder_mean_auc": ladder_auc,
                         "clean_auc": new_by_transform.get("clean_png", new_by_transform.get("h264_crf23", {})).get("auc"),
                         "ladder_mean_tpr@5%fpr": mean(m["tpr@5%fpr"] for m in new_by_transform.values()),
                         "meets_target": ladder_auc >= TARGET_AUC, "target_auc": TARGET_AUC},
            "regression": {gen: {"by_transform": t, "ladder_mean_auc": mean(t.values())} for gen, t in regression.items()}}


def evaluate_run(settings: Settings, run, profile, model_tag: str, detector_kind: str, real_dir: Path | None = None,
                 workers: int | None = None) -> dict:
    eval_dir = run.dir / "eval"
    items_path = eval_dir / "items.json"
    if items_path.exists(): items = json.loads(items_path.read_text())  # same eval set before and after
    else:
        items = assemble_eval_set(settings, run, profile, real_dir=real_dir)
        eval_dir.mkdir(parents=True, exist_ok=True); items_path.write_text(json.dumps(items, indent=1))
    records = build_processed_set(items, profile.MODALITY, eval_dir / "processed", workers)
    checkpoint = ModelRegistry(settings.models_path).checkpoint(model_tag)
    scores = score_processed(records, detector_kind, checkpoint, model_tag, eval_dir / f"scores_{model_tag}.jsonl")
    summary = summarize(items, records, scores, profile, model_tag)
    (eval_dir / f"summary_{model_tag}.json").write_text(json.dumps(summary, indent=1))
    return summary


def compare(before: dict, after: dict) -> dict:
    regressions = {}
    for gen, b in before["regression"].items():
        a = after["regression"].get(gen)
        if a: regressions[gen] = round(a["ladder_mean_auc"] - b["ladder_mean_auc"], 4)
    flagged = {g: d for g, d in regressions.items() if d < -REGRESSION_TOLERANCE}
    return {"new_ladder_auc_delta": after["headline"]["ladder_mean_auc"] - before["headline"]["ladder_mean_auc"],
            "regression_auc_delta": regressions, "regressions_flagged": flagged, "tolerance": REGRESSION_TOLERANCE}
