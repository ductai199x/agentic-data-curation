"""Launch deep screening across multiple GPUs in parallel.

Splits channels into chunks, assigns each chunk to a GPU,
runs deep_screen_channel on each chunk in a separate process.

Usage:
    PYTHONUNBUFFERED=1 uv run python -m video.deep_screen_parallel \
        --input configs/video_sources/_approved \
        --output configs/video_sources/_verified \
        --num-gpus 8 --workers-per-gpu 4
"""

import argparse
import json
import multiprocessing
import os
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


def worker_process(
    gpu_id: int,
    chunk: list[tuple[str, str, str]],
    worker_id: int,
    output_dir: Path,
    result_queue,
):
    """Worker process: load model on assigned GPU, screen channels."""
    # MUST set before any torch/CUDA import
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

    # Import here so CUDA initializes on the right GPU
    from video.content_filter import JoyCaptionModel
    from video.discover import deep_screen_channel

    tmp_dir = output_dir / f"_tmp_worker_{worker_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    model = JoyCaptionModel()

    results = []
    for cid, name, category in chunk:
        result = deep_screen_channel(cid, name, model, tmp_dir)
        result["category"] = category
        results.append(result)
        result_queue.put((worker_id, result))
        time.sleep(0.3)  # Rate limit yt-dlp

    # Cleanup
    import shutil
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return results


def main():
    parser = argparse.ArgumentParser(description="Parallel deep screening")
    parser.add_argument("--input", default="configs/video_sources/_approved",
                        help="Directory with approved channel lists")
    parser.add_argument("--output", default="configs/video_sources/_verified",
                        help="Output directory for verified channels")
    parser.add_argument("--num-gpus", type=int, default=8, help="Number of GPUs")
    parser.add_argument("--workers-per-gpu", type=int, default=4,
                        help="Workers per GPU")
    parser.add_argument("--log", default="/tmp/deep_screening.log",
                        help="Log file path")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load all channels
    all_channels = load_all_channels(input_dir)

    # Check which channels are already verified
    already_verified = set()
    for vf in output_dir.glob("C*.txt"):
        with open(vf) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                cid = line.split("\t")[0]
                already_verified.add(cid)

    remaining = [(c, n, cat) for c, n, cat in all_channels if c not in already_verified]
    print(f"Total channels: {len(all_channels)}")
    print(f"Already verified: {len(already_verified)}")
    print(f"Remaining: {len(remaining)}")

    if not remaining:
        print("Nothing to do.")
        return

    # Split into chunks for workers
    total_workers = args.num_gpus * args.workers_per_gpu
    chunk_size = max(1, len(remaining) // total_workers + 1)
    chunks = [remaining[i:i + chunk_size] for i in range(0, len(remaining), chunk_size)]

    print(f"Workers: {total_workers} ({args.workers_per_gpu} per GPU × {args.num_gpus} GPUs)")
    print(f"Chunks: {len(chunks)}, ~{chunk_size} channels each")

    # Use spawn context so child processes don't inherit parent's CUDA state
    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    # Launch workers
    processes = []
    for i, chunk in enumerate(chunks):
        gpu_id = i % args.num_gpus
        p = ctx.Process(
            target=worker_process,
            args=(gpu_id, chunk, i, output_dir, result_queue),
        )
        processes.append(p)

    print(f"\nLaunching {len(processes)} workers...")
    for p in processes:
        p.start()
        time.sleep(2)  # Stagger model loading to avoid GPU OOM

    # Collect results with progress bar
    log_file = open(args.log, "w")
    pbar = tqdm(total=len(remaining), desc="Deep screening", unit="ch")

    # Per-category results
    category_results = {}  # category -> list of results
    passed = 0
    rejected = 0
    errors = 0

    try:
        collected = 0
        while collected < len(remaining):
            try:
                worker_id, result = result_queue.get(timeout=300)
            except Exception:
                # Check if all processes are dead
                alive = sum(1 for p in processes if p.is_alive())
                if alive == 0:
                    break
                continue

            collected += 1
            pbar.update(1)

            cat = result.get("category", "unknown")
            if cat not in category_results:
                category_results[cat] = []
            category_results[cat].append(result)

            status = result["status"]
            name = result.get("channel_name", "?")
            reason = result.get("reason", "")

            if status == "pass":
                passed += 1
                log_file.write(f"PASS  {cat:35s} {name:40s} | {reason}\n")
            elif status == "reject":
                rejected += 1
                log_file.write(f"FAIL  {cat:35s} {name:40s} | {reason}\n")
            else:
                errors += 1
                log_file.write(f"ERR   {cat:35s} {name:40s} | {reason}\n")

            log_file.flush()
            pbar.set_postfix(p=passed, r=rejected, e=errors)

            # Periodically save per-category verified files
            if collected % 100 == 0:
                _save_verified(output_dir, category_results)

    finally:
        pbar.close()
        log_file.close()

        # Wait for all processes
        for p in processes:
            p.join(timeout=10)

    # Final save
    _save_verified(output_dir, category_results)

    print(f"\n{'='*60}")
    print(f"TOTAL: {collected} channels screened")
    print(f"  Passed:   {passed}")
    print(f"  Rejected: {rejected}")
    print(f"  Errors:   {errors}")
    print(f"{'='*60}")
    print(f"Results saved to {output_dir}/")
    print(f"Log: {args.log}")


def _save_verified(output_dir: Path, category_results: dict):
    """Save verified channels per category."""
    for cat, results in category_results.items():
        verified = [r for r in results if r["status"] == "pass"]
        rejected_count = sum(1 for r in results if r["status"] == "reject")
        error_count = sum(1 for r in results if r["status"] == "error")

        outfile = output_dir / f"{cat}.txt"
        with open(outfile, "w") as f:
            f.write(f"# {cat} — {len(verified)} verified camera-captured channels\n")
            f.write(f"# Deep-screened: {rejected_count} rejected, {error_count} errors\n")
            f.write(f"# Format: channel_id<tab>channel_name<tab>sample_video\n\n")
            for r in verified:
                f.write(f"{r['channel_id']}\t{r.get('channel_name', '')}\t"
                        f"{','.join(r.get('sample_videos', []))}\n")


if __name__ == "__main__":
    main()
