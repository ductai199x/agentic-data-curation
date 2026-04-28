"""Cheap post-cut quality filter for real-video validation.

Rejects clips that are clearly unusable training data without needing any GPU:
  * Low information density  (bits-per-pixel-per-second < 0.020) — auto-adjusts
                              for resolution/fps. Catches CGI/AI-generated and
                              heavily over-compressed clips at any resolution.
  * Too dark                 (mean luminance near black)
  * Too static               (near-zero pixel motion — still image / slideshow)

Bits-per-pixel-per-second (bpps) replaces an absolute bitrate threshold
so a 1080p lecture at 1.4 Mbps (legit low-budget stream) isn't wrongly
rejected while a 1080p over-compressed 1.1 Mbps AI clip is caught.
The fps in the denominator is clamped at 30 so 60fps content isn't
unfairly penalized — modern codecs compress inter-frame deltas well,
so 60fps at 2 Mbps is visually comparable to 30fps at ~1.5 Mbps.
Calibrated on 8 known-bad + 15 random good + edge-case spot-checks.

Single-pass: samples 5 frames via OpenCV, 1 ffprobe call. ~0.1s per clip.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


# Any one gate tripping rejects the clip. Calibrated on the C18 audit.
MIN_BPPS = 0.020            # bits per pixel per second. known-bad: <=0.022; legit low-bpps: >=0.042
MIN_MEAN_LUM = 25.0         # 0-255. known-bad dark: 8.8-16; known-good: 29+
MIN_MEAN_MOTION = 0.02      # 0-1 (fraction). known-bad static: <2%; known-good: >=7.5%


@dataclass
class QualityStats:
    path: Path
    width: int
    height: int
    fps: float
    duration: float
    size_mb: float
    mbps: float
    bpps: float              # bits per pixel per second = mbps*1e6 / (w*h*fps)
    mean_lum: float          # 0-255
    mean_motion: float       # 0-1 (mean |diff| between consecutive sampled frames)


def probe_clip(path: Path, n_samples: int = 5) -> QualityStats | None:
    """Return quality stats for a video clip. None on unreadable."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=size,duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        j = json.loads(r.stdout)
        s = j["streams"][0]
        f = j["format"]
        w, h = int(s["width"]), int(s["height"])
        dur = float(f.get("duration") or 0)
        size = int(f.get("size") or 0)
        if dur <= 0 or size <= 0 or w <= 0 or h <= 0:
            return None
        try:
            fn, fd = s["r_frame_rate"].split("/")
            fps = float(fn) / max(float(fd), 1e-6)
        except Exception:
            fps = 30.0
        mbps = (size * 8 / 1e6) / dur
        # Clamp fps at 30 in the denominator so 60fps content isn't penalized
        # (modern codecs compress inter-frame deltas efficiently at high fps).
        effective_fps = min(max(fps, 1.0), 30.0)
        bpps = (size * 8 / dur) / (w * h * effective_fps)

        cap = cv2.VideoCapture(str(path))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if n < 2:
            cap.release()
            return None
        sample_idx = [int(n * t) for t in np.linspace(0.1, 0.9, n_samples)]
        imgs: list[np.ndarray] = []
        for idx in sample_idx:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, img = cap.read()
            if ok:
                imgs.append(img)
        cap.release()
        if len(imgs) < 2:
            return None

        # Rec.601 luma from BGR (OpenCV default)
        lums = [
            float(np.mean(0.114 * im[..., 0] + 0.587 * im[..., 1] + 0.299 * im[..., 2]))
            for im in imgs
        ]
        # Mean |pixel diff| between consecutive sampled frames, normalized 0-1
        motions = []
        for i in range(1, len(imgs)):
            d = np.abs(imgs[i].astype(np.float32) - imgs[i-1].astype(np.float32)).mean() / 255.0
            motions.append(d)
        return QualityStats(
            path=path, width=w, height=h, fps=fps, duration=dur,
            size_mb=size / 1e6, mbps=mbps, bpps=bpps,
            mean_lum=float(np.mean(lums)),
            mean_motion=float(np.mean(motions)),
        )
    except Exception:
        return None


def check_quality(
    path: Path,
    min_bpps: float = MIN_BPPS,
    min_mean_lum: float = MIN_MEAN_LUM,
    min_mean_motion: float = MIN_MEAN_MOTION,
) -> tuple[bool, str, QualityStats | None]:
    """Return (passed, reason, stats). `reason` is "" on pass."""
    stats = probe_clip(path)
    if stats is None:
        return False, "unreadable", None
    fails = []
    if stats.bpps < min_bpps:
        fails.append(f"low_info({stats.bpps:.4f}bpps<{min_bpps})")
    if stats.mean_lum < min_mean_lum:
        fails.append(f"too_dark(lum={stats.mean_lum:.1f}<{min_mean_lum})")
    if stats.mean_motion < min_mean_motion:
        fails.append(f"too_static(motion={stats.mean_motion*100:.2f}%<{min_mean_motion*100:.0f}%)")
    if fails:
        return False, "; ".join(fails), stats
    return True, "", stats
