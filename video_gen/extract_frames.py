"""Pre-extract first + last PNG frames for every validated video clip.

Idempotent: resumes by skipping clips whose frame files already exist.
`build_jobs` assumes frames are present — run this once per new batch of
clips before generating, rather than lazily extracting during generation.

Usage:
    PYTHONPATH=/home/tai/1-workdir/09-agent-data-curation \\
      uv run python -m video_gen.extract_frames \\
        --clips data/videos/real/instagram/validated \\
        --out data/videos/real/instagram/frames
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import click
from tqdm import tqdm

from video_gen.common import extract_frame, extract_last_frame, list_clips


def _extract_both(clip: Path, out: Path, force: bool) -> tuple[str, bool, bool, bool]:
    stem = clip.stem
    first = out / f"{stem}_first.png"
    last = out / f"{stem}_last.png"

    need_first = force or not first.exists()
    need_last = force or not last.exists()

    if not need_first and not need_last:
        return stem, True, True, True  # skipped

    ok_first = (not need_first) or extract_frame(clip, 0.0, first)
    ok_last = (not need_last) or extract_last_frame(clip, last)
    return stem, ok_first, ok_last, False


@click.command()
@click.option("--clips", type=click.Path(path_type=Path), required=True,
              help="Dir of validated .mp4 clips")
@click.option("--out", type=click.Path(path_type=Path), required=True,
              help="Dir to write {stem}_first.png / {stem}_last.png")
@click.option("--force", is_flag=True, help="Re-extract even when frames already exist")
@click.option("--workers", type=int, default=32, show_default=True,
              help="Parallel ffmpeg extractions")
def main(clips: Path, out: Path, force: bool, workers: int):
    out.mkdir(parents=True, exist_ok=True)
    clip_list = list_clips(clips)
    print(f"found {len(clip_list)} clips", flush=True)

    done_first = done_last = skipped = fail_first = fail_last = 0
    broken: list[str] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_extract_both, clip, out, force) for clip in clip_list]
        for fut in tqdm(as_completed(futs), total=len(futs), ncols=80, desc="extract"):
            stem, ok_first, ok_last, was_skipped = fut.result()
            if was_skipped:
                skipped += 1
                continue
            if ok_first:
                done_first += 1
            else:
                fail_first += 1
                broken.append(f"{stem} (first)")
            if ok_last:
                done_last += 1
            else:
                fail_last += 1
                broken.append(f"{stem} (last)")

    print(f"\nfirst: {done_first} new, {fail_first} failed")
    print(f"last:  {done_last} new, {fail_last} failed")
    print(f"skipped (already present): {skipped}")
    if broken:
        print(f"\n{len(broken)} extraction failures (likely corrupt clips):")
        for b in broken[:30]:
            print(f"  {b}")
        if len(broken) > 30:
            print(f"  ...and {len(broken) - 30} more")
        sys.exit(1)


if __name__ == "__main__":
    main()
