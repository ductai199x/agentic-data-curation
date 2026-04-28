"""Frame-rate upsampling for fake-video clips via RIFE 4.26.

Walks a root of `<generator>/<source>/<stem>.mp4` (e.g.
`data/videos/fake/`), filters to clips at or below `--source-fps-max`
(default 17 — catches the 16fps cluster: Wan 2.x + CogVideoX), runs RIFE
2× interpolation, and writes the upsampled output to
`<out_root>/<generator>/<source>/<stem>.mp4`.

The model is loaded ONCE per worker and reused across all clips in that
worker's shard — much faster than `inference_video.py`'s per-call CLI
spawn overhead.

Usage:
    # Single shard (one GPU)
    CUDA_VISIBLE_DEVICES=3 SHARDS=8 SHARD_ID=0 \
        uv run python -m video_gen.interpolate_fps \
            --root data/videos/fake \
            --out-root data/videos/fake_30fps_rife \
            --target-fps 30

    # Multi-GPU launch (8 shards via scripts/launch_interpolate.sh):
    bash scripts/launch_interpolate.sh start
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import click
import cv2
import numpy as np
import torch
from tqdm import tqdm

from video_gen.common import is_source_clip

REPO = Path(__file__).resolve().parents[1]
RIFE_DIR = REPO / "third_party" / "vfi_bench" / "Practical-RIFE"


def _load_rife_model():
    """Load Practical-RIFE 4.26 once. Returns the loaded model object."""
    sys.path.insert(0, str(RIFE_DIR))
    from train_log.RIFE_HDv3 import Model
    torch.set_grad_enabled(False)
    torch.backends.cudnn.enabled = True
    torch.backends.cudnn.benchmark = True
    model = Model()
    if not hasattr(model, "version"):
        model.version = 0
    model.load_model(str(RIFE_DIR / "train_log"), -1)
    model.eval()
    model.device()
    return model


def _make_inference(model, I0, I1, n: int, scale: float = 1.0):
    """Generate n intermediate frames between I0 and I1."""
    if model.version >= 3.9:
        return [model.inference(I0, I1, (i + 1) / (n + 1), scale) for i in range(n)]
    middle = model.inference(I0, I1, scale)
    if n == 1:
        return [middle]
    first = _make_inference(model, I0, middle, n // 2, scale)
    second = _make_inference(model, middle, I1, n // 2, scale)
    return first + ([middle] if n % 2 else []) + second


def _pad(frame_t: torch.Tensor, scale: float):
    """Pad to multiples of (32 / scale) so RIFE's pyramid alignment works."""
    n, c, h, w = frame_t.shape
    tmp = max(128, int(32 / scale))
    ph = ((h - 1) // tmp + 1) * tmp
    pw = ((w - 1) // tmp + 1) * tmp
    pad = (0, pw - w, 0, ph - h)
    return torch.nn.functional.pad(frame_t, pad), (h, w)


def interpolate_clip(model, src: Path, dst: Path, multi: int = 2,
                     target_fps: int | None = None, scale: float = 1.0) -> None:
    """Interpolate one clip in-process using a preloaded RIFE model."""
    cap = cv2.VideoCapture(str(src))
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_fps = src_fps * multi  # e.g. 16 -> 32 with multi=2
    final_fps = target_fps if target_fps is not None else out_fps

    # We write at out_fps then resample with ffmpeg if final_fps differs.
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_h264 = dst.parent / f".{dst.name}.tmp.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(tmp_h264), fourcc, out_fps, (width, height))

    ret, prev = cap.read()
    if not ret:
        cap.release()
        writer.release()
        tmp_h264.unlink(missing_ok=True)
        raise RuntimeError(f"empty video: {src}")

    def to_tensor(f):
        # BGR uint8 HWC -> RGB float CHW [0,1] on GPU
        rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
        t = torch.from_numpy(rgb.transpose(2, 0, 1)).float().cuda().unsqueeze(0) / 255.0
        return t

    def from_tensor(t, hw):
        h, w = hw
        arr = (t[0, :, :h, :w].permute(1, 2, 0).cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    writer.write(prev)  # write original first frame
    prev_t, hw = _pad(to_tensor(prev), scale)

    for _ in range(n_frames - 1):
        ret, curr = cap.read()
        if not ret:
            break
        curr_t, _ = _pad(to_tensor(curr), scale)
        # Insert (multi - 1) frames between prev and curr
        if multi > 1:
            mids = _make_inference(model, prev_t, curr_t, multi - 1, scale)
            for m in mids:
                writer.write(from_tensor(m, hw))
        writer.write(curr)
        prev_t = curr_t

    cap.release()
    writer.release()

    # Re-encode with libx264 main + faststart, optionally resample to target_fps
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(tmp_h264),
    ]
    if target_fps is not None and abs(final_fps - out_fps) > 0.1:
        cmd += ["-filter:v", f"fps={target_fps}"]
    cmd += [
        "-c:v", "libx264", "-profile:v", "main", "-level", "4.0",
        "-pix_fmt", "yuv420p", "-crf", "19", "-movflags", "+faststart",
        str(dst),
    ]
    subprocess.run(cmd, check=True)
    tmp_h264.unlink(missing_ok=True)


def find_clips(root: Path, source_fps_max: float, metadata_csv: Path | None) -> list[tuple[Path, str]]:
    """Return list of (src_path, rel_subpath) for clips at fps <= source_fps_max.

    rel_subpath is `<generator>/<source>/<stem>.mp4` so we mirror the layout
    in out_root.
    """
    if metadata_csv and metadata_csv.exists():
        clips = []
        with metadata_csv.open() as f:
            for row in csv.DictReader(f):
                if float(row["fps"]) <= source_fps_max:
                    src = root / row["filepath"]
                    if is_source_clip(src) and src.exists():
                        clips.append((src, row["filepath"]))
        return clips
    # Fallback: walk directory tree
    out = []
    for mp4 in root.rglob("*.mp4"):
        if not is_source_clip(mp4):
            continue
        rel = mp4.relative_to(root)
        if len(rel.parts) != 3:
            continue
        # Probe fps
        cap = cv2.VideoCapture(str(mp4))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        if fps and fps <= source_fps_max:
            out.append((mp4, str(rel)))
    return out


@click.command()
@click.option("--root", required=True,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Source root, e.g. data/videos/fake")
@click.option("--out-root", required=True,
              type=click.Path(file_okay=False, path_type=Path),
              help="Output root, e.g. data/videos/fake_30fps_rife")
@click.option("--metadata-csv", default=None,
              type=click.Path(path_type=Path),
              help="Optional metadata.csv for fast fps lookup. "
                   "Defaults to <root>/metadata.csv")
@click.option("--source-fps-max", default=17.0, show_default=True,
              help="Only interpolate clips with fps <= this (catches 16fps cluster).")
@click.option("--target-fps", default=30, show_default=True,
              help="Output fps. RIFE 2x runs internally; ffmpeg resamples to target.")
@click.option("--multi", default=2, show_default=True,
              help="RIFE interpolation multiplier (must be a power of 2).")
@click.option("--scale", default=1.0,
              type=click.Choice(["0.25", "0.5", "1.0", "2.0", "4.0"]),
              help="RIFE scale factor (lower for 4k input).")
def main(root: Path, out_root: Path, metadata_csv: Path | None,
         source_fps_max: float, target_fps: int, multi: int, scale: str) -> None:
    if metadata_csv is None:
        cand = root / "metadata.csv"
        metadata_csv = cand if cand.exists() else None

    shards = int(os.environ.get("SHARDS", "1"))
    shard_id = int(os.environ.get("SHARD_ID", "0"))

    print(f"[shard {shard_id}/{shards}] scanning {root}", flush=True)
    all_clips = find_clips(root, source_fps_max, metadata_csv)
    print(f"[shard {shard_id}/{shards}] found {len(all_clips)} candidate clips", flush=True)

    # Stable shard split by index
    my_clips = [c for i, c in enumerate(all_clips) if i % shards == shard_id]

    # Skip already-done
    todo = []
    for src, rel in my_clips:
        dst = out_root / rel
        if dst.exists() and dst.stat().st_size > 1024:
            continue
        todo.append((src, dst))

    print(f"[shard {shard_id}/{shards}] my clips: {len(my_clips)}  todo: {len(todo)}", flush=True)
    if not todo:
        return

    print(f"[shard {shard_id}/{shards}] loading RIFE 4.26...", flush=True)
    t0 = time.time()
    model = _load_rife_model()
    print(f"[shard {shard_id}/{shards}] loaded in {time.time()-t0:.1f}s", flush=True)

    ok = fail = 0
    bar = tqdm(todo, desc=f"shard{shard_id}", ncols=80)
    for src, dst in bar:
        try:
            interpolate_clip(model, src, dst, multi=multi, target_fps=target_fps, scale=float(scale))
            ok += 1
        except Exception as e:
            fail += 1
            print(f"[shard {shard_id}] FAIL {src.name}: {type(e).__name__}: {e}", flush=True)
        bar.set_postfix(ok=ok, fail=fail)

    print(f"[shard {shard_id}/{shards}] done. ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    main()
