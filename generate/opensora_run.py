"""Open-Sora 2.0 batch worker — drives Open-Sora's native inference.py.

Mirrors the role of `generate.comfy_batch_run` but talks to Open-Sora's
own torchrun-based pipeline instead of a ComfyUI HTTP server. Open-Sora
2.0 (Flux-DiT + Hunyuan VAE, 11B) has no production ComfyUI integration,
so we go through their `scripts/diffusion/inference.py` directly.

Per-shard flow:
  1. Build job list (rank-filtered, same logic as build_jobs).
  2. Filter out clips whose mp4 already exists in cfg.output_dir (resume).
  3. Write a per-shard CSV at /tmp/opensora_shard{id}.csv with columns
     `text,ref,name` — `name` carries the source-clip stem so Open-Sora's
     own save path puts the mp4 at <tmp_save>/sample/<stem>.mp4.
  4. Subprocess `torchrun --nproc_per_node 1 scripts/diffusion/inference.py
     <i2v_config> --save-dir <tmp_save> --dataset.data-path <csv>
     --cond_type i2v_head --offload True ...`.
  5. After completion, copy each <stem>.mp4 from tmp_save into cfg.output_dir
     and append a manifest row.

Resume safety: each clip is independently skippable via the on-disk mp4
check; killing the shard mid-run loses in-flight work but won't corrupt
already-saved clips.

Launch via `scripts/launch_opensora.sh`. Env vars:
    OPENSORA_CONFIG=configs.generate.opensora_youtube
    SHARDS=8 SHARD_ID=0
"""
from __future__ import annotations

import csv
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from shared.manifest import MANIFEST_FIELDS, append_manifest, load_processed
from shared.paths import REPO_ROOT
from shared.shard import shard_jobs

# `from shared.loaders import build_jobs` — but our caller pre-builds the job
# list to keep this script independent from comfy_config (Open-Sora has its
# own config dataclass). build_jobs lives there; we reuse it directly.
sys.path.insert(0, str(REPO_ROOT))
from shared.loaders import build_jobs  # noqa: E402


OPENSORA_DIR = REPO_ROOT / "third_party" / "Open-Sora"
TORCHRUN = OPENSORA_DIR / ".venv" / "bin" / "torchrun"
DEFAULT_CONFIG_PATH = "configs/diffusion/inference/t2i2v_768px.py"  # i2v


def _shard_csv_path(tmp_dir: Path, shard_id: int) -> Path:
    return tmp_dir / f"shard_{shard_id}.csv"


