"""Back-compat shim — content moved to top-level `shared/` package.

This module re-exports the helpers so existing `from generate.common import X`
imports keep working until callers are migrated to import from `shared.*`.
Will be removed in a later phase once all importers are updated.
"""
from shared.clip_utils import (
    VIDEO_EXTS,
    is_source_clip,
    list_clips,
    probe_duration,
    extract_frame,
    extract_last_frame,
    extract_first_last_frames,
)
from shared.manifest import (
    MANIFEST_FIELDS,
    ClipJob,
    load_processed,
    append_manifest,
)
from shared.loaders import (
    load_captions,
    load_ranking,
    build_jobs,
)
from shared.shard import (
    shard_jobs,
)

__all__ = [
    "VIDEO_EXTS",
    "is_source_clip",
    "list_clips",
    "probe_duration",
    "extract_frame",
    "extract_last_frame",
    "extract_first_last_frames",
    "MANIFEST_FIELDS",
    "ClipJob",
    "load_processed",
    "append_manifest",
    "load_captions",
    "load_ranking",
    "build_jobs",
    "shard_jobs",
]
