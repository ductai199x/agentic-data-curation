"""One-time credit calibration: 1 clip per provider, measure exact cost.

Runs sequentially. For each provider:
  1. Query balance via GET /customers/balance
  2. Generate 1 clip
  3. Query balance again
  4. Store delta as the true per-clip credit cost

Saves to `data/credit_rates.json`. Use these rates in batch configs.

Usage:
    PYTHONPATH=/home/tai/1-workdir/09-agent-data-curation \\
      COMFY_PORT=8190 \\
      python -m video_gen.calibrate_credits
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from video_gen.comfy_batch_run import (
    SubmitResult,
    get_credit_balance,
    load_api_key,
    submit_and_wait,
    wait_for_comfy,
)
from video_gen.comfy_config import load_config

PROVIDERS = [
    # Estimates updated with calibrated rates (2026-04-16)
    ("configs.generate.luma_ray2_instagram_pilot", "luma_ray2", 1.01),
    ("configs.generate.runway_gen4_instagram_pilot", "runway_gen4", 0.36),
    ("configs.generate.veo3_instagram_pilot", "veo3", 1.60),
    ("configs.generate.sora2_instagram_pilot", "sora2", 0.80),
    ("configs.generate.kling2_instagram_pilot", "kling2", 0.35),
    ("configs.generate.hailuo02_instagram_pilot", "hailuo02", 0.28),
]

OUT_FILE = REPO_ROOT / "data" / "credit_rates.json"


def main():
    port = int(os.environ.get("COMFY_PORT", "8190"))
    server = f"http://127.0.0.1:{port}"

    session = requests.Session()
    if not wait_for_comfy(session, server):
        print("comfy not ready")
        sys.exit(1)

    cfg0 = load_config(PROVIDERS[0][0])
    api_key = load_api_key(cfg0)
    if not api_key:
        print("no API key")
        sys.exit(1)

    # Verify balance API works
    bal = get_credit_balance(api_key)
    if bal < 0:
        print("balance API failed")
        sys.exit(1)
    print(f"starting balance: {bal:.2f} credits (${bal/211:.2f})")

    # Load existing calibration
    rates = {}
    if OUT_FILE.exists():
        rates = json.loads(OUT_FILE.read_text())

    comfy_input = cfg0.comfy_root / "input"
    comfy_input.mkdir(exist_ok=True)

    # Use rank-1 clip directly — no ffprobe scan needed
    import csv
    rank_file = cfg0.rank_file or (REPO_ROOT / "data/videos/real/instagram/diversity_rank.csv")
    with open(rank_file) as f:
        row = next(csv.DictReader(f))  # rank 1
    base_stem = row["stem"]

    caps = json.loads(cfg0.captions_path.read_text())
    cap_entry = caps.get(f"{base_stem}.mp4", {})
    short_caption = cap_entry.get("short_caption", "") if isinstance(cap_entry, dict) else str(cap_entry)
    full_caption = cap_entry.get("caption", short_caption) if isinstance(cap_entry, dict) else str(cap_entry)

    # Copy frames once
    frames_dir = cfg0.frames_dir
    first_name = f"{base_stem}_first.png"
    last_name = f"{base_stem}_last.png"
    for name in [first_name, last_name]:
        src = frames_dir / name
        dst = comfy_input / name
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)

    print(f"calibration clip: {base_stem}", flush=True)
    print(f"short: {short_caption[:100]}", flush=True)
    print(f"full:  {full_caption[:100]}", flush=True)

    for config_module, tag, est_usd in PROVIDERS:
        if tag in rates:
            r = rates[tag]
            print(f"\n[{tag}] already calibrated: {r['actual_credits']:.2f} credits = ${r['actual_usd']:.4f} (ratio={r['ratio']:.2f}x) — skip")
            continue

        cfg = load_config(config_module)
        mod = importlib.import_module(cfg.workflow_module)

        prompt_text = (short_caption if cfg.prompt_source == "short_caption" else full_caption)[:cfg.prompt_max_chars]

        print(f"\n{'='*60}")
        print(f"[{tag}] clip={base_stem}  est=${est_usd:.3f}  prompt_source={cfg.prompt_source}")

        # Balance BEFORE
        before = get_credit_balance(api_key)
        if before < 0:
            print(f"[{tag}] balance query failed, skipping")
            continue
        print(f"[{tag}] balance before: {before:.2f} credits")

        # Generate
        wf = mod.build_workflow(
            cfg=cfg,
            first_frame_name=first_name,
            last_frame_name=last_name if (comfy_input / last_name).exists() else None,
            prompt_text=prompt_text,
            filename_prefix=f"calibrate_{tag}_{base_stem}",
        )
        t0 = time.time()
        result = submit_and_wait(
            session, server, wf,
            timeout_s=cfg.submit_timeout_s,
            api_key=api_key,
            comfy_output_dir=cfg.comfy_root / "output",
        )
        elapsed = time.time() - t0

        # Balance AFTER — poll until it changes (comfy.org has async settlement)
        after = before
        for wait_attempt in range(60):  # up to 2 min
            time.sleep(2)
            after = get_credit_balance(api_key)
            if after < 0:
                print(f"[{tag}] balance query failed on attempt {wait_attempt+1}")
                continue
            if abs(after - before) > 0.01:  # balance changed
                print(f"[{tag}] balance settled after {(wait_attempt+1)*2}s")
                break
        else:
            print(f"[{tag}] balance never changed after 120s — NOT saving")
            continue

        actual_credits = round(before - after, 2)
        if actual_credits <= 0:
            print(f"[{tag}] balance went up or unchanged ({before:.2f} -> {after:.2f}) — NOT saving")
            continue
        actual_usd = actual_credits / 211.0
        ratio = actual_usd / est_usd if est_usd > 0 else 0
        status = "generated" if result.output_path else "failed"

        if status == "failed" and actual_credits == 0:
            print(f"[{tag}] failed and no credits charged — NOT saving (retry later)")
            continue

        rates[tag] = {
            "actual_credits": actual_credits,
            "actual_usd": round(actual_usd, 4),
            "estimated_usd": est_usd,
            "ratio": round(ratio, 3),
            "status": status,
            "elapsed_s": round(elapsed, 1),
            "clip_stem": base_stem,
            "error": result.error[:200] if result.error else "",
        }

        # Save after each (crash-safe)
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(json.dumps(rates, indent=2))

        flag = "✓" if abs(ratio - 1.0) <= 0.15 else "⚠️"
        print(f"[{tag}] {status} in {elapsed:.0f}s")
        print(f"[{tag}] ACTUAL: {actual_credits:.2f} credits = ${actual_usd:.4f}")
        print(f"[{tag}] ESTIMATED: ${est_usd:.3f}")
        print(f"[{tag}] RATIO: {ratio:.2f}x {flag}")

    print(f"\n{'='*60}")
    print("CALIBRATION RESULTS")
    print(f"{'='*60}")
    for tag, r in rates.items():
        flag = "✓" if abs(r['ratio'] - 1.0) <= 0.15 else "⚠️"
        print(f"  {tag:15s}  {r['actual_credits']:7.1f} cr  ${r['actual_usd']:.4f}  ratio={r['ratio']:.2f}x {flag}")
    print(f"\nsaved to {OUT_FILE}")


if __name__ == "__main__":
    main()
