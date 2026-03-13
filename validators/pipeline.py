"""Full validation pipeline.

Orchestrates: JoyCaption → structural → FSD detector → sort into
images/ (passed) vs rejected/ (failed).

Three-tier validation:
1. Content: JoyCaption VLM filters screenshots, memes, UI captures (GPU, ~2-3s/image)
2. Structural: pixel count, aspect ratio, format, EXIF (fast, local)
3. Forensic: FSD detector z-score (GPU, batch)

Images pass if they survive all tiers.
"""

import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from tqdm import tqdm
from pathlib import Path

from validators.image_validator import validate_image, ValidationResult
from configs import load_config


@dataclass
class PipelineResult:
    """Combined result from all validation tiers."""
    path: Path
    passed: bool
    # Tier 1: structural
    structural: ValidationResult | None = None
    structural_passed: bool = False
    # Tier 2: forensic (FSD)
    fsd_z_score: float | None = None
    fsd_is_fake: bool = False
    # Tier 3: VLM
    vlm_classification: str = ""
    vlm_confidence: float = 0.0
    # Final disposition
    destination: str = ""  # "images", "rejected", "staging_webp"
    rejection_reasons: list[str] = field(default_factory=list)


def run_structural_validation(
    image_dir: Path,
    config,
    suffixes: tuple[str, ...] = (".jpg", ".jpeg", ".png"),
) -> dict[str, ValidationResult]:
    """Run tier 1 structural validation on all images in a directory."""
    files = sorted(f for f in image_dir.iterdir() if f.suffix.lower() in suffixes)
    results = {}
    for f in tqdm(files, desc="Structural", unit="img", file=sys.stderr):
        result = validate_image(
            f,
            min_pixels=getattr(config, "MIN_PIXELS", 200_000),
            max_pixels=getattr(config, "MAX_PIXELS", 5_000_000),
            expected_formats=getattr(config, "EXPECTED_FORMATS", ["JPEG", "PNG"]),
            max_avg_quantization=getattr(config, "MAX_AVG_QUANTIZATION", 15.0),
            camera_exif_tags=getattr(config, "CAMERA_EXIF_TAGS", []),
            known_aspect_ratios=getattr(config, "KNOWN_ASPECT_RATIOS", []),
            aspect_ratio_tolerance=getattr(config, "ASPECT_RATIO_TOLERANCE", 0.05),
        )
        results[f.name] = result
    return results


