"""Build UNIFIED manifest + metadata for the entire fake-video collection
by scanning mp4 files on disk (not by reading shard manifest CSVs).

The mp4 files are the source of truth. ComfyUI's `VHS_VideoCombine` node
embeds the full workflow JSON into each mp4's `prompt` metadata tag, so we
can recover the positive prompt text even after the shard manifests have
been cleaned up. ffprobe gives us width/height/fps/duration/codec/etc.

Output, at `data/videos/fake/`:
  - `manifest.csv`  — one row per clip: generator, source, filepath,
    real_clip, model, prompt_preview, timestamp.
  - `metadata.csv` — same identifiers plus ffprobed video properties
    (width, height, fps, duration_s, codec, bitrate, pixel_format, file_size).

`filepath` is `<generator>/<source>/<stem>.mp4` — the unique key across the
collection (raw `real_clip` stems collide because different generators
share the same source-clip SHA).

Usage:
    uv run python -m generate.build_dataset_metadata --root data/videos/fake

    # Also remove stale per-dataset manifest.csv / manifest_shard*.csv files:
    uv run python -m generate.build_dataset_metadata --root data/videos/fake --clean
"""
from __future__ import annotations

import csv
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import click
from tqdm import tqdm

from shared.paths import REPO_ROOT

from generate.common import is_source_clip

MANIFEST_COLUMNS = [
    "generator", "source", "filepath", "real_clip",
    "model", "prompt_preview", "timestamp",
]

METADATA_COLUMNS = [
    "generator", "source", "filepath", "real_clip", "model",
    "width", "height", "fps", "duration_s",
    "codec", "bitrate", "pixel_format", "file_size",
    "timestamp",
]

# Matches a positive prompt embedded in the ComfyUI workflow JSON. Different
# wrappers name the input slightly differently:
#   Wan*, Hunyuan: "positive_prompt"
#   CogVideoX:     "prompt"   (inside CogVideoTextEncode)
#   LTX, misc:     "prompt" / "text"
# We try the specific keys first so we don't pick up the negative prompt or
# an unrelated string input.
_PROMPT_KEY_CANDIDATES = ("positive_prompt", "prompt_text", "prompt", "text")
_PROMPT_LEN = 250


def _iter_clip_mp4s(d: Path):
    return (p for p in d.glob("*.mp4") if is_source_clip(p))


def find_dataset_dirs(root: Path) -> list[tuple[str, str, Path]]:
    """Find (generator, source, dir) for every <generator>/<source>/ under root
    that contains at least one clip mp4."""
    seen: set[Path] = set()
    for mp4 in root.rglob("*.mp4"):
        if not is_source_clip(mp4):
            continue
        rel = mp4.parent.relative_to(root)
        if len(rel.parts) == 2:
            seen.add(mp4.parent)
    out: list[tuple[str, str, Path]] = []
    for d in sorted(seen):
        generator, source = d.relative_to(root).parts
        out.append((generator, source, d))
    return out


def _find_prompt_in_workflow(node: object) -> str | None:
    """Depth-first search a ComfyUI workflow dict for a likely positive prompt."""
    if isinstance(node, dict):
        # Prefer a direct positive_prompt string at this level.
        for key in _PROMPT_KEY_CANDIDATES:
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                return v
        for v in node.values():
            found = _find_prompt_in_workflow(v)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_prompt_in_workflow(v)
            if found:
                return found
    return None


def _extract_prompt(workflow_json: str | None) -> str:
    if not workflow_json:
        return ""
    # VHS_VideoCombine sometimes wraps the workflow dict in an extra JSON
    # string layer, so `json.loads` can return a str on first decode. Keep
    # decoding until we get a dict (or stop making progress).
    wf: object = workflow_json
    for _ in range(3):
        if isinstance(wf, str):
            try:
                wf = json.loads(wf)
            except json.JSONDecodeError:
                return ""
        else:
            break
    if not isinstance(wf, (dict, list)):
        return ""
    # The workflow dict looks like {node_id: {class_type, inputs: {...}}}.
    # We care about positive_prompt inside the `inputs` of *TextEncode nodes,
    # preferring those whose node id contains "positive" or the class_type
    # contains "Positive" — otherwise first match wins.
    best: str | None = None
    if isinstance(wf, dict):
        for node_id, node in wf.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs", {})
            if not isinstance(inputs, dict):
                continue
            # Skip nodes that look like a negative branch.
            lowered_id = str(node_id).lower()
            class_type = str(node.get("class_type", "")).lower()
            if "negative" in lowered_id or "negative" in class_type:
                continue
            for key in _PROMPT_KEY_CANDIDATES:
                v = inputs.get(key)
                if isinstance(v, str) and v.strip():
                    if "positive" in lowered_id or "positive" in class_type:
                        return v  # best possible match — return immediately
                    if best is None:
                        best = v
    if best is not None:
        return best
    # Fallback: recursive search anywhere.
    return _find_prompt_in_workflow(wf) or ""


