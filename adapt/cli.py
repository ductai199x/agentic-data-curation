"""CLI for the adaptation pipeline. `uv run adapt --help`

Typical flow (each stage resumable and skipped when done; `run` chains them):
  trigger -> collect -> dedupe -> batch -> eval (before) -> train -> eval (after) -> report
"""

import json
import os
import shutil
from pathlib import Path

import click

from adapt import batch as batch_mod
from adapt.collect import collect_closed
from adapt.dedupe import PhashIndex, dedupe_run, write_dedupe_report
from adapt.detectors import ModelRegistry
from adapt.evaluate import evaluate_run, compare
from adapt import comfy_video
from adapt.synthesize import generate_samples, ProceduralBackend
from adapt.profiles import ensure_profile, load_profile, profile_path
from adapt.release_log import new_entries, mark_seen
from adapt.report import write_report
from adapt.runs import Run, list_runs
from adapt.settings import load_settings
from adapt.store import SampleStore
from adapt.timeline import log_event, has_event, load_events, now_iso
from adapt.train_hook import train_command, run_training
from shared.paths import REPO_ROOT


def _ctx(obj) -> tuple:
    return obj["settings"], obj


def _release_at(entry) -> str:
    value = entry.release_date
    return value if "T" in value or " " in value else f"{value}T00:00:00+00:00"


def _notify(settings, run_id: str, kind: str, text: str):
    # plain-text notes the project's watch/coordinator can relay; nothing is sent from here
    settings.notifications_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_iso().replace(":", "").replace("-", "")
    (settings.notifications_dir / f"{stamp}_{run_id}_{kind}.md").write_text(text)


@click.group()
@click.option("--root", default=None, help="Pipeline working root (default $ADAPT_ROOT or data/adapt)")
@click.pass_context
def cli(ctx, root):
    ctx.obj = {"settings": load_settings(root)}


@cli.command()
@click.option("--log", "log_path", type=click.Path(exists=True, path_type=Path), default=None, help="Watch log (default $ADAPT_RELEASE_LOG)")
@click.option("--dry-run", is_flag=True, help="Mark runs as dry runs (procedural samples, dummy detector)")
@click.option("--only", multiple=True, help="Only these generator names (slug or display)")
@click.pass_obj
def trigger(obj, log_path, dry_run, only):
    """Create a run for every new entry in the generator watch log."""
    settings, _ = _ctx(obj)
    created = []
    for entry in new_entries(settings, log_path):
        if only and entry.name not in only and entry.run_id.rsplit("_", 1)[0] not in only: continue
        path, drafted = ensure_profile(settings, entry)
        profile = load_profile(path)
        run = Run.create(settings, entry, profile.NAME, dry_run=dry_run)
        if not has_event(settings.timeline_path, run.run_id, "release"):
            log_event(settings.timeline_path, run.run_id, "release", at=_release_at(entry), dry_run=dry_run, name=entry.name, maker=entry.maker)
            log_event(settings.timeline_path, run.run_id, "detected", at=entry.detected_at or None, dry_run=dry_run)
        mark_seen(settings, entry, run.run_id)
        created.append(run.run_id)
        click.echo(f"run {run.run_id}: {entry.name} ({entry.modality}, {entry.weights} weights)" + (f"  [drafted profile {path}]" if drafted else ""))
    if not created: click.echo("no new releases")


