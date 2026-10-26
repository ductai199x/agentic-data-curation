"""Video collection through generate/'s ComfyUI workers.

A new video generator is adapted the same way the existing fake-video sets were made: image-to-video from the first
frame of each real clip (data/videos/real/<source>/validated) with its SALMONN caption, so every fake has a paired real.
The profile names the workflow builder (generate.workflows.<x>) and its model_kwargs; this module writes a
ComfyRunConfig for the run, runs one shard per GPU (same env as scripts/launch.sh, but blocking), and registers the
generated clips as samples.
Paid providers (comfy.org API nodes) only run with ADAPT_ALLOW_PAID=1 and a MAX_COST_USD in the profile; the
existing budget gate in comfy_batch_run still applies on top.
"""

import csv
import os
import subprocess
from pathlib import Path

from adapt.settings import Settings
from adapt.store import SampleStore
from shared.paths import COMFY_ROOT, REPO_ROOT

CONFIG_TEMPLATE = '''"""Written by adapt.comfy_video for run {run_id}. Regenerated on every collect; edit the profile instead."""
from pathlib import Path
from generate.comfy_config import ComfyRunConfig

CONFIG = ComfyRunConfig(
    clips_dir=Path({clips_dir!r}),
    captions_path=Path({captions_path!r}),
    frames_dir=Path({frames_dir!r}),
    output_dir=Path({output_dir!r}),
    workflow_module={workflow!r},
    model_tag={model_tag!r},
    rank_file={rank_file},
    max_clips={max_clips},
    prompt_source={prompt_source!r},
    prompt_max_chars={prompt_max_chars},
    paid_provider={paid},
    cost_per_clip_usd={cost},
    max_cost_usd={max_cost},
    delete_input_frame_after_use=False,
    model_kwargs={model_kwargs!r},
)
'''


def output_dir(settings: Settings, profile) -> Path:
    return settings.media_dir(profile.NAME, "video") / profile.COMFY_SOURCE


def write_comfy_config(settings: Settings, run, profile, n: int) -> str:
    real = settings.data_root / "videos/real" / profile.COMFY_SOURCE
    rank = real / "diversity_rank.csv"
    paid = bool(getattr(profile, "PAID_PROVIDER", False))
    module = f"adapt_{run.run_id}"
    settings.comfy_configs_dir.mkdir(parents=True, exist_ok=True)
    (settings.comfy_configs_dir / f"{module}.py").write_text(CONFIG_TEMPLATE.format(
        run_id=run.run_id, clips_dir=str(real / "validated"), captions_path=str(real / "video_captions.json"),
        frames_dir=str(real / "frames"), output_dir=str(output_dir(settings, profile)), workflow=profile.COMFY_WORKFLOW,
        model_tag=f"{profile.NAME}-adapt", rank_file=f"Path({str(rank)!r})" if rank.exists() else "None", max_clips=n,
        prompt_source=getattr(profile, "COMFY_PROMPT_SOURCE", "caption"), prompt_max_chars=getattr(profile, "COMFY_PROMPT_MAX_CHARS", 1500),
        paid=paid, cost=float(getattr(profile, "COST_PER_CLIP_USD", 0.0)), max_cost=float(getattr(profile, "MAX_COST_USD", 0.0)),
        model_kwargs=getattr(profile, "COMFY_MODEL_KWARGS", {})))
    return module


def run_comfy_shards(settings: Settings, module: str, profile, log_dir: Path) -> list[int]:
    if getattr(profile, "PAID_PROVIDER", False) and os.environ.get("ADAPT_ALLOW_PAID") != "1":
        raise SystemExit(f"{profile.NAME} uses a paid provider; set ADAPT_ALLOW_PAID=1 (and MAX_COST_USD in the profile) to spend")
    gpus = os.environ.get("GPUS", "0").replace(",", " ").split()
    python = os.environ.get("PY", str(COMFY_ROOT / ".venv/bin/python"))
    log_dir.mkdir(parents=True, exist_ok=True)
    procs = []
    for shard_id, gpu in enumerate(gpus):
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": gpu, "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
               "PYTHONPATH": os.pathsep.join([str(REPO_ROOT), str(settings.comfy_configs_dir)]),
               "COMFY_CONFIG": module, "SHARDS": str(len(gpus)), "SHARD_ID": str(shard_id)}
        log = open(log_dir / f"shard_{shard_id}_gpu{gpu}.log", "a")
        procs.append(subprocess.Popen([python, "-m", "generate.comfy_batch_run"], env=env, stdout=log, stderr=subprocess.STDOUT, cwd=REPO_ROOT))
    return [p.wait() for p in procs]


def register_outputs(settings: Settings, run, profile, store: SampleStore, on_first_sample=None) -> int:
    out = output_dir(settings, profile)
    added = 0
    for manifest in sorted(out.glob("manifest*.csv")):
        for row in csv.DictReader(open(manifest)):
            path = Path(row.get("output_path") or "")
            if row.get("status") != "generated" or not path.is_file(): continue
            if store.register(path, url=f"comfy://{row.get('model', '')}/{row['real_clip']}", source=f"local_generation_comfy_{profile.COMFY_SOURCE}",
                              run_id=run.run_id, modality="video", sample_key=f"comfy:{row['real_clip']}", prompt=row.get("prompt_preview", ""),
                              paired_real=row["real_clip"], backend="comfy", flair=profile.COMFY_SOURCE):
                added += 1
                if added == 1 and on_first_sample: on_first_sample()
    return added


def check_comfy_config(settings: Settings, module: str, sample_frame: Path) -> dict:
    # dry-run proof: the written config loads as a ComfyRunConfig and its workflow builder emits a graph
    import importlib, sys
    sys.path.insert(0, str(settings.comfy_configs_dir))
    try:
        from generate.comfy_config import load_config
        sys.modules.pop(module, None)
        cfg = load_config(module)
        builder = importlib.import_module(cfg.workflow_module)
        graph = builder.build_workflow(cfg, sample_frame.name, "a test prompt", f"{cfg.model_tag}_check",
                                       last_frame_name=sample_frame.name, first_frame_path=sample_frame)
        loaders = sorted({n["class_type"] for n in graph.values() if "Load" in n["class_type"]})
        return {"loads": True, "workflow": cfg.workflow_module, "nodes": len(graph), "loader_nodes": loaders,
                "model_tag": cfg.model_tag, "max_clips": cfg.max_clips, "paid_provider": cfg.paid_provider}
    finally:
        sys.path.remove(str(settings.comfy_configs_dir))
