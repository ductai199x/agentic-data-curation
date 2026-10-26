"""Caption + ranking loaders, plus the ClipJob list builder."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from shared.clip_utils import list_clips
from shared.manifest import ClipJob


def load_captions(captions_path: Path, key: str = "caption") -> dict[str, str]:
    """Load the SALMONN caption JSON, returning {filename: <key-field>}.

    The JSON value for each clip may be a bare string (legacy) or a dict with
    at least a `caption` field and optionally `short_caption` (added by
    `generate.rewrite_captions`). When `key != 'caption'`, clips missing that
    key fall back to the long `caption` field so nothing ever returns empty.
    """
    data = json.load(open(captions_path))
    out = {}
    for fn, v in data.items():
        if isinstance(v, dict):
            picked = v.get(key) or v.get("caption")
            if picked:
                out[fn] = picked
        elif isinstance(v, str):
            out[fn] = v
    return out


def load_ranking(rank_file: Path) -> dict[str, int]:
    """Read a diversity_rank.csv (`rank, stem, ...`) into `{stem: rank}`."""
    ranking: dict[str, int] = {}
    with open(rank_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            stem = row.get("stem")
            try:
                rank = int(row.get("rank", "0"))
            except Exception:
                continue
            if stem and rank:
                ranking[stem] = rank
    return ranking


def build_jobs(
    clips_dir: Path,
    captions_path: Path,
    frames_dir: Path,
    rank_file: Path | None = None,
    max_clips: int | None = None,
    caption_key: str = "caption",
) -> list[ClipJob]:
    """Build the full list of generation jobs.

    For each validated clip that has a SALMONN caption:
      - extract first/last frames (cached in frames_dir)
      - create a ClipJob
    Clips without captions are skipped.

    If `rank_file` is set, the output is filtered + ordered by the ranks in
    that CSV (columns `rank`, `stem`) and truncated to `max_clips` (if set).
    If only `max_clips` is set, the first K in directory order are returned.
    """
    captions = load_captions(captions_path, key=caption_key)

    # If rank_file is set, only process clips in the ranking (skip the rest)
    allowed_stems: set[str] | None = None
    ranking: dict[str, int] = {}
    if rank_file is not None:
        ranking = load_ranking(rank_file)  # {stem: rank}
        allowed_stems = set(ranking.keys())
        if max_clips is not None and max_clips > 0:
            # Only need the top-K stems — skip everything else
            top_k = sorted(ranking.items(), key=lambda kv: kv[1])[:max_clips]
            allowed_stems = {stem for stem, _ in top_k}

    seen_stems: set[str] = set()
    jobs: list[ClipJob] = []
    for clip in list_clips(clips_dir):
        stem = clip.stem
        if stem in seen_stems:
            continue
        seen_stems.add(stem)
        if allowed_stems is not None and stem not in allowed_stems:
            continue
        cap = captions.get(clip.name)
        if not cap:
            continue
        first = frames_dir / f"{stem}_first.png"
        last = frames_dir / f"{stem}_last.png"

        # Frames must be pre-extracted via `python -m generate.extract_frames`.
        # Skip (with warning) any clip missing its first frame. Last frame is
        # optional: FLF workflows check `job.last_frame.exists()`, I2V ignores.
        if not first.exists():
            print(f"[build_jobs] skipping {stem}: missing first frame "
                  f"(run `python -m generate.extract_frames` to pre-extract)",
                  flush=True)
            continue

        jobs.append(ClipJob(
            real_clip=clip, first_frame=first, last_frame=last,
            prompt=cap, duration=0.0,
        ))

    if rank_file is not None:
        jobs.sort(key=lambda j: ranking.get(j.real_clip.stem, 999999))

    if max_clips is not None and max_clips > 0:
        jobs = jobs[:max_clips]

    return jobs