@cli.command()
@click.argument("run_id")
@click.option("--n", type=int, default=None, help="Samples to collect (default profile TARGET_SAMPLES)")
@click.option("--backend", type=click.Choice(["diffusers", "comfy", "procedural", "closed"]), default=None)
@click.option("--resolution-scale", type=float, default=1.0, help="Shrink generation size (smoke tests)")
@click.option("--force", is_flag=True)
@click.pass_obj
def collect(obj, run_id, n, backend, resolution_scale, force):
    """Generate (open weights / API nodes) or download (closed) samples into data/."""
    settings, _ = _ctx(obj)
    run = Run(settings, run_id); assert run.exists, f"no run {run_id}"
    if run.done("collect") and not force: click.echo("collect: already done"); return
    profile = load_profile(profile_path(settings, run.generator))
    store = SampleStore(settings.media_dir(profile.NAME, profile.MODALITY))
    n = n or profile.TARGET_SAMPLES
    first = lambda: has_event(settings.timeline_path, run_id, "first_samples") or log_event(settings.timeline_path, run_id, "first_samples", dry_run=run.dry_run)
    video_comfy = profile.MODALITY == "video" and profile.VIDEO_BACKEND == "comfy" and profile.COMFY_WORKFLOW
    backend = backend or ("procedural" if run.dry_run else "comfy" if video_comfy else "diffusers" if profile.WEIGHTS == "open" else None)
    details = {"backend": backend}
    if video_comfy:  # always write the ComfyRunConfig, so a dry run proves it loads
        module = comfy_video.write_comfy_config(settings, run, profile, n)
        details["comfy_config"] = str(settings.comfy_configs_dir / f"{module}.py")
        if backend == "procedural":
            frame = settings.root / "dryrun_frame.png"
            if not frame.exists(): frame.parent.mkdir(parents=True, exist_ok=True); frame.write_bytes(ProceduralBackend(None).image({"seed": 1}, 1080, 1920)[0])
            details["comfy_check"] = comfy_video.check_comfy_config(settings, module, frame)
    if backend == "comfy":
        details["shard_exit_codes"] = comfy_video.run_comfy_shards(settings, module, profile, run.dir / "comfy_logs")
        details["registered"] = comfy_video.register_outputs(settings, run, profile, store, on_first_sample=first)
    elif backend in ("diffusers", "procedural"):
        details["generated"] = generate_samples(profile, store, run_id, n, backend=backend, resolution_scale=resolution_scale, on_first_sample=first)
    else:
        details["sources"] = collect_closed(profile, store, run_id, n, base_dir=REPO_ROOT)
        if store.samples(run_id): first()
    total = len(store.samples(run_id))
    run.mark("collect", "done" if total else "empty", total=total, **details)
    click.echo(f"collect: {total} samples for {run_id} {json.dumps(details)[:400]}")


@cli.command()
@click.argument("run_id")
@click.option("--force", is_flag=True)
@click.pass_obj
def dedupe(obj, run_id, force):
    """Perceptual-hash dedupe within the run and against every earlier batch."""
    settings, _ = _ctx(obj)
    run = Run(settings, run_id)
    if run.done("dedupe") and not force: click.echo("dedupe: already done"); return
    profile = load_profile(profile_path(settings, run.generator))
    store = SampleStore(settings.media_dir(profile.NAME, profile.MODALITY))
    rows = dedupe_run(store.samples(run_id), PhashIndex(settings.phash_index_path), profile.PHASH_MAX_DISTANCE)
    write_dedupe_report(rows, run.dir / "dedupe.jsonl")
    kept = sum(r["dedupe"] == "kept" for r in rows)
    run.mark("dedupe", kept=kept, dropped=len(rows) - kept)
    click.echo(f"dedupe: kept {kept} of {len(rows)}")


@cli.command("batch")
@click.argument("run_id")
@click.option("--force", is_flag=True)
@click.pass_obj
def batch_cmd(obj, run_id, force):
    """Split kept samples into train/val/eval_holdout with a labeled manifest and a READY note."""
    settings, _ = _ctx(obj)
    run = Run(settings, run_id)
    if run.done("batch") and not force: click.echo("batch: already done"); return
    profile = load_profile(profile_path(settings, run.generator))
    rows = [json.loads(l) for l in open(run.dir / "dedupe.jsonl") if l.strip()]
    summary = batch_mod.build_batch(settings, run, profile, rows)
    run.mark("batch", **{k: summary[k] for k in ("batch_dir", "counts")})
    log_event(settings.timeline_path, run_id, "batch_ready", dry_run=run.dry_run, counts=summary["counts"])
    _notify(settings, run_id, "batch_ready", (Path(summary["batch_dir"]) / "READY.md").read_text())
    click.echo(f"batch: {summary['counts']} -> {summary['batch_dir']}")


@cli.command("register-model")
@click.argument("tag")
@click.option("--checkpoint", required=True, help="Checkpoint path / weights dir the detector adapter loads")
@click.option("--not-current", is_flag=True)
@click.pass_obj
def register_model(obj, tag, checkpoint, not_current):
    """Register a detector checkpoint (do this once for the model in production now)."""
    settings, _ = _ctx(obj)
    ModelRegistry(settings.models_path).register(tag, checkpoint, make_current=not not_current)
    click.echo(f"registered {tag} -> {checkpoint}")


