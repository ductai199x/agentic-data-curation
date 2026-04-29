"""Top-level CLI for fake-video generation.

Registered as `generate` via `[project.scripts]` in pyproject.toml.
Old `python -m generate.X` paths still work — this is a convenience layer.

    generate --help                          # all commands
    generate extract-frames --clips ...      # pre-extract first/last frames
    generate diversity-rank --labels ...     # stratified round-robin pick
    generate rewrite-captions --captions ... # short-form caption rewrite
    generate interpolate-fps --root ...      # RIFE 16fps→30fps
    generate metadata --root data/videos/fake # build manifest+metadata.csv
"""
from __future__ import annotations

import click

from generate import (
    build_dataset_metadata, calibrate_credits, comfy_batch_run,
    diversity_rank, extract_frames, interpolate_fps, regen_stretched,
    rewrite_captions, taxonomy_label,
)


@click.group()
def main() -> None:
    """Fake-video generation pipeline."""


main.add_command(extract_frames.main, name="extract-frames")
main.add_command(diversity_rank.main, name="diversity-rank")
main.add_command(rewrite_captions.main, name="rewrite-captions")
main.add_command(interpolate_fps.main, name="interpolate-fps")
main.add_command(taxonomy_label.main, name="taxonomy-label")
main.add_command(build_dataset_metadata.cli, name="metadata")
main.add_command(regen_stretched.main, name="regen-stretched")


@main.command(
    "batch",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    help=(
        "Run a ComfyUI worker shard. Driven by env vars, not flags: "
        "COMFY_CONFIG=<module> SHARDS=N SHARD_ID=I. "
        "Normally launched via scripts/launch.sh."
    ),
)
def batch_cmd() -> None:
    comfy_batch_run.main()


@main.command(
    "calibrate-credits",
    help="One-time credit-cost calibration for paid commercial pilots.",
)
def calibrate_cmd() -> None:
    calibrate_credits.main()


if __name__ == "__main__":
    main()
