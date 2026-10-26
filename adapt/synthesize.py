"""Open-weights collection: generate samples locally from the released checkpoint.

Backends:
- diffusers: the real path. DiffusionPipeline.from_pretrained(HF_REPO) resolves the right pipeline class from the
  repo's model_index.json, so a new model usually needs only a profile, not code. Gated repos read HF_TOKEN.
- procedural: dry-run stand-in that draws deterministic synthetic images/clips with PIL (no GPU, no download).
  Its outputs are labeled backend=procedural and must never be trained on.
Resumable: each (prompt index, seed) is a sample_key; already-generated keys are skipped.
"""

import io
import os
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from tqdm import tqdm

from adapt.prompts import make_prompts
from adapt.store import SampleStore


class ProceduralBackend:
    name = "procedural"

    def __init__(self, profile, style: str = "fake"):
        self.profile, self.style = profile, style

    def _image(self, prompt: dict, width: int, height: int) -> Image.Image:
        rng = random.Random(prompt["seed"])
        base = tuple(rng.randrange(256) for _ in range(3))
        img = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(img)
        for _ in range(rng.randint(8, 30)):  # random shapes so phash differs per sample
            x0, y0 = rng.randrange(width), rng.randrange(height)
            box = (x0, y0, min(width, x0 + rng.randrange(40, width // 2)), min(height, y0 + rng.randrange(40, height // 2)))
            color = tuple(rng.randrange(256) for _ in range(3))
            (draw.ellipse if rng.random() < 0.5 else draw.rectangle)(box, fill=color)
        if self.style == "real":  # crude camera-like stand-in: blur + sensor noise
            img = img.filter(ImageFilter.GaussianBlur(1.2))
            noise = Image.effect_noise((width, height), 18).convert("RGB")
            img = Image.blend(img, noise, 0.12)
        return img

    def image(self, prompt: dict, width: int, height: int) -> tuple[bytes, str]:
        buffer = io.BytesIO(); self._image(prompt, width, height).save(buffer, "PNG")
        return buffer.getvalue(), ".png"

    def video(self, prompt: dict, width: int, height: int, num_frames: int, fps: int) -> tuple[bytes, str]:
        num_frames = min(num_frames, 24)  # dry runs only need a short clip
        first = self._image(prompt, width, height)
        frames = [first.transform(first.size, Image.AFFINE, (1, 0, i * 2, 0, 1, i), fillcolor=(0, 0, 0)) for i in range(num_frames)]
        return frames_to_mp4(frames, fps), ".mp4"


class DiffusersBackend:
    name = "diffusers"

    def __init__(self, profile):
        import torch
        from diffusers import DiffusionPipeline
        assert profile.HF_REPO, f"profile {profile.NAME} has no HF_REPO"
        self.torch, self.profile = torch, profile
        self.device = os.environ.get("ADAPT_DEVICE", "cuda")
        self.pipe = DiffusionPipeline.from_pretrained(
            profile.HF_REPO, revision=profile.HF_REVISION, torch_dtype=getattr(torch, profile.TORCH_DTYPE),
            token=os.environ.get("HF_TOKEN"))
        if os.environ.get("ADAPT_CPU_OFFLOAD"): self.pipe.enable_model_cpu_offload()
        else: self.pipe.to(self.device)

    def _generator(self, seed: int):
        return self.torch.Generator(device="cpu" if os.environ.get("ADAPT_CPU_OFFLOAD") else self.device).manual_seed(seed)

    def image(self, prompt: dict, width: int, height: int) -> tuple[bytes, str]:
        out = self.pipe(prompt=prompt["prompt"], width=width, height=height, generator=self._generator(prompt["seed"]),
                        **self.profile.GENERATION_KWARGS)
        buffer = io.BytesIO(); out.images[0].save(buffer, "PNG")  # PNG: keep the generator's own pixels
        return buffer.getvalue(), ".png"

    def video(self, prompt: dict, width: int, height: int, num_frames: int, fps: int) -> tuple[bytes, str]:
        out = self.pipe(prompt=prompt["prompt"], width=width, height=height, num_frames=num_frames,
                        generator=self._generator(prompt["seed"]), **self.profile.GENERATION_KWARGS)
        frames = [f if isinstance(f, Image.Image) else Image.fromarray((f * 255).clip(0, 255).astype("uint8")) for f in out.frames[0]]
        return frames_to_mp4(frames, fps), ".mp4"


def frames_to_mp4(frames: list[Image.Image], fps: int) -> bytes:
    # near-lossless H.264 (crf 10) so the clip is close to the generator's frames before the processing ladder
    with tempfile.TemporaryDirectory() as tmp:
        for i, frame in enumerate(frames): frame.save(Path(tmp) / f"{i:05d}.png")
        out = Path(tmp) / "out.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", f"{tmp}/%05d.png",
                        "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", str(out)], check=True)
        return out.read_bytes()


def make_backend(profile, backend: str):
    return ProceduralBackend(profile) if backend == "procedural" else DiffusersBackend(profile)


def generate_samples(profile, store: SampleStore, run_id: str, n: int, backend: str = "diffusers",
                     resolution_scale: float = 1.0, on_first_sample=None) -> int:
    prompts = make_prompts(n, seed=f"{run_id}:{profile.NAME}", mix=profile.PROMPT_MIX)
    todo = [p for p in prompts if not store.has_key(f"gen:{p['index']}:{p['seed']}")]
    if not todo: return 0
    engine = make_backend(profile, backend)
    rng, made = random.Random(run_id), 0
    resolutions = [rng.choice(profile.RESOLUTIONS) for _ in prompts]
    for p in tqdm(todo, desc=f"Generating ({engine.name})", unit="sample"):
        width, height = (max(16, int(d * resolution_scale) // 16 * 16) for d in resolutions[p["index"]])
        if profile.MODALITY == "video":
            data, ext = engine.video(p, width, height, profile.VIDEO_NUM_FRAMES, profile.VIDEO_FPS)
        else:
            data, ext = engine.image(p, width, height)
        url = f"hf://{profile.HF_REPO or profile.NAME}@{profile.HF_REVISION or 'main'}#idx={p['index']}&seed={p['seed']}"
        path = store.add(data, ext, url=url, source=f"local_generation_{engine.name}", run_id=run_id, modality=profile.MODALITY,
                         sample_key=f"gen:{p['index']}:{p['seed']}", prompt=p["prompt"], seed=p["seed"],
                         category=p["category"], style=p["style"], backend=engine.name, flair=p["category"])
        if path:
            made += 1
            if made == 1 and on_first_sample: on_first_sample()
    return made
