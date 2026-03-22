"""Split Midjourney 2x2 grid images into individual tiles.

Detection logic:
1. If is_upscaled == "true" in manifest → single image, skip
2. If dimensions match a known base tile size → single image, skip
3. If dimensions match a known 2× grid size → split into 4 tiles
4. Otherwise → skip (unknown format)

Usage:
    uv run python -m validators.split_grids --config configs/midjourney.py [--dry-run] [--output-dir DIR]
"""

import argparse
import csv
import hashlib
import io
import multiprocessing
import shutil
import sys
from pathlib import Path

from PIL import Image

# Known Midjourney v7 base tile dimensions (width, height)
# From empirical analysis of 48K images
KNOWN_BASE_TILES = {
    (1024, 1024),  # 1:1
    (1456, 816),   # 16:9
    (816, 1456),   # 9:16
    (896, 1344),   # 2:3
    (1344, 896),   # 3:2
    (928, 1232),   # 3:4
    (1232, 928),   # 4:3
    (960, 1200),   # 4:5
    (1200, 960),   # 5:4
    (1456, 832),   # 7:4
    (832, 1456),   # 4:7
    (1680, 720),   # 21:9
    (720, 1680),   # 9:21
    (2176, 544),   # 4:1
    (544, 2176),   # 1:4
    (1904, 640),   # 3:1
    (640, 1904),   # 1:3
    (1536, 768),   # 2:1
    (768, 1536),   # 1:2
    (2112, 576),   # 11:3
    (576, 2112),   # 3:11
    (2016, 576),   # 7:2
    (576, 2016),   # 2:7
    (960, 1248),   # ~4:5 variant
    (1248, 960),
    (1344, 768),   # ~16:9 variant
    (768, 1344),
    # Additional base tiles discovered from unknown dimensions
    (864, 1360),
    (1360, 864),
    (928, 1312),
    (1312, 928),
    (1376, 864),
    (864, 1376),
    (1424, 848),
    (848, 1424),
    (1024, 1040),
    (1040, 1024),
    (816, 1472),
    (1472, 816),
    (912, 1296),
    (1296, 912),
    (992, 1200),
    (1200, 992),
    (1712, 704),
    (704, 1712),
    (720, 1648),
    (1648, 720),
    (736, 1600),
    (1600, 736),
    (656, 448),   # very small — may be v7 --quality 0.25
    (448, 656),
}

# Build 2× grid sizes from base tiles
KNOWN_GRID_SIZES = {(w * 2, h * 2) for w, h in KNOWN_BASE_TILES}


def content_hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify_image(width: int, height: int, is_upscaled: str) -> str:
    """Classify an image as 'single', 'grid', or 'unknown'.

    Args:
        width: Image width in pixels
        height: Image height in pixels
        is_upscaled: "true" or "false" from manifest

    Returns:
        'single', 'grid', or 'unknown'
    """
    # Rule 1: Upscaled flag from Discord message content
    if is_upscaled == "true":
        return "single"

    # Rule 2: Dimensions match known base tile
    if (width, height) in KNOWN_BASE_TILES:
        return "single"

    # Rule 3: Dimensions match known 2× grid
    if (width, height) in KNOWN_GRID_SIZES:
        return "grid"

    # Rule 4: If total pixels > 3.5 MP and both dims even, it's a grid
    # (no Midjourney base tile exceeds ~2 MP; grids are 4-5 MP)
    if width % 2 == 0 and height % 2 == 0:
        total_pixels = width * height
        if total_pixels > 3_500_000:
            return "grid"

    return "unknown"


def split_grid(img: Image.Image) -> list[Image.Image]:
    """Split a 2x2 grid image into 4 tiles."""
    w, h = img.size
    half_w, half_h = w // 2, h // 2
    return [
        img.crop((0, 0, half_w, half_h)),           # top-left
        img.crop((half_w, 0, w, half_h)),            # top-right
        img.crop((0, half_h, half_w, h)),             # bottom-left
        img.crop((half_w, half_h, w, h)),             # bottom-right
    ]


def _split_one_grid(args):
    """Worker function for multiprocessing. Returns (tile_rows, original_filename) or None."""
    row, img_path_str, output_dir_str = args
    img_path = Path(img_path_str)
    output_dir = Path(output_dir_str)

    try:
        img = Image.open(img_path)
        tiles = split_grid(img)
    except Exception as e:
        print(f"  Error splitting {img_path.name}: {e}", file=sys.stderr)
        return None

    tile_rows = []
    parent_stem = img_path.stem

    for tile_idx, tile in enumerate(tiles):
        buf = io.BytesIO()
        tile.save(buf, format="PNG")
        tile_bytes = buf.getvalue()
        tile_hash = content_hash_bytes(tile_bytes)
        tile_filename = f"{parent_stem}_{tile_idx}.png"

        tile_path = output_dir / tile_filename
        if not tile_path.exists():
            tile_path.write_bytes(tile_bytes)

        tile_row = dict(row)
        tile_row["filename"] = tile_filename
        tile_row["content_hash"] = tile_hash
        tile_row["width"] = str(tile.size[0])
        tile_row["height"] = str(tile.size[1])
        tile_row["format"] = "PNG"
        tile_row["file_size"] = str(len(tile_bytes))
        tile_row["flair"] = row.get("flair", "").replace(":grid", f":tile{tile_idx}")
        tile_rows.append(tile_row)

    # Delete original grid file
    try:
        img_path.unlink()
    except FileNotFoundError:
        pass

    return tile_rows, row.get("filename", "")


