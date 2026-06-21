"""
Platform-aware path resolution for all Localy data.

All persistent data (models, config, benchmarks, logs, cache) lives under
a single platform-appropriate root directory. This module ensures paths
are resolved correctly on Windows, macOS, and Linux.
"""

from __future__ import annotations

import os
from pathlib import Path

from localy.core.logging import get_logger

logger = get_logger(__name__)


def get_data_root() -> Path:
    """Get the platform-appropriate root data directory.

    - Windows: %LOCALAPPDATA%\\Localy
    - macOS: ~/Library/Application Support/Localy
    - Linux: ~/.local/share/localy

    Returns:
        Path to the root data directory.
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Localy"

    try:
        if os.uname().sysname == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Localy"
    except AttributeError:
        pass

    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "localy"


def ensure_data_dirs(root: Path | None = None) -> dict[str, Path]:
    """Create all required data directories and return their paths.

    Args:
        root: Custom root directory (defaults to platform default).

    Returns:
        Dictionary mapping directory name to its Path.
    """
    if root is None:
        root = get_data_root()

    dirs = {
        "root": root,
        "models": root / "models",
        "config": root / "config",
        "benchmarks": root / "benchmarks",
        "logs": root / "logs",
        "cache": root / "cache",
        "registry": root / "registry",
    }

    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        logger.debug("directory_ensured", name=name, path=str(path))

    return dirs