def _write_shard_csv(jobs: list, csv_path: Path) -> int:
    """Write Open-Sora-format CSV (text, ref, name) for the given jobs.

    Truncates prompts at cfg.prompt_max_chars (Open-Sora's T5 caps at ~512).
    Returns the number of rows written.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(["text", "ref", "name"])
        for j in jobs:
            w.writerow([
                j.prompt[:512],
                str(j.first_frame),
                j.real_clip.stem,
            ])
    return len(jobs)


def _run_torchrun(
    config_path: str,
    csv_path: Path,
    save_dir: Path,
    cuda_device: str,
    cond_type: str = "i2v_head",
    aspect_ratio: str = "16:9",
    num_frames: int = 129,
    offload: bool = True,
) -> int:
    """Launch one torchrun process for this shard's CSV. Returns exit code."""
    save_dir.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "CUDA_VISIBLE_DEVICES": cuda_device}
    cmd = [
        str(TORCHRUN), "--nproc_per_node=1", "--standalone",
        "scripts/diffusion/inference.py",
        config_path,
        "--save-dir", str(save_dir),
        "--dataset.data-path", str(csv_path),
        "--cond_type", cond_type,
        "--aspect_ratio", aspect_ratio,
        "--num_frames", str(num_frames),
    ]
    if offload:
        cmd += ["--offload", "True"]

    print(f"[opensora] cmd: {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(OPENSORA_DIR), env=env)


def _move_outputs(save_dir: Path, output_dir: Path, stems: set[str]) -> int:
    """Move generated <stem>.mp4 files from Open-Sora's save_dir layout
    (`<save_dir>/sample/<stem>.mp4` typically) into our output_dir. Returns
    count of files moved.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for mp4 in save_dir.rglob("*.mp4"):
        if mp4.stem in stems:
            dst = output_dir / f"{mp4.stem}.mp4"
            shutil.move(str(mp4), str(dst))
            moved += 1
    return moved


def main():
    config_module_name = os.environ.get("OPENSORA_CONFIG")
    if not config_module_name:
        print("set OPENSORA_CONFIG=<module> (e.g. configs.generate.opensora_youtube)",
              flush=True)
        sys.exit(1)

    cfg_mod = importlib.import_module(config_module_name)
    cfg = cfg_mod.CONFIG  # OpenSoraRunConfig (defined in its config file)

    shards = int(os.environ.get("SHARDS", "1"))
    shard_id = int(os.environ.get("SHARD_ID", "0"))
    cuda_device = os.environ.get("CUDA_VISIBLE_DEVICES", "0")

    log = lambda m: print(f"[opensora shard {shard_id}/{shards}] {m}", flush=True)

    log("building jobs...")
    jobs = build_jobs(
        cfg.clips_dir,
        cfg.captions_path,
        cfg.frames_dir,
        rank_file=cfg.rank_file,
        max_clips=cfg.max_clips,
        caption_key=cfg.prompt_source,
    )
    log(f"total jobs: {len(jobs)}")
    jobs = shard_jobs(jobs, shard_id, shards)
    log(f"my shard:   {len(jobs)} jobs")

    manifest_path = cfg.output_dir / (
        f"manifest_shard{shard_id}.csv" if shards > 1 else "manifest.csv"
    )
    processed = load_processed(manifest_path)
    remaining = [
        j for j in jobs
        if j.real_clip.name not in processed
        and not (cfg.output_dir / f"{j.real_clip.stem}.mp4").exists()
    ]
    log(f"already done: {len(jobs) - len(remaining)}")
    log(f"remaining:    {len(remaining)}")
    if not remaining:
        log("nothing to do.")
        return

    # ---- Write CSV + run Open-Sora ---------------------------------------
    tmp_root = Path(tempfile.mkdtemp(prefix=f"opensora_shard{shard_id}_"))
    csv_path = _shard_csv_path(tmp_root, shard_id)
    n_rows = _write_shard_csv(remaining, csv_path)
    log(f"wrote {csv_path} ({n_rows} rows)")

    save_dir = tmp_root / "save"
    t0 = time.time()
    rc = _run_torchrun(
        config_path=cfg.opensora_config_path,
        csv_path=csv_path,
        save_dir=save_dir,
        cuda_device=cuda_device,
        cond_type=cfg.cond_type,
        aspect_ratio=cfg.aspect_ratio,
        num_frames=cfg.num_frames,
        offload=cfg.offload,
    )
    elapsed = time.time() - t0
    log(f"torchrun exit={rc}, elapsed={elapsed:.0f}s")

    # ---- Move outputs + write manifest -----------------------------------
    stems = {j.real_clip.stem for j in remaining}
    moved = _move_outputs(save_dir, cfg.output_dir, stems)
    log(f"moved {moved} mp4s into {cfg.output_dir}")

    now = datetime.now(timezone.utc).isoformat()
    n_appended = 0
    for j in remaining:
        out_mp4 = cfg.output_dir / f"{j.real_clip.stem}.mp4"
        if out_mp4.exists():
            row = {field: "" for field in MANIFEST_FIELDS}
            row.update({
                "real_clip": j.real_clip.name,
                "first_frame": j.first_frame.name,
                "last_frame": j.last_frame.name if j.last_frame.exists() else "",
                "prompt_source": cfg.prompt_source,
                "prompt_preview": j.prompt[:200],
                "output_path": str(out_mp4),
                "duration_s": cfg.num_frames / cfg.fps_save,
                "status": "generated",
                "model_name": cfg.model_tag,
                "elapsed_s": "",
                "error": "",
            })
            append_manifest(manifest_path, row)
            n_appended += 1
    log(f"appended {n_appended} manifest rows. done.")

    # Best-effort cleanup of tmp shard dir
    try:
        shutil.rmtree(tmp_root)
    except Exception:
        pass


if __name__ == "__main__":
    main()
