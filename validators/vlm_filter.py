"""VLM-based image classification filter using vLLM.

Uses a vision-language model (e.g. Qwen2.5-VL-7B-Instruct) served via vLLM
to classify images. Expects an OpenAI-compatible API at the given URL.

Usage:
    uv run python -m validators.vlm_filter --config configs/grok.py --dir data/grok/staging
    uv run python -m validators.vlm_filter --config configs/grok.py --image data/grok/images/foo.jpg
"""

import base64
import json
import re
import time
from pathlib import Path

import click
import requests

DEFAULT_API_URL = "http://localhost:8001/v1"
DEFAULT_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"

CLASSIFY_PROMPT = """\
Analyze this image and classify it into exactly one category.

Categories:
- AI_ART: A genuine AI-generated image (artwork, portrait, landscape, etc.)
- SCREENSHOT: A screenshot of an app, website, chat, or UI
- MEME: A meme, joke image, or image with overlaid text
- COLLAGE: Multiple images stitched together or side-by-side comparison
- PHOTO: A real photograph (not AI-generated)
- OTHER: None of the above

Respond using this exact XML format:
<classification>
  <category>CATEGORY_HERE</category>
  <is_ai_art>true or false</is_ai_art>
  <reason>Brief explanation in one sentence</reason>
</classification>"""


def _parse_xml_response(content: str) -> dict:
    """Parse XML classification response from VLM."""
    result = {"category": "UNKNOWN", "is_ai_art": True, "reason": ""}

    if not content:
        result["reason"] = "Empty response"
        return result

    m = re.search(r"<category>\s*(.*?)\s*</category>", content, re.IGNORECASE)
    if m:
        result["category"] = m.group(1).upper().strip()

    m = re.search(r"<is_ai_art>\s*(.*?)\s*</is_ai_art>", content, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        result["is_ai_art"] = val in ("true", "yes", "1")

    m = re.search(r"<reason>\s*(.*?)\s*</reason>", content, re.IGNORECASE | re.DOTALL)
    if m:
        result["reason"] = m.group(1).strip()

    return result


def _get_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")


def classify_image(
    image_path: Path,
    api_url: str = DEFAULT_API_URL,
    model: str = DEFAULT_MODEL,
    prompt: str = CLASSIFY_PROMPT,
    max_tokens: int = 1024,
) -> dict:
    """Classify a single image via vLLM vision API.

    Returns dict with: category, is_ai_art, reason, raw_response.
    """
    try:
        img_b64 = base64.b64encode(image_path.read_bytes()).decode()
        mime = _get_mime(image_path)

        resp = requests.post(
            f"{api_url}/chat/completions",
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        result = _parse_xml_response(raw)
        result["raw_response"] = raw[:500]
        return result

    except Exception as e:
        return {
            "category": "ERROR",
            "is_ai_art": True,  # keep on error — don't lose good images
            "reason": str(e)[:200],
            "raw_response": "",
        }


def batch_classify(
    image_dir: Path,
    api_url: str = DEFAULT_API_URL,
    model: str = DEFAULT_MODEL,
    delay: float = 0.2,
) -> dict[str, dict]:
    """Classify all images in a directory."""
    suffixes = (".jpg", ".jpeg", ".png")
    files = sorted(f for f in image_dir.iterdir() if f.suffix.lower() in suffixes)
    results = {}
    ai_count = 0
    start = time.time()

    for i, f in enumerate(files):
        if i > 0 and delay > 0:
            time.sleep(delay)

        result = classify_image(f, api_url, model)
        results[f.name] = result
        if result["is_ai_art"]:
            ai_count += 1

        if (i + 1) % 10 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            print(f"  [{i+1}/{len(files)}] {ai_count} AI art, "
                  f"{i+1-ai_count} other ({rate:.1f} img/s)")

    elapsed = time.time() - start
    print(f"Done: {ai_count}/{len(files)} AI art ({elapsed:.0f}s)")
    return results


@click.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True), help="Generator config file")
@click.option("--dir", "image_dir", default=None, type=click.Path(exists=True), help="Image directory to classify")
@click.option("--image", default=None, type=click.Path(exists=True), help="Single image to classify")
@click.option("--output", "-o", type=click.Path(), help="Output JSON path")
@click.option("--url", default=DEFAULT_API_URL, help="vLLM API URL")
@click.option("--model", "-m", default=DEFAULT_MODEL, help="Model name")
@click.option("--delay", type=float, default=0.2, help="Delay between requests (seconds)")
def main(config, image_dir, image, output, url, model, delay):
    """Classify images using a vision-language model via vLLM."""
    from configs import load_config
    cfg = load_config(config)

    if image:
        result = classify_image(Path(image), api_url=url, model=model)
        print(json.dumps(result, indent=2))
    elif image_dir:
        results = batch_classify(Path(image_dir), api_url=url, model=model, delay=delay)
        if output:
            with open(output, "w") as f:
                json.dump(results, f, indent=2)
            print(f"Saved to {output}")
    else:
        raise click.UsageError("Provide --dir or --image")


if __name__ == "__main__":
    main()