def main():
    parser = argparse.ArgumentParser(description="Split Midjourney grid images into tiles")
    parser.add_argument("--config", "-c", required=True, help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Only report, don't split")
    parser.add_argument("--output-dir", "-o", help="Output directory for tiles (default: staging)")
    parser.add_argument("--limit", "-n", type=int, default=0, help="Process only N images")
    args = parser.parse_args()

    from configs import load_config
    config = load_config(args.config)

    data_dir = Path(f"data/{config.NAME}")
    staging = data_dir / "staging"
    manifest_path = data_dir / "manifest.csv"
    output_dir = Path(args.output_dir) if args.output_dir else staging

    if not manifest_path.exists():
        print("No manifest.csv found", file=sys.stderr)
        return

    # Read manifest
    rows = []
    with open(manifest_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    # Classify all images
    stats = {"single": 0, "grid": 0, "unknown": 0, "missing": 0, "split": 0, "tiles": 0}
    grids_to_split = []

    for row in rows:
        filename = row.get("filename", "")
        w_str = row.get("width", "")
        h_str = row.get("height", "")
        is_up = row.get("is_upscaled", "")

        if not w_str.isdigit() or not h_str.isdigit():
            stats["unknown"] += 1
            continue

        w, h = int(w_str), int(h_str)
        classification = classify_image(w, h, is_up)
        stats[classification] += 1

        if classification == "grid":
            img_path = staging / filename
            if img_path.exists():
                grids_to_split.append((row, img_path))
            else:
                stats["missing"] += 1

    print(f"Classification results:")
    print(f"  Single images: {stats['single']}")
    print(f"  Grids to split: {stats['grid']}")
    print(f"  Unknown: {stats['unknown']}")
    print(f"  Missing files: {stats['missing']}")
    print(f"  Grid files found: {len(grids_to_split)}")

    if args.dry_run:
        return

    if args.limit:
        grids_to_split = grids_to_split[:args.limit]

    # Split grids in parallel
    output_dir.mkdir(parents=True, exist_ok=True)

    # Prepare work items as serializable tuples (row_dict, img_path_str, output_dir_str)
    work_items = [(row, str(img_path), str(output_dir)) for row, img_path in grids_to_split]

    # Filter out already-split grids (tiles already exist)
    filtered_items = []
    for row, img_path_str, out_dir_str in work_items:
        parent_stem = Path(img_path_str).stem
        tile0 = Path(out_dir_str) / f"{parent_stem}_0.png"
        if not tile0.exists():
            filtered_items.append((row, img_path_str, out_dir_str))

    already_done = len(work_items) - len(filtered_items)
    if already_done:
        print(f"  Skipping {already_done} already-split grids")

    num_workers = min(256, multiprocessing.cpu_count(), len(filtered_items) or 1)
    print(f"  Splitting {len(filtered_items)} grids with {num_workers} workers...")
    sys.stdout.flush()

    with multiprocessing.Pool(num_workers) as pool:
        results = pool.imap_unordered(_split_one_grid, filtered_items, chunksize=16)
        new_manifest_rows = []
        split_filenames = set()
        errors = 0

        for i, result in enumerate(results):
            if result is None:
                errors += 1
                continue
            tile_rows, original_filename = result
            new_manifest_rows.extend(tile_rows)
            split_filenames.add(original_filename)
            stats["split"] += 1
            stats["tiles"] += len(tile_rows)

            if (i + 1) % 1000 == 0:
                print(f"  Split {i + 1}/{len(filtered_items)} grids ({stats['tiles']} tiles, {errors} errors)")
                sys.stdout.flush()

    # Also count already-done grids in split_filenames
    for row, img_path_str, _ in work_items:
        parent_stem = Path(img_path_str).stem
        tile0 = Path(work_items[0][2]) / f"{parent_stem}_0.png"
        if tile0.exists() and row.get("filename", "") not in split_filenames:
            split_filenames.add(row.get("filename", ""))

    print(f"\nSplit results:")
    print(f"  Grids split: {stats['split']} (+ {already_done} previously done)")
    print(f"  Tiles created: {stats['tiles']}")
    print(f"  Errors: {errors}")

    # Update manifest: remove grid rows, add tile rows
    if new_manifest_rows:
        from scrapers.base import MANIFEST_FIELDS
        # Read all existing rows, filter out split grids
        kept_rows = [r for r in rows if r.get("filename", "") not in split_filenames]
        all_rows = kept_rows + new_manifest_rows

        # Backup original manifest
        backup = manifest_path.with_suffix(".csv.bak")
        shutil.copy2(manifest_path, backup)

        # Write updated manifest
        with open(manifest_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"  Manifest updated: {len(kept_rows)} kept + {len(new_manifest_rows)} tiles = {len(all_rows)} total")
        print(f"  Backup: {backup}")


if __name__ == "__main__":
    main()
