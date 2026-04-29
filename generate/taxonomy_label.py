"""Classify SALMONN captions into (content, motion) taxonomy labels.

Uses a local vLLM OpenAI-compatible server. Launch the server first:

    CUDA_VISIBLE_DEVICES=<id> VLLM_GPU_MEMORY_UTILIZATION=0.15 \\
      uv run python -m vllm.entrypoints.openai.api_server \\
        --model Qwen/Qwen3.5-9B \\
        --port 8100 \\
        --gpu-memory-utilization 0.15 \\
        --max-model-len 8192

Then:

    uv run python -m generate.taxonomy_label \\
        --captions data/videos/real/instagram/salmonn_captions_cleaned.json \\
        --out data/videos/real/instagram/taxonomy_labels.csv

The script is idempotent: it reads `out` on start, skips stems already
labeled, and appends new rows. Safe to ctrl-C and resume.
"""

from __future__ import annotations

import click
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

from openai import AsyncOpenAI, OpenAI

from generate.taxonomy import (
    CONTENT_IDS,
    MOTION_IDS,
    format_taxonomy_prompt,
    is_valid_content,
    is_valid_motion,
)

FIELDS = ["stem", "content", "motion", "confidence", "raw"]

DEFAULT_SERVER = "http://127.0.0.1:8100/v1"
DEFAULT_MODEL = "Qwen/Qwen3.5-9B"

BATCH_SIZE = 20  # captions per LLM call — balance context length vs round-trips

SYSTEM_PROMPT = f"""You classify video clips into a fixed taxonomy based on a text description of each clip.

{format_taxonomy_prompt()}

For each clip caption the user gives you, pick:
  - Exactly one CONTENT category id (C1..C21)
  - Exactly one MOTION type id (M1..M11)
  - A confidence score 0.0-1.0 for the overall assignment

Rules:
  - Pick the single BEST fit. If a clip could belong to two content categories, pick the one that matches the DOMINANT visual subject.
  - Motion is about how the CAMERA moves, not the subjects. A person running with a static camera is M1 (static/tripod), not M6 (fast action).
  - If the caption doesn't mention camera motion at all, default to M2 (handheld-stable) — that's the Instagram baseline.
  - If a caption mentions aerial/drone/above → lean C17 and M9.
  - If a caption mentions a person speaking directly to the camera in tight framing → C3 (talking head).
  - Cooking always wins over Hands & Objects if food/stove/kitchen is visible → C13, not C16.

OUTPUT FORMAT: one JSON object per clip, one per line, no extra text, no markdown fences. Schema:
  {{"idx": <int>, "content": "C?", "motion": "M?", "confidence": <float>}}

The user will give you a numbered list. Output exactly one JSON line per input number, in order."""


def load_captions(path: Path) -> dict[str, str]:
    data = json.load(open(path))
    out = {}
    for k, v in data.items():
        stem = Path(k).stem
        cap = v["caption"] if isinstance(v, dict) else v
        out[stem] = cap
    return out


