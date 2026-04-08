"""Validate and fix channel IDs in approved channel lists.

For each channel ID, checks if it's valid by listing videos.
If invalid, attempts to resolve the correct ID by searching for the channel name.
Rewrites the source files with corrected IDs. Logs all fixes to a report file.

Usage:
    PYTHONUNBUFFERED=1 uv run python -m video.validate_channels --dir configs/video_sources/_approved
"""

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from tqdm import tqdm

from video.rate_limiter import run_ytdlp


def validate_channel_id(channel_id: str) -> bool:
    """Check if a channel ID is valid by listing 1 video."""
    try:
        result = run_ytdlp([
            "--flat-playlist", "--print", "%(id)s",
            "--playlist-end", "1",
            f"https://www.youtube.com/channel/{channel_id}/videos",
        ], timeout=15)
        return result.returncode == 0 and result.stdout.strip() != ""
    except Exception:
        return False


def resolve_channel_id(channel_name: str) -> str | None:
    """Try to find the correct channel ID by searching for the channel name."""
    try:
        result = run_ytdlp([
            "--flat-playlist", "--print", "%(channel_id)s",
            "--playlist-end", "1",
            f"ytsearch1:{channel_name}",
        ], timeout=15)
        resolved = result.stdout.strip().split("\n")[0].strip()
        if resolved and resolved != "NA":
            return resolved
    except Exception:
        pass
    return None


def validate_and_fix(channel_id: str, channel_name: str) -> dict:
    """Validate a channel ID and fix if broken."""
    if validate_channel_id(channel_id):
        return {"channel_id": channel_id, "status": "valid"}

    resolved = resolve_channel_id(channel_name)
    if resolved and resolved != channel_id:
        if validate_channel_id(resolved):
            return {
                "channel_id": resolved,
                "status": "fixed",
                "original_id": channel_id,
            }

    return {"channel_id": channel_id, "status": "broken"}


def validate_file(
    filepath: Path,
    max_workers: int = 4,
    report: list | None = None,
) -> dict:
    """Validate all channel IDs in a file and rewrite with corrections."""
    header_lines = []
    channels = []
    with open(filepath) as f:
        for line in f:
            if line.startswith("#") or line.strip() == "":
                header_lines.append(line)
            else:
                parts = line.strip().split("\t", 1)
                if len(parts) >= 2:
                    channels.append((parts[0], parts[1]))

    if not channels:
        return {"valid": 0, "fixed": 0, "broken": 0, "total": 0}

    valid = 0
    fixed = 0
    broken = 0
    corrected_channels = []

    pbar = tqdm(total=len(channels), desc=f"  {filepath.stem}", unit="ch")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for cid, rest in channels:
            name = rest.split("\t")[0]
            futures[executor.submit(validate_and_fix, cid, name)] = (cid, rest)

        for future in as_completed(futures):
            cid, rest = futures[future]
            name = rest.split("\t")[0]
            try:
                result = future.result(timeout=30)
            except Exception:
                broken += 1
                corrected_channels.append((cid, rest))
                pbar.update(1)
                continue

            time.sleep(0.3)

            if result["status"] == "valid":
                valid += 1
                corrected_channels.append((cid, rest))
            elif result["status"] == "fixed":
                fixed += 1
                new_id = result["channel_id"]
                corrected_channels.append((new_id, rest))
                tqdm.write(f"    FIXED: {name} ({cid} -> {new_id})")
                if report is not None:
                    report.append({
                        "file": filepath.name,
                        "channel_name": name,
                        "old_id": cid,
                        "new_id": new_id,
                    })
            else:
                broken += 1
                corrected_channels.append((cid, rest))
                tqdm.write(f"    BROKEN: {name} ({cid})")
                if report is not None:
                    report.append({
                        "file": filepath.name,
                        "channel_name": name,
                        "old_id": cid,
                        "new_id": None,
                    })

            pbar.update(1)

    pbar.close()

    # Rewrite file with corrections
    with open(filepath, "w") as f:
        for line in header_lines:
            f.write(line)
        for cid, rest in corrected_channels:
            f.write(f"{cid}\t{rest}\n")

    return {"valid": valid, "fixed": fixed, "broken": broken, "total": len(channels)}


def main():
    parser = argparse.ArgumentParser(description="Validate and fix channel IDs")
    parser.add_argument("--dir", required=True, help="Directory with channel list files")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--report", default="/tmp/channel_validation_report.json",
                        help="Path to save JSON report of fixes")
    args = parser.parse_args()

    source_dir = Path(args.dir)
    total_valid = 0
    total_fixed = 0
    total_broken = 0
    total_channels = 0
    report = []

    for filepath in sorted(source_dir.glob("C*.txt")):
        print(f"\n{filepath.name}")
        stats = validate_file(filepath, max_workers=args.workers, report=report)
        total_valid += stats["valid"]
        total_fixed += stats["fixed"]
        total_broken += stats["broken"]
        total_channels += stats["total"]
        print(f"  {stats['valid']} valid, {stats['fixed']} fixed, {stats['broken']} broken")

    print(f"\n{'='*60}")
    print(f"TOTAL: {total_channels} channels")
    print(f"  Valid:  {total_valid} ({total_valid/total_channels*100:.1f}%)")
    print(f"  Fixed:  {total_fixed} ({total_fixed/total_channels*100:.1f}%)")
    print(f"  Broken: {total_broken} ({total_broken/total_channels*100:.1f}%)")
    print(f"{'='*60}")

    # Save report
    report_path = Path(args.report)
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total": total_channels,
            "valid": total_valid,
            "fixed": total_fixed,
            "broken": total_broken,
            "changes": report,
        }, f, indent=2)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
