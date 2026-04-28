"""Cross-cutting utilities shared across curate/ and generate/ packages.

Modules:
    clip_utils  — file-level: is_source_clip, list_clips, frame extraction
    manifest    — ClipJob dataclass, manifest read/write
    loaders     — caption + ranking loaders, job building
    shard       — work-sharding helpers
"""