@cli.command("eval")
@click.argument("run_id")
@click.option("--phase", type=click.Choice(["before", "after"]), required=True)
@click.option("--model-tag", default=None, help="Default: current model for before, the run's trained model for after")
@click.option("--detector", type=click.Choice(["command", "fsd", "dummy"]), default=None, help="Default $ADAPT_DETECTOR or fsd")
@click.option("--real-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--force", is_flag=True)
@click.pass_obj
def eval_cmd(obj, run_id, phase, model_tag, detector, real_dir, force):
    """Score the new generator + regression set through the processing ladder."""
    settings, _ = _ctx(obj)
    run = Run(settings, run_id)
    stage = f"eval_{phase}"
    if run.done(stage) and not force: click.echo(f"{stage}: already done"); return
    profile = load_profile(profile_path(settings, run.generator))
    registry = ModelRegistry(settings.models_path)
    model_tag = model_tag or (run.info("eval_before").get("model_tag") or registry.current if phase == "before" else run.info("train").get("model_tag"))
    assert model_tag, "no model tag: register-model first (before) or train / mark-trained (after)"
    detector = detector or ("dummy" if run.dry_run else os.environ.get("ADAPT_DETECTOR", "fsd"))
    summary = evaluate_run(settings, run, profile, model_tag, detector, real_dir=real_dir)
    head = summary["headline"]
    extra = {}
    if phase == "after":
        before = json.loads((run.dir / "eval" / f"summary_{run.info('eval_before')['model_tag']}.json").read_text())
        extra = compare(before, summary)
        (run.dir / "eval" / "comparison.json").write_text(json.dumps(extra, indent=1))
    run.mark(stage, model_tag=model_tag, detector=detector, **head)
    log_event(settings.timeline_path, run_id, stage, dry_run=run.dry_run, model_tag=model_tag, detector=detector,
              ladder_mean_auc=head["ladder_mean_auc"], clean_auc=head["clean_auc"], meets_target=head["meets_target"],
              regressions_flagged=extra.get("regressions_flagged", {}))
    click.echo(f"{stage}: {model_tag} ladder AUC {head['ladder_mean_auc']:.3f} (target {head['target_auc']}, met={head['meets_target']})"
               + (f"; regressions flagged: {extra['regressions_flagged'] or 'none'}" if extra else ""))


@cli.command()
@click.argument("run_id")
@click.pass_obj
def train(obj, run_id):
    """Run ADAPT_TRAIN_CMD on the batch (or hand back to Tai if it is not set)."""
    settings, _ = _ctx(obj)
    run = Run(settings, run_id)
    if run.done("train"): click.echo("train: already done"); return
    registry = ModelRegistry(settings.models_path)
    base_tag = run.info("eval_before").get("model_tag") or registry.current
    batch_dir = Path(run.info("batch")["batch_dir"])
    output_dir = settings.root / "models" / run_id
    command = train_command(run_id, batch_dir, registry.checkpoint(base_tag) if base_tag else "", output_dir, run.generator)
    if not command:
        run.mark("train", "awaiting_tai", base_model=base_tag)
        _notify(settings, run_id, "awaiting_training", f"Batch for {run_id} is ready and scored. Train on {batch_dir}, then:\n"
                f"  uv run adapt mark-trained {run_id} --checkpoint <path>\n")
        click.echo("train: ADAPT_TRAIN_CMD not set; waiting for Tai (see notifications/)"); return
    log_event(settings.timeline_path, run_id, "train_started", dry_run=run.dry_run, base_model=base_tag)
    checkpoint = run_training(command, output_dir, run.dir / "train.log")
    _finish_training(settings, run, checkpoint, run_id, base_tag)


def _finish_training(settings, run, checkpoint: str, model_tag: str, base_tag: str | None, at: str | None = None):
    ModelRegistry(settings.models_path).register(model_tag, checkpoint, run_id=run.run_id, base_model=base_tag)
    run.mark("train", model_tag=model_tag, checkpoint=checkpoint, base_model=base_tag)
    log_event(settings.timeline_path, run.run_id, "model_updated", at=at, dry_run=run.dry_run, model_tag=model_tag, checkpoint=checkpoint)
    click.echo(f"train: registered {model_tag} -> {checkpoint}")


@cli.command("mark-trained")
@click.argument("run_id")
@click.option("--checkpoint", required=True)
@click.option("--model-tag", default=None, help="Default: the run id")
@click.option("--started-at", default=None, help="ISO time training started (if done by hand)")
@click.option("--finished-at", default=None, help="ISO time the model was ready (default now)")
@click.pass_obj
def mark_trained(obj, run_id, checkpoint, model_tag, started_at, finished_at):
    """Record a model Tai trained by hand, so the time-to-adapt log stays complete."""
    settings, _ = _ctx(obj)
    run = Run(settings, run_id)
    if started_at: log_event(settings.timeline_path, run_id, "train_started", at=started_at, dry_run=run.dry_run)
    _finish_training(settings, run, checkpoint, model_tag or run_id, run.info("eval_before").get("model_tag"), at=finished_at)