_FFPROBE_JSON_CMD = [
    "ffprobe", "-v", "quiet", "-print_format", "json",
    "-show_format", "-show_streams",
]


def _probe_mp4(path: Path) -> dict | None:
    """Single ffprobe call returning (video props + embedded prompt + creation_time)."""
    try:
        r = subprocess.run(
            _FFPROBE_JSON_CMD + [str(path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return None

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if not video_stream:
        return None

    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) or {}

    # fps: avg_frame_rate is "NUM/DEN"
    fps = 0.0
    fr = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1"
    try:
        num, den = fr.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    # timestamp: prefer the mp4's embedded creation_time (from VHS_VideoCombine),
    # fall back to the container-level tag, then file mtime.
    stream_tags = video_stream.get("tags", {}) or {}
    timestamp = (
        stream_tags.get("creation_time")
        or tags.get("creation_time")
        or ""
    )
    if not timestamp:
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()

    prompt_preview = _extract_prompt(tags.get("prompt"))[:_PROMPT_LEN]

    return {
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": round(fps, 3),
        "duration_s": round(float(fmt.get("duration", 0.0)), 3),
        "codec": video_stream.get("codec_name", ""),
        "bitrate": int(fmt.get("bit_rate", 0) or 0),
        "pixel_format": video_stream.get("pix_fmt", ""),
        "file_size": int(fmt.get("size", 0) or path.stat().st_size),
        "timestamp": timestamp,
        "prompt_preview": prompt_preview,
    }


def _build_row(mp4_path: Path, generator: str, source: str, model: str,
               caption_fallback: str = "") -> tuple[dict, dict] | None:
    """Build (manifest_row, metadata_row) for one mp4. Returns None on probe failure."""
    p = _probe_mp4(mp4_path)
    if p is None:
        return None
    stem = mp4_path.name
    filepath = f"{generator}/{source}/{stem}"
    prompt_preview = p["prompt_preview"] or caption_fallback[:_PROMPT_LEN]
    manifest = {
        "generator": generator,
        "source": source,
        "filepath": filepath,
        "real_clip": stem,
        "model": model,
        "prompt_preview": prompt_preview,
        "timestamp": p["timestamp"],
    }
    metadata = {
        "generator": generator,
        "source": source,
        "filepath": filepath,
        "real_clip": stem,
        "model": model,
        "width": p["width"],
        "height": p["height"],
        "fps": p["fps"],
        "duration_s": p["duration_s"],
        "codec": p["codec"],
        "bitrate": p["bitrate"],
        "pixel_format": p["pixel_format"],
        "file_size": p["file_size"],
        "timestamp": p["timestamp"],
    }
    return manifest, metadata


# Static per-dataset model labels. These are the `model_tag` values we used
# when the clips were generated. Keyed by (generator, source).
_MODEL_LABELS: dict[tuple[str, str], str] = {
    ("cogvideox_1_5", "instagram"):    "cogvideox-1.5-5b-i2v-50step",
    ("cogvideox_1_5", "youtube"):      "cogvideox-1.5-5b-i2v-50step",
    ("hunyuan_video_1_5", "instagram"): "hunyuan-video-1.5-i2v-720p-cfg-distill-8step",
    ("hunyuan_video_1_5", "youtube"):  "hunyuan-video-1.5-i2v-720p-cfg-distill-8step",
    ("ltx_video_2.3", "instagram"):    "ltx-2.3-22b-dev-lora-flf2v",
    ("ltx_video_2.3", "youtube"):      "ltx-2.3-22b-dev-lora-flf2v-yt",
    ("wan_2_1_flf", "instagram"):      "wan-2.1-14b-flf2v-720p",
    ("wan_2_1_flf", "youtube"):        "wan-2.1-14b-flf2v-720p",
    ("wan_2_2", "instagram"):          "wan-2.2-14b-i2v-distill-5step-720p",
    ("wan_2_2", "youtube"):            "wan-2.2-14b-i2v-distill-5step-720p",
    ("hailuo02", "instagram"):         "hailuo-02-i2v",
    ("kling26", "instagram"):          "kling-v2-6-pro-i2v-5s",
    ("luma_ray2", "instagram"):        "luma-ray-2-i2v",
    ("runway_gen4", "instagram"):      "runway-gen-4-turbo-i2v",
    ("sora2", "instagram"):            "sora-2-std-i2v-720x1280-5s",
    ("veo3", "instagram"):             "veo-3-i2v",
}


def _load_source_captions(source: str) -> dict[str, str]:
    """Load video captions for a source (e.g. instagram, youtube).

    Used as a fallback when an mp4 has no embedded prompt (older LTX IG clips
    saved before VHS_VideoCombine embedded workflow JSON). The mapping is
    real_clip → caption text.
    """
    captions_path = REPO_ROOT / "data" / "videos" / "real" / source / "video_captions.json"
    if not captions_path.exists():
        return {}
    try:
        with captions_path.open() as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for stem, entry in raw.items():
            if isinstance(entry, dict):
                cap = entry.get("caption", "")
            else:
                cap = str(entry)
            if cap:
                out[stem] = cap
    return out


def build_unified(root: Path, workers: int, dry_run: bool = False) -> tuple[int, int, int]:
    """Build root/manifest.csv and root/metadata.csv by scanning mp4 files.

    With dry_run=True, scan + ffprobe everything and print the summary, but
    do not write the unified CSVs (so existing files are untouched).

    Returns (datasets, rows_written, probe_failures).
    """
    datasets = find_dataset_dirs(root)
    click.echo(f"Found {len(datasets)} dataset(s) under {root}")

    # Cache captions per source (instagram, youtube, ...) for fallback.
    captions_by_source: dict[str, dict[str, str]] = {}
    jobs: list[tuple[Path, str, str, str, str]] = []
    for generator, source, d in datasets:
        if source not in captions_by_source:
            captions_by_source[source] = _load_source_captions(source)
        caps = captions_by_source[source]
        mp4s = sorted(_iter_clip_mp4s(d))
        model = _MODEL_LABELS.get((generator, source), "")
        for mp4 in mp4s:
            jobs.append((mp4, generator, source, model, caps.get(mp4.name, "")))
        click.echo(
            f"  {generator}/{source}: {len(mp4s)} mp4s  model={model or '(unknown)'}"
            f"  captions_avail={len(caps)}"
        )

    manifest_path = root / "manifest.csv"
    metadata_path = root / "metadata.csv"
    ok = fail = 0

    if dry_run:
        # Probe but discard rows — surface the failure count, leave files alone.
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_build_row, *job) for job in jobs]
            for fut in tqdm(as_completed(futs), total=len(futs),
                            desc="ffprobe (dry-run)", ncols=80):
                result = fut.result()
                if result is None:
                    fail += 1
                else:
                    ok += 1
        click.echo(f"[dry-run] would write {manifest_path} ({ok} rows)")
        click.echo(f"[dry-run] would write {metadata_path} ({ok} rows, "
                   f"{fail} probe failures)")
        return len(datasets), ok, fail

    with manifest_path.open("w", newline="") as mf, \
            metadata_path.open("w", newline="") as md:
        mw = csv.DictWriter(mf, fieldnames=MANIFEST_COLUMNS)
        dw = csv.DictWriter(md, fieldnames=METADATA_COLUMNS)
        mw.writeheader()
        dw.writeheader()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_build_row, *job) for job in jobs]
            for fut in tqdm(as_completed(futs), total=len(futs), desc="ffprobe", ncols=80):
                result = fut.result()
                if result is None:
                    fail += 1
                    continue
                manifest_row, metadata_row = result
                mw.writerow(manifest_row)
                dw.writerow(metadata_row)
                ok += 1

    click.echo(f"wrote {manifest_path} ({ok} rows)")
    click.echo(f"wrote {metadata_path} ({ok} rows, {fail} probe failures)")
    return len(datasets), ok, fail