def load_done(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    with open(out_path) as f:
        return {row["stem"] for row in csv.DictReader(f) if row.get("stem")}


def append_rows(out_path: Path, rows: list[dict]):
    write_header = not out_path.exists()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        w.writerows(rows)


def _build_user_msg(batch: list[tuple[str, str]]) -> str:
    lines = []
    for i, (_stem, caption) in enumerate(batch):
        cap = caption.replace("\n", " ").strip()
        if len(cap) > 900:
            cap = cap[:900] + "…"
        lines.append(f"{i}. {cap}")
    return "\n".join(lines)


def _parse_response(text: str, batch: list[tuple[str, str]]) -> list[dict]:
    """Convert raw LLM response text into label rows."""
    parsed_by_idx: dict[int, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        idx = obj.get("idx")
        if not isinstance(idx, int):
            continue
        parsed_by_idx[idx] = obj

    rows = []
    for i, (stem, _cap) in enumerate(batch):
        obj = parsed_by_idx.get(i, {})
        c = obj.get("content", "?")
        m = obj.get("motion", "?")
        conf = obj.get("confidence", 0.0)
        if not is_valid_content(c):
            c = "?"
        if not is_valid_motion(m):
            m = "?"
        try:
            conf = float(conf)
        except Exception:
            conf = 0.0
        rows.append(
            {"stem": stem, "content": c, "motion": m, "confidence": round(conf, 2),
             "raw": "" if (c != "?" and m != "?") else text[:500]}
        )
    return rows


async def classify_batch_async(
    client: AsyncOpenAI, model: str, batch: list[tuple[str, str]]
) -> list[dict]:
    user_msg = _build_user_msg(batch)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=120 * len(batch),
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return _parse_response(resp.choices[0].message.content or "", batch)


async def run_async(captions_path: Path, out: Path, server: str, model: str,
                    batch_size: int, concurrency: int, limit: int) -> None:
    captions = load_captions(captions_path)
    print(f"loaded {len(captions)} captions", flush=True)
    done = load_done(out)
    print(f"already labeled: {len(done)}", flush=True)
    todo = [(stem, cap) for stem, cap in sorted(captions.items()) if stem not in done]
    if limit:
        todo = todo[: limit]
    print(f"remaining: {len(todo)}", flush=True)
    if not todo:
        return

    # Split into batches up front
    batches = [todo[i : i + batch_size] for i in range(0, len(todo), batch_size)]
    print(f"batches: {len(batches)}  concurrency: {concurrency}", flush=True)

    client = AsyncOpenAI(base_url=server, api_key="none")
    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    stats = {"ok": 0, "partial": 0, "total": 0, "err": 0}
    t0 = time.time()

    async def process_one(batch_idx: int, batch: list[tuple[str, str]]) -> None:
        async with sem:
            try:
                rows = await classify_batch_async(client, model, batch)
            except Exception as e:
                stats["err"] += 1
                print(f"  batch {batch_idx} error: {type(e).__name__}: {str(e)[:200]}", flush=True)
                return
        async with write_lock:
            append_rows(out, rows)
            for r in rows:
                stats["total"] += 1
                if r["content"] != "?" and r["motion"] != "?":
                    stats["ok"] += 1
                else:
                    stats["partial"] += 1
            if stats["total"] % (batch_size * 5) == 0 or stats["total"] == len(todo):
                elapsed = time.time() - t0
                rate = stats["total"] / max(elapsed, 1e-3)
                eta = (len(todo) - stats["total"]) / max(rate, 1e-3)
                print(
                    f"  [{stats['total']}/{len(todo)}] ok={stats['ok']} partial={stats['partial']} "
                    f"err={stats['err']}  {rate:.1f} cap/s  eta={eta/60:.1f}m",
                    flush=True,
                )

    await asyncio.gather(*(process_one(i, b) for i, b in enumerate(batches)))

    elapsed = time.time() - t0
    print(
        f"\ndone. labeled {stats['total']} clips "
        f"({stats['ok']} clean, {stats['partial']} partial, {stats['err']} errored) "
        f"in {elapsed:.1f}s"
    )


@click.command()
@click.option("--captions", type=click.Path(path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), required=True)
@click.option("--server", default=DEFAULT_SERVER)
@click.option("--model", default=DEFAULT_MODEL)
@click.option("--batch-size", type=int, default=BATCH_SIZE)
@click.option("--concurrency", type=int, default=8,
              help="number of batches in flight to vLLM at once")
@click.option("--limit", type=int, default=0,
              help="stop after this many new clips (0=all)")
def main(captions: Path, out: Path, server: str, model: str,
         batch_size: int, concurrency: int, limit: int):
    asyncio.run(run_async(captions, out, server, model, batch_size, concurrency, limit))


if __name__ == "__main__":
    main()
