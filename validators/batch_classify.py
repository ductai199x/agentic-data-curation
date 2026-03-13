"""Parallel batch classification via JoyCaption HTTP service.

Usage:
    uv run python -m validators.batch_classify --dir data/grok/staging --output captions.json
    uv run python -m validators.batch_classify --dir data/grok/staging --url http://localhost:8000 --concurrency 6
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp
import click
from tqdm import tqdm


async def classify_one(session, url, filepath):
    try:
        async with session.post(
            url, json={"path": str(filepath)},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            return filepath.name, await resp.json()
    except Exception as e:
        return filepath.name, {"error": str(e), "should_reject": False, "reject_signals": []}


async def run_batch(image_dir: Path, output: Path, url: str, concurrency: int,
                    force: bool = False):
    all_files = sorted(f for f in image_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png"))

    # Load existing results to skip already-classified files (unless --force)
    results = {}
    if not force and output.exists():
        with open(output) as f:
            results = json.load(f)
        print(f"Loaded {len(results)} existing results from {output}", flush=True)

    files = [f for f in all_files if f.name not in results]
    print(f"Classifying {len(files)} new images ({len(all_files) - len(files)} already done, "
          f"{concurrency} concurrent)...", flush=True)

    if not files:
        print("Nothing new to classify.", flush=True)
        return

    semaphore = asyncio.Semaphore(concurrency)

    async def classify_with_sem(session, f):
        async with semaphore:
            return await classify_one(session, url, f)

    pass_count = 0
    reject_count = 0
    err_count = 0

    pbar = tqdm(total=len(files), desc="Captioning", unit="img", file=sys.stderr)

    async with aiohttp.ClientSession() as session:
        tasks = [classify_with_sem(session, f) for f in files]
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            name, result = await coro
            results[name] = result

            if "error" in result:
                err_count += 1
            elif result.get("should_reject") or len(result.get("reject_signals", [])) > 0:
                reject_count += 1
            else:
                pass_count += 1

            pbar.update(1)
            pbar.set_postfix(p=pass_count, r=reject_count, e=err_count)

            # Incremental save every 300 images
            if (i + 1) % 300 == 0:
                with open(output, "w") as f:
                    json.dump(results, f, indent=2)

    pbar.close()

    elapsed = pbar.format_dict["elapsed"]
    rate = len(files) / elapsed if elapsed > 0 else 0
    print(f"\nDone: {pass_count} pass, {reject_count} rejected, {err_count} errors "
          f"({elapsed:.0f}s, {rate:.1f} img/s)", flush=True)

    # Show top reject signals
    from collections import Counter
    signal_counts = Counter()
    for r in results.values():
        for s in r.get("reject_signals", []):
            signal_counts[s] += 1
    if signal_counts:
        print("\nTop reject signals:", flush=True)
        for signal, count in signal_counts.most_common(15):
            print(f"  {signal}: {count}", flush=True)

    with open(output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {output}", flush=True)


@click.command()
@click.option("--dir", "image_dir", required=True, type=click.Path(exists=True), help="Image directory")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output JSON path")
@click.option("--url", default="http://localhost:8000", help="JoyCaption service URL")
@click.option("--concurrency", "-j", type=int, default=6, help="Number of concurrent requests")
@click.option("--force", is_flag=True, default=False, help="Reprocess all images (ignore existing results)")
def main(image_dir, output, url, concurrency, force):
    """Batch classify images via JoyCaption HTTP service.

    Resumes by default — skips files already in the output JSON.
    Use --force to reprocess everything from scratch.
    """
    asyncio.run(run_batch(Path(image_dir), Path(output), url, concurrency, force=force))


if __name__ == "__main__":
    main()
