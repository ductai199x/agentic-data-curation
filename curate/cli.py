"""Top-level CLI for image + real-video dataset curation.

Registered as `curate` via `[project.scripts]` in pyproject.toml.
Old `python -m curate.images.scrapers.X` paths still work — this is
a convenience layer.

    curate --help                       # all commands
    curate images scrape civitai -c configs/curate/images/grok.py -n 100
    curate images validate -c configs/curate/images/grok.py
    curate images caption --dir data/images/grok/staging --output captions.json
    curate videos discover --discover --output configs/video_sources/
    curate videos download -c configs/curate/videos/youtube.py
    curate videos validate -c configs/curate/videos/youtube.py
    curate stats                                # short dataset summary
    curate stats --detailed
    curate build-metadata                       # rebuild metadata.csv per dataset
"""
from __future__ import annotations

import click

# Image scrapers
from curate.images.scrapers import (
    aigcarena, civitai, civitai_simple, freepik, grok_imagine, higgsfield,
    instagram as ig_image, midjourney, openart, recraft, reddit, sora,
    tensorart, twitter, yodayo,
)
from curate.images.validators import (
    batch_classify, pipeline as image_pipeline, serve_joycaption,
    split_grids, vlm_filter,
)

# Real-video curation
from curate.videos import (
    discover, download, validate as video_validate, screen,
    quality_sweep, validate_channels, merge_yt_manifests,
    backfill_orphan_manifest, instagram as ig_video,
)

# Top-level utilities
from curate import build_metadata as _build_metadata, stats as _stats


@click.group()
def main() -> None:
    """Image + real-video dataset curation."""


# ---- images ---------------------------------------------------------------

@main.group()
def images() -> None:
    """Image dataset curation: scrape, validate, caption."""


@images.group()
def scrape() -> None:
    """Per-source image scrapers (content-addressed, resumable)."""


for _cmd, _name in [
    (aigcarena.main, "aigcarena"),
    (civitai.main, "civitai"),
    (civitai_simple.main, "civitai-simple"),
    (freepik.main, "freepik"),
    (grok_imagine.main, "grok-imagine"),
    (higgsfield.main, "higgsfield"),
    (ig_image.main, "instagram"),
    (midjourney.main, "midjourney"),
    (openart.main, "openart"),
    (recraft.main, "recraft"),
    (reddit.main, "reddit"),
    (sora.main, "sora"),
    (tensorart.main, "tensorart"),
    (twitter.main, "twitter"),
    (yodayo.main, "yodayo"),
]:
    scrape.add_command(_cmd, name=_name)


images.add_command(image_pipeline.main, name="validate")
images.add_command(batch_classify.main, name="caption")
images.add_command(serve_joycaption.cli, name="serve-joycaption")
images.add_command(split_grids.main, name="split-grids")
images.add_command(vlm_filter.main, name="vlm-filter")


# ---- videos (real) --------------------------------------------------------

@main.group()
def videos() -> None:
    """Real-video curation: discover, download, validate, screen."""


videos.add_command(discover.main, name="discover")
videos.add_command(download.main, name="download")
videos.add_command(video_validate.main, name="validate")
videos.add_command(screen.main, name="screen")
videos.add_command(quality_sweep.main, name="quality-sweep")
videos.add_command(validate_channels.main, name="validate-channels")
videos.add_command(merge_yt_manifests.main, name="merge-manifests")
videos.add_command(backfill_orphan_manifest.main, name="backfill-manifest")
videos.add_command(ig_video.main, name="instagram")


# ---- top-level utilities --------------------------------------------------

main.add_command(_stats.main, name="stats")


@main.command(
    "build-metadata",
    help="Rebuild metadata.csv for every image dataset.",
)
def build_metadata_cmd() -> None:
    _build_metadata.main()


if __name__ == "__main__":
    main()