@cli.command("seed-regression")
@click.option("--modality", type=click.Choice(["image", "video"]), default="image")
@click.option("--per-gen", type=int, default=200)
@click.pass_obj
def seed_regression(obj, modality, per_gen):
    """Add a sample of every existing dataset to the regression set (data/images/<gen>/images, data/videos/fake/<gen>/)."""
    import csv, random
    from shared.clip_utils import list_clips
    settings, _ = _ctx(obj)
    root = settings.data_root / ("videos/fake" if modality == "video" else "images")
    rows = []
    for gen_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name != "adapt") if root.exists() else []:
        if modality == "video": files = list_clips(gen_dir)
        elif (gen_dir / "images").is_dir(): files = sorted(f for f in (gen_dir / "images").iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
        else: continue
        for f in random.Random(gen_dir.name).sample(files, min(per_gen, len(files))):
            rows.append({"path": str(f), "label": "fake", "generator": gen_dir.name, "run_id": "seed", "modality": modality})
    batch_mod._add_to_regression(settings, rows)
    click.echo(f"regression set: +{len(rows)} {modality} files from {len({r['generator'] for r in rows})} generators")


@cli.command()
@click.option("--no-dry-run", is_flag=True, help="Leave dry runs out of the report")
@click.pass_obj
def report(obj, no_dry_run):
    """Write reports/TIME_TO_ADAPT.md, time_to_adapt.csv and halving_curve.svg."""
    settings, _ = _ctx(obj)
    click.echo(f"report: {write_report(settings.timeline_path, settings.reports_dir, include_dry_run=not no_dry_run)}")


@cli.command()
@click.pass_obj
def status(obj):
    """One line per run: stages done and what it waits on."""
    settings, _ = _ctx(obj)
    for run in list_runs(settings):
        stages = " ".join(f"{s}:{v['status']}" for s, v in run.state["stages"].items())
        click.echo(f"{run.run_id}{' [dry]' if run.dry_run else ''}  {stages or 'triggered'}")


@cli.command()
@click.option("--log", "log_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--dry-run", is_flag=True, help="Procedural samples, dummy detector, procedural reals; safe anywhere")
@click.option("--only", multiple=True)
@click.option("--n", type=int, default=None)
@click.option("--resolution-scale", type=float, default=1.0)
@click.pass_context
def run(ctx, log_path, dry_run, only, n, resolution_scale):
    """Trigger and carry every pending run as far as it can go (stops at training if no ADAPT_TRAIN_CMD)."""
    settings = ctx.obj["settings"]
    ctx.invoke(trigger, log_path=log_path, dry_run=dry_run, only=only)
    real_dir = None
    if dry_run:
        real_dir = _dry_run_reals(settings)
        registry = ModelRegistry(settings.models_path)
        if not registry.current: registry.register("dryrun_base", "dummy-v0")
    for r in list_runs(settings):
        if only and r.generator not in only and r.entry.name not in only: continue
        if r.done("eval_after"): continue
        ctx.invoke(collect, run_id=r.run_id, n=n, backend=None, resolution_scale=resolution_scale, force=False)
        if not Run(settings, r.run_id).done("collect"): click.echo(f"{r.run_id}: no samples yet, stopping here"); continue
        ctx.invoke(dedupe, run_id=r.run_id, force=False)
        ctx.invoke(batch_cmd, run_id=r.run_id, force=False)
        ctx.invoke(eval_cmd, run_id=r.run_id, phase="before", model_tag=None, detector=None, real_dir=real_dir, force=False)
        ctx.invoke(train, run_id=r.run_id)
        if Run(settings, r.run_id).done("train"):
            ctx.invoke(eval_cmd, run_id=r.run_id, phase="after", model_tag=None, detector=None, real_dir=real_dir, force=False)
    ctx.invoke(report, no_dry_run=False)


def _dry_run_reals(settings, n_images: int = 60, n_videos: int = 8) -> Path:
    # procedural "real" stand-ins (blur + noise) so AUC is computable without any real data; dry runs only
    out = settings.root / "dryrun_reals"
    if out.exists() and len(list(out.iterdir())) >= n_images + n_videos: return out
    out.mkdir(parents=True, exist_ok=True)
    backend = ProceduralBackend(None, style="real")
    for i in range(n_images):
        data, ext = backend.image({"seed": 10_000 + i}, 768, 768)
        (out / f"real_{i:04d}{ext}").write_bytes(data)
    for i in range(n_videos):
        data, ext = backend.video({"seed": 20_000 + i}, 320, 192, num_frames=16, fps=8)
        (out / f"real_video_{i:04d}{ext}").write_bytes(data)
    return out


if __name__ == "__main__":
    cli()