def run_fsd_detection(
    image_dir: Path,
    threshold: float = -2.0,
    weights_dir: str = "validators/fsd-weights",
) -> dict[str, dict]:
    """Run tier 2 FSD detection on all images.

    Uses fsd-score CLI installed as a local dependency.
    """
    try:
        abs_dir = str(Path(image_dir).resolve())
        result = subprocess.run(
            ["uv", "run", "fsd-score", "--dir", abs_dir, "--csv",
             "--threshold", str(threshold),
             "--weights-dir", weights_dir],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            print(f"FSD error: {result.stderr[:500]}")
            return {}

        fsd_results = {}
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return {}

        reader = csv.DictReader(lines)
        for row in reader:
            filename = Path(row["file"]).name
            fsd_results[filename] = {
                "z_score": float(row["z_score"]),
                "is_fake": row["is_fake"] == "True",
                "raw_score": float(row["raw_score"]),
            }
        return fsd_results

    except Exception as e:
        print(f"FSD detection failed: {e}")
        return {}


def load_joycaption_results(path: Path) -> dict[str, dict]:
    """Load JoyCaption classification results from JSON."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def run_pipeline(
    config,
    data_dir: Path = Path("data/grok"),
    fsd_threshold: float = -2.0,
    relaxed_mode: bool = False,
    captions_path: Path | None = None,
    skip_fsd: bool = False,
    force: bool = False,
) -> list[PipelineResult]:
    """Run the full validation pipeline.

    Resumes by default — only processes files still in staging/.
    Use force=True to move images/ and rejected/ back to staging/ and revalidate.

    Args:
        config: Generator config module (e.g. loaded from configs/grok.py)
        data_dir: Root data directory (contains staging/, images/, rejected/)
        fsd_threshold: FSD z-score threshold (more negative = stricter)
        relaxed_mode: If True, only reject on pixel count + FSD (ignore
                     compression quality for Reddit-sourced images)
        captions_path: Path to pre-computed JoyCaption results JSON.
                      If None, uses data_dir/captions.json.
        skip_fsd: Skip FSD detection (useful for quick runs).
        force: Move all images back to staging and revalidate from scratch.

    Returns:
        List of PipelineResult for each image.
    """
    staging_dir = data_dir / "staging"
    images_dir = data_dir / "images"
    rejected_dir = data_dir / "rejected"

    images_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)

    # --force: move everything back to staging for full revalidation
    if force:
        restored = 0
        for src_dir in (images_dir, rejected_dir):
            for f in src_dir.iterdir():
                if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    shutil.move(str(f), str(staging_dir / f.name))
                    restored += 1
        if restored:
            print(f"Force mode: moved {restored} images back to staging/")

    if not staging_dir.exists() or not any(staging_dir.iterdir()):
        print("No images in staging directory.")
        return []

    print(f"Running validation pipeline on {staging_dir}")
    print(f"  FSD threshold: {fsd_threshold}")
    print(f"  Relaxed mode: {relaxed_mode}")
    print()

    # Tier 0: JoyCaption content filtering
    if captions_path is None:
        captions_path = data_dir / "captions.json"

    # Content filter: reject any image with reject_signals from JoyCaption.
    # This includes screenshots, tables, logos, illustrations, cartoons, anime,
    # cgi, comics, etc. — we only want photorealistic AI-generated images.
    # Do NOT use is_ai_art field for filtering.
    #
    # Two-pass rejection:
    # 1. Service-side signals (reject_signals from JoyCaption service)
    # 2. Config-side keywords (re-classify caption text with current generator's config)
    joycaption = load_joycaption_results(captions_path)
    if joycaption:
        # Re-classify captions using THIS generator's REJECT_KEYWORDS
        # (JoyCaption service may be running with a different config)
        from validators.classify import classify_caption
        reclassified = 0
        for k, v in joycaption.items():
            caption_text = v.get("caption", "")
            if caption_text:
                local_result = classify_caption(caption_text, config)
                if local_result["should_reject"]:
                    # Merge: add local reject signals to existing ones
                    existing = set(v.get("reject_signals", []))
                    existing.update(local_result["reject_signals"])
                    v["reject_signals"] = list(existing)
                    v["should_reject"] = True
                    reclassified += 1

        rejected_content = {
            k: v for k, v in joycaption.items()
            if v.get("should_reject", False) or len(v.get("reject_signals", [])) > 0
        }
        print(f"Tier 0: JoyCaption content filter")
        print(f"  {len(joycaption)} tagged, "
              f"{len(rejected_content)} rejected by keywords"
              f" ({reclassified} caught by config keywords)")

        # Move content-rejected files immediately
        content_rejected = 0
        for filename, result in rejected_content.items():
            src = staging_dir / filename
            if src.exists():
                dest = rejected_dir / filename
                shutil.move(str(src), str(dest))
                content_rejected += 1
        if content_rejected > 0:
            print(f"  Moved {content_rejected} to rejected/")
        print()
    else:
        print("Tier 0: No JoyCaption results — skipping content filter")
        print("  (Run JoyCaption first or provide --joycaption-url)")
        print()

    # Tier 1: Structural validation (on remaining staging images)
    print("Tier 1: Structural validation...")
    structural = run_structural_validation(staging_dir, config)
    print(f"  {sum(1 for v in structural.values() if v.passed)}/{len(structural)} passed structural checks")

    # Tier 2: FSD detection
    fsd = {}
    if not skip_fsd:
        print("Tier 2: FSD detection...")
        fsd = run_fsd_detection(staging_dir, threshold=fsd_threshold)
        if fsd:
            fake_count = sum(1 for v in fsd.values() if v["is_fake"])
            print(f"  {fake_count}/{len(fsd)} detected as FAKE (AI-generated)")
        else:
            print("  FSD detection unavailable — skipping tier 2")
    else:
        print("Tier 2: FSD detection skipped")

    # Combine results and make decisions
    print("\nMaking final decisions...")
    results = []
    moved_to_images = 0
    moved_to_rejected = 0
    skipped_no_caption = 0

    for filename, sv in structural.items():
        filepath = staging_dir / filename
        if not filepath.exists():
            continue

        pr = PipelineResult(
            path=filepath,
            passed=False,
            structural=sv,
            structural_passed=sv.passed,
        )

        # Get FSD result
        if filename in fsd:
            pr.fsd_z_score = fsd[filename]["z_score"]
            pr.fsd_is_fake = fsd[filename]["is_fake"]

        # Get JoyCaption result
        if filename in joycaption:
            signals = joycaption[filename].get("reject_signals", [])
            pr.vlm_classification = ",".join(signals) if signals else "pass"

        # Decision logic
        rejection_reasons = []

        # MANDATORY: content filter (JoyCaption) must have been run on this image.
        # Images without captions stay in staging — never accepted without content check.
        if joycaption and filename not in joycaption:
            skipped_no_caption += 1
            continue  # leave in staging for next JoyCaption pass

        # Hard rejects (always fail regardless of mode)
        if any("too_few_pixels" in f for f in sv.flags):
            rejection_reasons.append("too_small")
        if any("too_many_pixels" in f for f in sv.flags):
            rejection_reasons.append("too_large")
        if sv.has_camera_exif:
            rejection_reasons.append("camera_exif")
        if any("non_native_aspect_ratio" in f for f in sv.flags):
            rejection_reasons.append("bad_aspect_ratio")

        # Soft rejects (only in strict mode)
        if not relaxed_mode:
            if any("high_compression" in f for f in sv.flags):
                rejection_reasons.append("high_compression")

        # FSD must confirm AI-generated (if available and not skipped)
        if fsd and filename in fsd:
            if not pr.fsd_is_fake:
                rejection_reasons.append(f"fsd_real:z={pr.fsd_z_score:.2f}")

        pr.rejection_reasons = rejection_reasons
        pr.passed = len(rejection_reasons) == 0

        # Move file
        if pr.passed:
            dest = images_dir / filename
            shutil.move(str(filepath), str(dest))
            pr.destination = "images"
            moved_to_images += 1
        else:
            dest = rejected_dir / filename
            shutil.move(str(filepath), str(dest))
            pr.destination = "rejected"
            moved_to_rejected += 1

        results.append(pr)

    # Summary
    print(f"\n{'='*60}")
    print("Pipeline Results")
    print(f"{'='*60}")
    print(f"Total processed:     {len(results)}")
    print(f"Moved to images/:    {moved_to_images}")
    print(f"Moved to rejected/:  {moved_to_rejected}")
    if skipped_no_caption > 0:
        print(f"Skipped (no caption): {skipped_no_caption}  ← still in staging/, needs JoyCaption")
    print()

    # Rejection reason breakdown
    reason_counts: dict[str, int] = {}
    for pr in results:
        for reason in pr.rejection_reasons:
            key = reason.split(":")[0]
            reason_counts[key] = reason_counts.get(key, 0) + 1

    if reason_counts:
        print("Rejection reasons:")
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}")

    # Save report
    report_path = data_dir / "validation_report.json"
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": moved_to_images,
        "rejected": moved_to_rejected,
        "fsd_threshold": fsd_threshold,
        "relaxed_mode": relaxed_mode,
        "rejection_reasons": reason_counts,
        "images": [
            {
                "filename": r.path.name,
                "passed": r.passed,
                "destination": r.destination,
                "structural_passed": r.structural_passed,
                "fsd_z_score": r.fsd_z_score,
                "fsd_is_fake": r.fsd_is_fake,
                "rejection_reasons": r.rejection_reasons,
                "width": r.structural.width if r.structural else 0,
                "height": r.structural.height if r.structural else 0,
            }
            for r in results
        ],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_path}")

    return results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run validation pipeline")
    parser.add_argument("--config", "-c", required=True, help="Generator config file (e.g. configs/grok.py)")
    parser.add_argument("--data-dir", "-d", default=None, help="Data directory (default: data/<generator>)")
    parser.add_argument("--relaxed", action="store_true",
                        help="Relaxed mode: accept re-compressed images if FSD confirms")
    parser.add_argument("--fsd-threshold", type=float, default=-2.0,
                        help="FSD z-score threshold (default: -2.0)")
    parser.add_argument("--captions", help="Path to JoyCaption results JSON")
    parser.add_argument("--skip-fsd", action="store_true", help="Skip FSD detection")
    parser.add_argument("--force", action="store_true",
                        help="Move images/rejected back to staging and revalidate from scratch")
    args = parser.parse_args()

    cfg = load_config(args.config)
    data_dir = Path(args.data_dir) if args.data_dir else Path(f"data/{cfg.NAME}")

    run_pipeline(
        config=cfg,
        data_dir=data_dir,
        relaxed_mode=args.relaxed,
        fsd_threshold=args.fsd_threshold,
        captions_path=Path(args.captions) if args.captions else None,
        skip_fsd=args.skip_fsd,
        force=args.force,
    )


if __name__ == "__main__":
    main()