def clean_stale_manifests(
    root: Path, datasets: list[tuple[str, str, Path]], dry_run: bool = False,
) -> int:
    """Remove stale per-dataset manifest/metadata/shard files.

    With dry_run=True, list paths that *would* be deleted but don't unlink.
    """
    removed = 0
    for _, _, d in datasets:
        for pat in ("manifest.csv", "metadata.csv", "manifest_shard*.csv"):
            for p in d.glob(pat):
                if dry_run:
                    click.echo(f"  [dry-run] would delete {p}")
                else:
                    p.unlink()
                removed += 1
    return removed


@click.command()
@click.option("--root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Collection root (e.g. data/videos/fake)")
@click.option("--workers", default=32, show_default=True, help="ffprobe parallelism")
@click.option("--clean/--no-clean", default=False,
              help="After writing unified files, delete per-dataset manifest.csv, "
                   "metadata.csv, and manifest_shard*.csv")
@click.option("--dry-run", is_flag=True,
              help="Scan + probe everything and report what would happen, but "
                   "DON'T write unified files or delete per-dataset manifests. "
                   "Safe to run anytime — won't touch the data.")
def cli(root: Path, workers: int, clean: bool, dry_run: bool) -> None:
    if dry_run:
        click.echo("[dry-run] no files will be written or deleted.\n")
    build_unified(root, workers=workers, dry_run=dry_run)
    if clean:
        datasets = find_dataset_dirs(root)
        n = clean_stale_manifests(root, datasets, dry_run=dry_run)
        verb = "would remove" if dry_run else "removed"
        click.echo(f"{verb} {n} stale per-dataset manifest/metadata files")


if __name__ == "__main__":
    cli()
