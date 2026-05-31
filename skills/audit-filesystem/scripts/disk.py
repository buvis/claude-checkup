"""Portable directory-size helpers (no shell `du`, works on macOS and Linux)."""

from __future__ import annotations

import os
from pathlib import Path


def dir_size(path: Path) -> int:
    """Total size in bytes of all files under path. Missing path -> 0."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"
