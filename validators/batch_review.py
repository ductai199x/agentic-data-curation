"""Batch image review and classification tool.

Creates HTML contact sheets for rapid human review, and provides
a classification interface that can be driven by a VLM or human.

Output: A JSON file mapping each filename to its classification,
which the pipeline uses to filter images.
"""

import json
import base64
from pathlib import Path

from PIL import Image


def create_contact_sheet(
    image_dir: Path,
    output_path: Path,
    suffixes: tuple[str, ...] = (".jpg", ".jpeg", ".png"),
    thumb_size: int = 200,
    cols: int = 5,
) -> int:
    """Create an HTML contact sheet for visual review.

    Returns number of images included.
    """
    files = sorted(
        f for f in image_dir.iterdir()
        if f.suffix.lower() in suffixes
    )

    html = [
        "<!DOCTYPE html><html><head>",
        "<style>",
        "body { background: #1a1a1a; color: #ccc; font-family: monospace; }",
        ".grid { display: grid; grid-template-columns: repeat(%d, 1fr); gap: 8px; }" % cols,
        ".card { background: #2a2a2a; padding: 4px; border-radius: 4px; text-align: center; }",
        ".card img { max-width: 100%; height: auto; max-height: 200px; }",
        ".card .info { font-size: 10px; margin-top: 4px; }",
        ".card.screenshot { border: 2px solid red; }",
        ".card.ai_art { border: 2px solid green; }",
        "</style></head><body>",
        f"<h2>Image Review: {image_dir} ({len(files)} images)</h2>",
        '<div class="grid">',
    ]

    for f in files:
        try:
            img = Image.open(f)
            w, h = img.size
            px = w * h
        except Exception:
            w, h, px = 0, 0, 0

        html.append(f'<div class="card" id="{f.name}">')
        html.append(f'<img src="{f.absolute()}" loading="lazy">')
        html.append(f'<div class="info">{f.name}<br>{w}x{h} ({px/1e6:.1f}MP) {f.suffix}</div>')
        html.append("</div>")

    html.append("</div></body></html>")

    output_path.write_text("\n".join(html))
    return len(files)


def load_classifications(path: Path) -> dict[str, str]:
    """Load existing classifications from JSON."""
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_classifications(path: Path, classifications: dict[str, str]):
    """Save classifications to JSON."""
    path.write_text(json.dumps(classifications, indent=2))


def apply_classifications(
    staging_dir: Path,
    classifications: dict[str, str],
    images_dir: Path | None = None,
    rejected_dir: Path | None = None,
) -> dict:
    """Move files based on classifications.

    Classifications: filename -> "ai_art" | "screenshot" | "meme" | "photo" | "reject"

    Files classified as "ai_art" go to images_dir.
    Everything else goes to rejected_dir.

    Returns dict with counts.
    """
    import shutil

    if images_dir is None:
        images_dir = staging_dir.parent / "images"
    if rejected_dir is None:
        rejected_dir = staging_dir.parent / "rejected"

    images_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    stats = {"moved_to_images": 0, "moved_to_rejected": 0, "not_found": 0}

    for filename, category in classifications.items():
        src = staging_dir / filename
        if not src.exists():
            stats["not_found"] += 1
            continue

        if category == "ai_art":
            shutil.move(str(src), str(images_dir / filename))
            stats["moved_to_images"] += 1
        else:
            shutil.move(str(src), str(rejected_dir / filename))
            stats["moved_to_rejected"] += 1

    return stats
