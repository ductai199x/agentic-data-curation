"""Generator config loading.

Configs are plain Python modules with module-level variables.
Load them with `load_config("configs/grok.py")` and access attributes directly.

Pattern borrowed from ~/1-workdir/07-fsd/fsd/cli/generate_fsd.py.
"""

from importlib.machinery import SourceFileLoader
from pathlib import Path


def load_config(config_path: str | Path):
    """Load a generator config file as a Python module.

    Args:
        config_path: Path to a .py config file (e.g. "configs/grok.py")

    Returns:
        Module object with config attributes (e.g. config.NAME, config.CIVITAI_TOOL_ID)
    """
    config_path = str(Path(config_path).resolve())
    return SourceFileLoader("config", config_path).load_module()
