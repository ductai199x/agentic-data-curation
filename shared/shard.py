"""Work-sharding helpers for parallel-worker pipelines."""
from __future__ import annotations


def shard_jobs(jobs: list, shard_id: int, num_shards: int) -> list:
    """Partition jobs across workers — each gets every Nth job."""
    if num_shards <= 1:
        return jobs
    return [j for i, j in enumerate(jobs) if i % num_shards == shard_id]
