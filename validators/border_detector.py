"""Detect images with uniform white/black borders (scanned photos, film edges, frames).

Used to filter out non-native-digital photos from Instagram real photographer datasets.
"""
from pathlib import Path

import numpy as np
from PIL import Image


def detect_borders(
    img_path: str | Path,
    border_width: int = 8,
    std_threshold: float = 3.0,
    contrast_threshold: float = 30.0,
    min_sides: int = 2,
) -> dict:
    """Detect if an image has uniform white/black borders.

    Checks each edge for a thin strip of near-pure white (>245) or black (<10)
    pixels with high contrast against the adjacent content.

    Args:
        img_path: Path to image file.
        border_width: Pixels from edge to check.
        std_threshold: Max std dev within border to consider "uniform".
        contrast_threshold: Min brightness difference between border and content.
        min_sides: Minimum number of bordered sides to flag.

    Returns:
        dict with 'has_border' (bool), 'borders' (list of dicts), 'n_sides' (int).
    """
    img = Image.open(img_path).convert("L")
    arr = np.array(img).astype(float)
    h, w = arr.shape

    if h < 60 or w < 60:
        return {"has_border": False, "borders": [], "n_sides": 0}

    bw = border_width
    borders = []

    checks = {
        "top": (arr[:bw, :], arr[bw : bw * 3, :]),
        "bottom": (arr[-bw:, :], arr[-bw * 3 : -bw, :]),
        "left": (arr[:, :bw], arr[:, bw : bw * 3]),
        "right": (arr[:, -bw:], arr[:, -bw * 3 : -bw]),
    }

    for side, (border_region, inner_region) in checks.items():
        border_mean = border_region.mean()
        border_std = border_region.std()
        inner_mean = inner_region.mean()

        is_white = border_mean > 245
        is_black = border_mean < 10
        if not (is_white or is_black):
            continue
        if border_std > std_threshold:
            continue

        contrast = abs(border_mean - inner_mean)
        if contrast < contrast_threshold:
            continue

        borders.append(
            {
                "side": side,
                "color": "white" if is_white else "black",
                "contrast": float(contrast),
            }
        )

    return {
        "has_border": len(borders) >= min_sides,
        "borders": borders,
        "n_sides": len(borders),
    }
