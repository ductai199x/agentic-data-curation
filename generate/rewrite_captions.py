"""Add a `short_caption` field next to each long SALMONN caption.

SALMONN writes verbose third-person paragraph descriptions (1-3 KB). Commercial
video generators (Luma, Runway, Veo, Sora, etc.) want short direct prompts and
reject long narrative text. This script calls a local LLM (vLLM OpenAI server)
to rewrite each caption into a short direct prompt, then writes the JSON back
with the NEW field added — the original `caption` stays untouched.

Idempotent: rows that already have a non-empty `short_caption` are skipped.
Safe to ctrl-C and resume. Writes atomically via .tmp + rename.

Usage:
    # start vLLM first (see generate/taxonomy_label.py docstring)
    uv run python -m generate.rewrite_captions \\
        --captions data/videos/real/instagram/salmonn_captions_cleaned.json \\
        --concurrency 8
"""

from __future__ import annotations

import click
import asyncio
import json
import os
import time
from pathlib import Path

from openai import AsyncOpenAI


SYSTEM_PROMPT = """You rewrite long third-person video descriptions into short direct prompts for an image-to-video generation model.

RULES:
- Output ONE short prompt, max 150 characters.
- Plain text only. No quotes, no JSON, no markdown, no prefix like "Prompt:" or "Short caption:".
- Start with the main visual subject + key attributes, then brief action/motion.
- NO "The video...", "The scene shows...", "In the clip..." — just describe the subject directly.
- Keep the distinctive visual details (colors, setting, objects) that matter most.
- Be concrete. Action verbs over abstract nouns.
- If the original mentions any text overlay, watermark, subtitles, or logos — DO NOT include them in your rewrite. Describe only the underlying video.

EXAMPLES:
Input: "The video takes place in a cozy indoor setting, likely a café or restaurant, characterized by dim lighting, dark walls, and hanging pendant lights. A group of people is seated in a semi-circle, each holding a violin, suggesting they are part of a small orchestra or music group."
Output: cozy dim-lit cafe with warm hanging pendant lights, small orchestra of musicians holding violins seated in a semi-circle

Input: "The video opens with a serene scene featuring two red heart-shaped balloons floating against a backdrop of white fabric. The water is clear with rose petals scattered around."
Output: two red heart-shaped balloons drifting over clear water with scattered red rose petals, white fabric backdrop

Now rewrite the user's caption. Output ONLY the rewritten prompt."""


async def rewrite_one(client: AsyncOpenAI, model: str, caption: str) -> str:
    cap = caption.replace("\n", " ").strip()
    if len(cap) > 2500:
        cap = cap[:2500] + "…"
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": cap},
        ],
        temperature=0.2,
        max_tokens=120,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    text = (resp.choices[0].message.content or "").strip()
    # Guard: strip quotes, fences, lingering "Prompt:" etc
    for bad in ['"', "'", "`"]:
        text = text.strip(bad)
    for prefix in ("prompt:", "short caption:", "output:", "rewrite:"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):].strip()
    # Hard cap at 180 chars — be lenient past 150 but never unbounded
    if len(text) > 180:
        text = text[:180].rsplit(" ", 1)[0]
    return text


def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


async def run_async(captions: Path, server: str, model: str, concurrency: int, limit: int):
    captions_path = captions
    print(f"loading {captions_path}", flush=True)
    data = json.loads(captions_path.read_text())
    print(f"  {len(data)} entries", flush=True)

    # Normalize: bare string → {"caption": s}
    for k, v in list(data.items()):
        if isinstance(v, str):
            data[k] = {"caption": v}

    todo = [
        (fn, v["caption"]) for fn, v in data.items()
        if v.get("caption") and not v.get("short_caption")
    ]
    if limit:
        todo = todo[: limit]
    print(f"  need short_caption: {len(todo)}", flush=True)
    if not todo:
        print("nothing to do")
        return

    client = AsyncOpenAI(base_url=server, api_key="none")
    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    written_every = max(50, len(todo) // 40)

    stats = {"ok": 0, "err": 0, "total": 0}
    t0 = time.time()

    async def process_one(fn: str, cap: str) -> None:
        async with sem:
            try:
                short = await rewrite_one(client, model, cap)
            except Exception as e:
                stats["err"] += 1
                print(f"  {fn}: {type(e).__name__}: {str(e)[:200]}", flush=True)
                return
        async with write_lock:
            data[fn]["short_caption"] = short
            stats["ok"] += 1
            stats["total"] += 1
            if stats["total"] % written_every == 0:
                atomic_write_json(captions_path, data)
                elapsed = time.time() - t0
                rate = stats["total"] / max(elapsed, 1e-3)
                eta = (len(todo) - stats["total"]) / max(rate, 1e-3)
                print(
                    f"  [{stats['total']}/{len(todo)}] ok={stats['ok']} err={stats['err']}  "
                    f"{rate:.1f} cap/s  eta={eta/60:.1f}m",
                    flush=True,
                )

    await asyncio.gather(*(process_one(fn, cap) for fn, cap in todo))

    atomic_write_json(captions_path, data)
    elapsed = time.time() - t0
    print(
        f"\ndone. {stats['ok']} rewrites, {stats['err']} errors in {elapsed:.1f}s "
        f"(final: {stats['total']} new short_captions)"
    )


@click.command()
@click.option("--captions", type=click.Path(path_type=Path), required=True)
@click.option("--server", default="http://127.0.0.1:8100/v1")
@click.option("--model", default="Qwen/Qwen3.5-9B")
@click.option("--concurrency", type=int, default=8)
@click.option("--limit", type=int, default=0)
def main(captions: Path, server: str, model: str, concurrency: int, limit: int):
    asyncio.run(run_async(captions, server, model, concurrency, limit))


if __name__ == "__main__":
    main()
