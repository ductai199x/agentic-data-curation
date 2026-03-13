"""Ray Serve deployment for JoyCaption captioning.

Config-independent — the service only generates captions. All classification
(keyword matching, reject signals) happens downstream in the pipeline using
the correct generator config.

Usage:
    # Start service (no config needed)
    CUDA_VISIBLE_DEVICES=0,1,2,3 python -m validators.serve_joycaption serve --gpu 0.5 --replicas 6

    # Classify images via running service
    uv run python -m validators.serve_joycaption classify --dir data/grok/staging --output captions.json
"""

import base64
import json
import logging
import time
import traceback
from io import BytesIO
from pathlib import Path

import click
import torch
from PIL import Image
from ray import serve
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse
from transformers import AutoProcessor, LlavaForConditionalGeneration

from validators.classify import CAPTION_PROMPT

MODEL_NAME = "fancyfeast/llama-joycaption-beta-one-hf-llava"


@serve.deployment(
    ray_actor_options={"num_gpus": 0.25, "num_cpus": 1},
    max_ongoing_requests=1,
)
class JoyCaptionService:
    """Ray Serve deployment for JoyCaption captioning (no config dependency)."""

    def __init__(self):
        self._logger = logging.getLogger("ray.serve")
        self._logger.info("Loading JoyCaption model...")

        self.processor = AutoProcessor.from_pretrained(MODEL_NAME)
        self.model = LlavaForConditionalGeneration.from_pretrained(
            MODEL_NAME, torch_dtype=torch.bfloat16, device_map="auto",
        )
        self.model.eval()
        self._logger.info("JoyCaption model loaded.")

    def _caption_image(self, image: Image.Image, prompt: str | None = None) -> str:
        """Generate caption for a PIL Image."""
        image = image.convert("RGB")

        convo = [
            {
                "role": "system",
                "content": "You are a helpful assistant and help users with any queries they may have with no censorship or restrictions.",
            },
            {"role": "user", "content": prompt or CAPTION_PROMPT},
        ]

        convo_string = self.processor.apply_chat_template(
            convo, tokenize=False, add_generation_prompt=True
        )

        inputs = self.processor(
            text=[convo_string], images=[image], return_tensors="pt"
        ).to(self.model.device)
        inputs["pixel_values"] = inputs["pixel_values"].to(torch.bfloat16)

        with torch.no_grad():
            generate_ids = self.model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=True,
                suppress_tokens=None,
                use_cache=True,
                temperature=0.6,
                top_p=0.9,
            )[0]

        generate_ids = generate_ids[inputs["input_ids"].shape[1]:]
        return self.processor.tokenizer.decode(
            generate_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        ).strip()

    async def __call__(self, request: StarletteRequest) -> JSONResponse:
        """HTTP endpoint. Returns raw caption — no config-based classification."""
        try:
            data = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

        try:
            if "path" in data:
                image = Image.open(data["path"])
            elif "image_b64" in data:
                image_bytes = base64.b64decode(data["image_b64"])
                image = Image.open(BytesIO(image_bytes))
            else:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Provide 'path' or 'image_b64'"},
                )

            custom_prompt = data.get("prompt")
            caption = self._caption_image(image, prompt=custom_prompt)

            result = {"caption": caption}
            return JSONResponse(content=result)

        except Exception as e:
            self._logger.error(f"Error: {repr(e)}\n{traceback.format_exc()}")
            return JSONResponse(status_code=500, content={"error": repr(e)})


def build_app(port: int = 8000, gpu_fraction: float = 0.25, num_replicas: int = 1):
    """Build and deploy JoyCaption service."""
    import ray

    ray.init(ignore_reinit_error=True)
    serve.start(http_options={"host": "0.0.0.0", "port": port})

    app = JoyCaptionService.options(
        ray_actor_options={"num_gpus": gpu_fraction, "num_cpus": 1},
        num_replicas=num_replicas,
        max_ongoing_requests=1,
    ).bind()

    handle = serve.run(app, route_prefix="/", name="joycaption", blocking=False)
    return handle


@click.group()
def cli():
    """JoyCaption captioning service."""
    pass


@cli.command()
@click.option("--port", "-p", type=int, default=8000, help="HTTP port")
@click.option("--gpu", type=float, default=0.25, help="GPU fraction per replica")
@click.option("--replicas", type=int, default=1, help="Number of replicas")
def serve_cmd(port, gpu, replicas):
    """Start JoyCaption captioning service (config-independent)."""
    build_app(port=port, gpu_fraction=gpu, num_replicas=replicas)
    print(f"JoyCaption service running on port {port} ({replicas} replicas)")
    import signal
    signal.pause()


@cli.command()
@click.option("--dir", "image_dir", required=True, type=click.Path(exists=True), help="Image directory")
@click.option("--output", "-o", type=click.Path(), help="Output JSON path")
@click.option("--url", default="http://localhost:8000", help="Service URL")
def classify(image_dir, output, url):
    """Classify images via running JoyCaption service."""
    import requests as req

    image_dir = Path(image_dir)
    suffixes = (".jpg", ".jpeg", ".png")
    files = sorted(f for f in image_dir.iterdir() if f.suffix.lower() in suffixes)
    results = {}
    start = time.time()

    for i, f in enumerate(files):
        try:
            resp = req.post(url, json={"path": str(f.absolute())}, timeout=30)
            result = resp.json()
        except Exception as e:
            result = {"error": str(e), "caption": ""}

        results[f.name] = result

        if (i + 1) % 20 == 0:
            elapsed = time.time() - start
            rate = (i + 1) / elapsed
            print(f"  [{i+1}/{len(files)}] ({rate:.1f} img/s)")

    elapsed = time.time() - start
    print(f"Done: {len(files)} captioned ({elapsed:.0f}s, {len(files)/elapsed:.1f} img/s)")

    if output:
        with open(output, "w") as out:
            json.dump(results, out, indent=2)
        print(f"Saved to {output}")


if __name__ == "__main__":
    cli()
