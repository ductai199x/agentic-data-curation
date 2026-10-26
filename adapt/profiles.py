"""Generator profiles: plain Python modules with module-level variables, same pattern as configs/*.py.

A profile adds the adaptation fields (weights, HF repo or ComfyUI workflow, generation kwargs, collection sources)
on top of the usual config fields (MIN_PIXELS, KNOWN_ASPECT_RATIOS, ...). When the watch logs a generator with no profile,
a draft is written from the log entry so an agent (or Tai) can fill in the details.
"""

from importlib.machinery import SourceFileLoader
from pathlib import Path

from adapt.release_log import ReleaseEntry
from adapt.settings import Settings, slugify

DEFAULTS = {
    "MODALITY": "image",
    "WEIGHTS": "unknown",
    "LICENSE": "unknown",
    "HF_REPO": None,
    "HF_REVISION": None,
    "TORCH_DTYPE": "bfloat16",
    "GENERATION_KWARGS": {},             # passed straight to the diffusers pipeline call
    "RESOLUTIONS": [(1024, 1024)],       # (width, height) presets sampled per prompt
    "VIDEO_NUM_FRAMES": 81,
    "VIDEO_FPS": 16,
    "PROMPT_MIX": {"photo": 0.8, "art": 0.2},
    "TARGET_SAMPLES": 500,
    "SPLIT": {"train": 0.8, "val": 0.1, "eval_holdout": 0.1},
    "COLLECT_SOURCES": [],               # closed models: list of source dicts, see collect.py
    "VIDEO_BACKEND": "comfy",            # video: comfy (generate/ workers, I2V from real clips) | diffusers
    "COMFY_WORKFLOW": None,              # e.g. "generate.workflows.ltx_i2v"
    "COMFY_MODEL_KWARGS": {},
    "COMFY_SOURCE": "instagram",         # real clips under data/videos/real/<source>/ (validated, captions, frames)
    "PAID_PROVIDER": False,              # comfy.org API nodes; needs ADAPT_ALLOW_PAID=1 + MAX_COST_USD
    "MIN_PIXELS": 200_000,
    "PHASH_MAX_DISTANCE": 6,
}

DRAFT_TEMPLATE = '''"""{display} — adaptation profile (DRAFT written by the pipeline from the watch log; verify every field).

Release: {release_date}  Maker: {maker}  Link: {link}
"""

NAME = "{name}"
DISPLAY_NAME = "{display}"
RELEASE_DATE = "{release_date}"
MODALITY = "{modality}"
WEIGHTS = "{weights}"          # open | closed
LICENSE = "unknown"            # check whether outputs may be used to train a commercial detector

# === Images, open weights: diffusers ===
HF_REPO = None                 # e.g. "org/model"; gated repos read HF_TOKEN from the environment
GENERATION_KWARGS = {{}}        # e.g. {{"num_inference_steps": 30, "guidance_scale": 4.0}}
RESOLUTIONS = [(1024, 1024), (1344, 768), (768, 1344)]

# === Video: generate/ ComfyUI workers (I2V from real clips' first frames + SALMONN captions) ===
COMFY_WORKFLOW = None          # e.g. "generate.workflows.ltx_i2v"; a new model may need a new builder there
COMFY_MODEL_KWARGS = {{}}
COMFY_SOURCE = "instagram"
PAID_PROVIDER = False          # API-node providers cost money: needs ADAPT_ALLOW_PAID=1 and MAX_COST_USD
# COST_PER_CLIP_USD = 0.0
# MAX_COST_USD = 0.0

# === Closed models without an API node: collection (see adapt/collect.py) ===
COLLECT_SOURCES = [
    # {{"adapter": "url_list", "path": "configs/adapt/sources/{name}_urls.txt", "source": "official_gallery"}},
    # {{"adapter": "repo_scraper", "command": ["uv", "run", "curate", "images", "scrape", "civitai", "-c", "configs/curate/images/{name}.py", "-n", "{{n}}"], "source": "civitai"}},
]

TARGET_SAMPLES = 500
'''


def profile_path(settings: Settings, name: str) -> Path:
    return settings.profiles_dir / f"{slugify(name)}.py"


def load_profile(path: str | Path):
    module = SourceFileLoader(f"profile_{Path(path).stem}", str(Path(path).resolve())).load_module()
    for key, value in DEFAULTS.items():
        if not hasattr(module, key): setattr(module, key, value)
    return module


def ensure_profile(settings: Settings, entry: ReleaseEntry) -> tuple[Path, bool]:
    # returns (path, created_draft)
    path = profile_path(settings, entry.name)
    if path.exists(): return path, False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DRAFT_TEMPLATE.format(name=slugify(entry.name), display=entry.name, release_date=entry.release_date,
                                          maker=entry.maker, link=entry.link, modality=entry.modality, weights=entry.weights))
    return path, True
