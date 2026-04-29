"""Generic config for any ComfyUI-driven batch video generator.

A run is defined by:
  - the job source (clips + captions + frames)
  - the output path
  - a workflow builder module (`generate.workflows.<name>`) exposing a
    `build_workflow(cfg, first_frame, prompt, filename_prefix) -> dict`
  - a `model_kwargs` dict forwarded verbatim to the workflow builder so each
    generator can declare its own model-specific knobs

Everything runtime-related (steps, shift, cfg, scheduler, resolution, frames,
fps, LoRAs, quantization, attention mode, etc.) lives inside `model_kwargs`
since those are generator-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ComfyRunConfig:
    # ---- job source --------------------------------------------------------
    clips_dir: Path
    captions_path: Path
    frames_dir: Path
    output_dir: Path

    # ---- which generator ---------------------------------------------------
    workflow_module: str
    """Import path of a module exposing `build_workflow(cfg, ...)`.
    Examples: "generate.workflows.wan22", "generate.workflows.hunyuan_v15"."""

    model_tag: str
    """Stable identifier for this run, written to the manifest."""

    model_kwargs: dict[str, Any] = field(default_factory=dict)
    """Forwarded to the workflow builder. Every generator-specific knob lives
    here (resolution, steps, LoRAs, cfg, etc.)."""

    # ---- clip selection ----------------------------------------------------
    rank_file: Path | None = None
    """Optional path to a `diversity_rank.csv` from `generate.diversity_rank`.
    If set, the worker filters `build_jobs()` output down to the top
    `max_clips` entries in rank order (plus any stems not present in the
    rank file are dropped)."""

    max_clips: int | None = None
    """Maximum number of clips to process. If `rank_file` is set, takes the
    top-K by rank; otherwise takes the first K in `build_jobs` order."""

    # ---- prompts -----------------------------------------------------------
    prompt_max_chars: int = 1500

    prompt_source: str = "caption"
    """Which key to pull the prompt text from in the captions JSON.
    Use `"caption"` (default, long SALMONN paragraph) for local open-source
    generators that tolerate long descriptive text (Wan 2.2, LTX 2.3). Use
    `"short_caption"` (short Qwen-rewritten prompt) for commercial providers
    (Luma, Runway, Veo, Sora, etc.) that reject long third-person narrative."""

    # ---- paid commercial providers -----------------------------------------
    paid_provider: bool = False
    """Must be True to use any ComfyUI-API-Nodes commercial provider node.
    Acts as a safety gate — accidentally submitting a paid-provider workflow
    from a config with `paid_provider=False` is refused at startup."""

    api_key_file: Path = field(default_factory=lambda: Path.home() / ".comfy_org_api_key")
    """File containing the comfy.org API key. Read at startup, never logged."""

    api_key_env: str = "COMFY_ORG_API_KEY"
    """Env var to check first; falls back to api_key_file if unset."""

    cost_per_clip_usd: float = 0.0
    """Static unit cost used for budget gating. Look up in
    docs.comfy.org/tutorials/partner-nodes/pricing."""

    max_cost_usd: float = 0.0
    """Hard ceiling. Worker refuses to start if
    `cost_per_clip_usd * max_clips > max_cost_usd`, and stops mid-run if
    running total would exceed it. Must be set explicitly for paid configs."""

    # ---- server wiring -----------------------------------------------------
    comfy_root: Path = field(
        default_factory=lambda: Path("/home/tai/1-workdir/09-agent-data-curation/third_party/ComfyUI")
    )
    default_port: int = 8190
    submit_timeout_s: float = 1800

    # ---- post-run cleanup --------------------------------------------------
    delete_input_frame_after_use: bool = True


def load_config(module_name: str) -> ComfyRunConfig:
    """Import a config module and return its CONFIG attribute."""
    import importlib
    mod = importlib.import_module(module_name)
    cfg = getattr(mod, "CONFIG", None)
    if cfg is None:
        raise ValueError(f"config module '{module_name}' has no top-level CONFIG")
    if not isinstance(cfg, ComfyRunConfig):
        raise TypeError(
            f"CONFIG in '{module_name}' must be a ComfyRunConfig, got {type(cfg).__name__}"
        )
    return cfg
