"""Single source of truth for the repo root.

`shared/paths.py` is at depth 1 under the project, so `parents[1]` is
the repo root regardless of where Python is invoked from. Import from
here instead of recomputing `Path(__file__).resolve().parents[N]` in
every script — it's tedious to keep N correct after directory moves
(see Phase 2 of the curate/generate refactor for proof).
"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT: Path = Path(__file__).resolve().parents[1]
DATA_DIR: Path = REPO_ROOT / "data"
COOKIES_DIR: Path = DATA_DIR / "cookies"
COMFY_ROOT: Path = REPO_ROOT / "third_party" / "ComfyUI"
