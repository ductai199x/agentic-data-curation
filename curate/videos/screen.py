"""Deep screen channels for camera-captured content.

Two modes:
- shard: Single GPU worker. Run N instances externally for parallelism.
- parallel: Multi-GPU orchestrator. Spawns workers internally.

Usage:
    # Shard mode (run 8 of these, one per GPU):
    CUDA_VISIBLE_DEVICES=0 uv run python -m curate.videos.screen shard \
        --shard-id 0 --shards 8 \
        --input configs/video_sources/_approved \
        --output configs/video_sources/_verified

    # Parallel mode (orchestrates all GPUs):
    uv run python -m curate.videos.screen parallel \
        --input configs/video_sources/_approved \
        --output configs/video_sources/_verified \
        --num-gpus 8 --workers-per-gpu 4
"""

import click
import multiprocessing
import os
import shutil
import time
from pathlib import Path

from tqdm import tqdm


def load_all_channels(input_dir: Path) -> list[tuple[str, str, str]]:
    """Load all channels from approved files.

    Returns list of (channel_id, channel_name, category).
    """
    channels = []
    for cat_file in sorted(input_dir.glob("C*.txt")):
        category = cat_file.stem
        with open(cat_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    channels.append((parts[0], parts[1], category))
    return channels


def load_already_processed(output_dir: Path) -> set[str]:
    """Load channel IDs already processed (verified, rejected, or errored)."""
    processed = set()
    for vf in output_dir.glob("C*.txt"):
        with open(vf) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                processed.add(line.split("\t")[0])
    for pf in output_dir.glob("_processed_shard_*.log"):
        with open(pf) as f:
            for line in f:
                cid = line.strip()
                if cid:
                    processed.add(cid)
    return processed


def save_results(output_dir: Path, category_results: dict[str, list[dict]],
                 append: bool = True):
    """Save per-category verified channel files."""
    for cat, results in category_results.items():
        verified = [r for r in results if r["status"] == "pass"]
        rejected_count = sum(1 for r in results if r["status"] == "reject")
        error_count = sum(1 for r in results if r["status"] == "error")

        outfile = output_dir / f"{cat}.txt"

        if append:
            existing = set()
            if outfile.exists():
                with open(outfile) as f:
                    for line in f:
                        if not line.startswith("#") and line.strip():
                            existing.add(line.split("\t")[0])
            with open(outfile, "a") as f:
                if not existing:
                    f.write(f"# {cat} — verified camera-captured channels\n")
                    f.write(f"# Format: channel_id<tab>channel_name<tab>sample_videos\n\n")
                for r in verified:
                    if r["channel_id"] not in existing:
                        f.write(f"{r['channel_id']}\t{r.get('channel_name', '')}\t"
                                f"{','.join(r.get('sample_videos', []))}\n")
        else:
            with open(outfile, "w") as f:
                f.write(f"# {cat} — {len(verified)} verified camera-captured channels\n")
                f.write(f"# Deep-screened: {rejected_count} rejected, {error_count} errors\n")
                f.write(f"# Format: channel_id<tab>channel_name<tab>sample_video\n\n")
                for r in verified:
                    f.write(f"{r['channel_id']}\t{r.get('channel_name', '')}\t"
                            f"{','.join(r.get('sample_videos', []))}\n")


# ---------------------------------------------------------------------------
# Shard mode: single GPU, single process
# ---------------------------------------------------------------------------

def run_shard(shard_id: int, shards: int, input_dir: Path, output_dir: Path):
    """Run deep screening on a shard of channels (single GPU)."""
    from curate.videos.content_filter import JoyCaptionModel
    from curate.videos.discover import deep_screen_channel

    output_dir.mkdir(parents=True, exist_ok=True)

    all_channels = load_all_channels(input_dir)
    already_processed = load_already_processed(output_dir)
    remaining = [(c, n, cat) for c, n, cat in all_channels if c not in already_processed]

    my_channels = [ch for i, ch in enumerate(remaining) if i % shards == shard_id]

    print(f"Shard {shard_id}/{shards} | "
          f"{len(my_channels)} channels (of {len(remaining)} remaining)")

    if not my_channels:
        print("Nothing to do.")
        return

    model = JoyCaptionModel()

    tmp_dir = output_dir / f"_tmp_shard_{shard_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    category_results: dict[str, list[dict]] = {}
    passed = rejected = errors = 0

    pbar = tqdm(my_channels, desc=f"Shard {shard_id}", unit="ch")
    for cid, name, category in pbar:
        result = deep_screen_channel(cid, name, model, tmp_dir)
        result["category"] = category

        if category not in category_results:
            category_results[category] = []
        category_results[category].append(result)

        if result["status"] == "pass":
            passed += 1
            tqdm.write(f"PASS  {name:40s} | {result['reason']}")
        elif result["status"] == "reject":
            rejected += 1
            tqdm.write(f"FAIL  {name:40s} | {result['reason']}")
        else:
            errors += 1
            tqdm.write(f"ERR   {name:40s} | {result['reason']}")

        # Log for resume
        logfile = output_dir / f"_processed_shard_{shard_id}.log"
        with open(logfile, "a") as f:
            f.write(f"{cid}\n")

        pbar.set_postfix(p=passed, r=rejected, e=errors)
        save_results(output_dir, category_results, append=True)

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\nDone: {passed} passed, {rejected} rejected, {errors} errors")


# ---------------------------------------------------------------------------
# Parallel mode: multi-GPU orchestrator
# ---------------------------------------------------------------------------

def _parallel_worker(gpu_id, chunk, worker_id, output_dir, result_queue):
    """Worker process for parallel mode."""
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    from curate.videos.content_filter import JoyCaptionModel
    from curate.videos.discover import deep_screen_channel

    tmp_dir = output_dir / f"_tmp_worker_{worker_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    model = JoyCaptionModel()

    for cid, name, category in chunk:
        result = deep_screen_channel(cid, name, model, tmp_dir)
        result["category"] = category
        result_queue.put((worker_id, result))
        time.sleep(0.3)

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_parallel(num_gpus: int, workers_per_gpu: int, input_dir: Path, output_dir: Path):
    """Run deep screening across multiple GPUs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    all_channels = load_all_channels(input_dir)
    already_processed = load_already_processed(output_dir)
    remaining = [(c, n, cat) for c, n, cat in all_channels if c not in already_processed]

    print(f"Total: {len(all_channels)}, Already done: {len(already_processed)}, "
          f"Remaining: {len(remaining)}")

    if not remaining:
        print("Nothing to do.")
        return

    total_workers = num_gpus * workers_per_gpu
    chunk_size = max(1, len(remaining) // total_workers + 1)
    chunks = [remaining[i:i + chunk_size] for i in range(0, len(remaining), chunk_size)]

    print(f"Workers: {total_workers} ({workers_per_gpu}/GPU × {num_gpus} GPUs)")

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    processes = []
    for i, chunk in enumerate(chunks):
        gpu_id = i % num_gpus
        p = ctx.Process(target=_parallel_worker,
                        args=(gpu_id, chunk, i, output_dir, result_queue))
        processes.append(p)

    for p in processes:
        p.start()
        time.sleep(2)

    category_results: dict[str, list[dict]] = {}
    passed = rejected = errors = 0
    pbar = tqdm(total=len(remaining), desc="Deep screening", unit="ch")

    try:
        collected = 0
        while collected < len(remaining):
            try:
                worker_id, result = result_queue.get(timeout=300)
            except Exception:
                if not any(p.is_alive() for p in processes):
                    break
                continue

            collected += 1
            pbar.update(1)

            cat = result.get("category", "unknown")
            category_results.setdefault(cat, []).append(result)

            status = result["status"]
            if status == "pass":
                passed += 1
            elif status == "reject":
                rejected += 1
            else:
                errors += 1

            pbar.set_postfix(p=passed, r=rejected, e=errors)

            if collected % 100 == 0:
                save_results(output_dir, category_results, append=False)
    finally:
        pbar.close()
        for p in processes:
            p.join(timeout=10)

    save_results(output_dir, category_results, append=False)
    print(f"\nTotal: {passed} passed, {rejected} rejected, {errors} errors")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group(help="Deep screen channels")
def main():
    pass


@main.command("shard", help="Single GPU worker (run N externally)")
@click.option("--shard-id", type=int, required=True)
@click.option("--shards", type=int, default=8)
@click.option("--input", "input_", default="configs/video_sources/_approved")
@click.option("--output", default="configs/video_sources/_verified")
def shard_cmd(shard_id, shards, input_, output):
    run_shard(shard_id, shards, Path(input_), Path(output))


@main.command("parallel", help="Multi-GPU orchestrator")
@click.option("--num-gpus", type=int, default=8)
@click.option("--workers-per-gpu", type=int, default=4)
@click.option("--input", "input_", default="configs/video_sources/_approved")
@click.option("--output", default="configs/video_sources/_verified")
def parallel_cmd(num_gpus, workers_per_gpu, input_, output):
    run_parallel(num_gpus, workers_per_gpu, Path(input_), Path(output))


if __name__ == "__main__":
    main()
