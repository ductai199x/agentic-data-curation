"""Deep screen channels on a single GPU.

Run multiple instances with different --shard arguments to parallelize.

Usage:
    # 8-way parallel across 8 GPUs:
    for i in $(seq 0 7); do
        PYTHONUNBUFFERED=1 uv run python -m video.deep_screen_worker \
            --gpu $i --shards 8 --shard-id $i \
            --input configs/video_sources/_approved \
            --output configs/video_sources/_verified \
            > /tmp/deep_screen_gpu${i}.log 2>&1 &
    done
"""

import argparse
import json
import os
import sys
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
    """Load channel IDs already processed (pass, reject, or error).

    Reads both the verified .txt files and the per-shard processed logs.
    """
    processed = set()
    # Verified channels from category files
    for vf in output_dir.glob("C*.txt"):
        with open(vf) as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                processed.add(line.split("\t")[0])
    # Processed logs (includes rejected + errored channels)
    for pf in output_dir.glob("_processed_shard_*.log"):
        with open(pf) as f:
            for line in f:
                cid = line.strip()
                if cid:
                    processed.add(cid)
    return processed


def log_processed(output_dir: Path, shard_id: int, channel_id: str):
    """Append a channel ID to the shard's processed log."""
    logfile = output_dir / f"_processed_shard_{shard_id}.log"
    with open(logfile, "a") as f:
        f.write(f"{channel_id}\n")


def save_results(output_dir: Path, results: dict[str, list[dict]]):
    """Save per-category verified channel files."""
    for cat, cat_results in results.items():
        verified = [r for r in cat_results if r["status"] == "pass"]
        rejected_count = sum(1 for r in cat_results if r["status"] == "reject")
        error_count = sum(1 for r in cat_results if r["status"] == "error")

        outfile = output_dir / f"{cat}.txt"

        # Append mode — multiple workers may write to the same category
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


def main():
    parser = argparse.ArgumentParser(description="Deep screen worker (single GPU)")
    parser.add_argument("--gpu", type=int, required=True, help="GPU index")
    parser.add_argument("--shards", type=int, default=8, help="Total number of shards")
    parser.add_argument("--shard-id", type=int, required=True, help="This worker's shard ID (0-indexed)")
    parser.add_argument("--input", default="configs/video_sources/_approved")
    parser.add_argument("--output", default="configs/video_sources/_verified")
    args = parser.parse_args()

    # Now import CUDA-dependent modules
    from video.content_filter import JoyCaptionModel
    from video.discover import deep_screen_channel

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load and shard channels
    all_channels = load_all_channels(input_dir)
    already_processed = load_already_processed(output_dir)
    remaining = [(c, n, cat) for c, n, cat in all_channels if c not in already_processed]

    # Take this shard's slice
    my_channels = [ch for i, ch in enumerate(remaining) if i % args.shards == args.shard_id]

    print(f"GPU {args.gpu} | Shard {args.shard_id}/{args.shards} | "
          f"{len(my_channels)} channels (of {len(remaining)} remaining)")

    if not my_channels:
        print("Nothing to do.")
        return

    # Load model
    model = JoyCaptionModel()

    # Process channels
    tmp_dir = output_dir / f"_tmp_shard_{args.shard_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    category_results: dict[str, list[dict]] = {}
    passed = 0
    rejected = 0
    errors = 0

    pbar = tqdm(my_channels, desc=f"GPU {args.gpu}", unit="ch")
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

        # Log every processed channel for resume
        log_processed(output_dir, args.shard_id, cid)
        pbar.set_postfix(p=passed, r=rejected, e=errors)

        # Save verified channels periodically
        if (passed + rejected + errors) % 50 == 0:
            save_results(output_dir, category_results)

    # Final save
    save_results(output_dir, category_results)

    # Cleanup
    import shutil
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\nDone: {passed} passed, {rejected} rejected, {errors} errors")


if __name__ == "__main__":
    main()
