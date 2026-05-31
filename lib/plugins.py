"""Plugin-cache enumeration: active version, stale versions, orphaned caches.

The cache layout is cache/<marketplace>/<plugin>/<version>/ and the authoritative
"which version is active" answer lives in plugins/installed_plugins.json, keyed
by "<plugin>@<marketplace>". A cached version that is not the active one is stale;
a cache dir with no manifest entry is a fully orphaned install.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginInfo:
    name: str
    marketplace: str
    active_version: str | None
    cached_versions: tuple[str, ...]
    cache_dir: Path

    @property
    def stale_versions(self) -> tuple[str, ...]:
        if self.active_version is None:
            return ()
        return tuple(v for v in self.cached_versions if v != self.active_version)

    @property
    def is_orphan(self) -> bool:
        return self.active_version is None


def read_installed_plugins(config: Path) -> dict:
    """Map "<plugin>@<marketplace>" -> its install record (first if several).

    Returns {} when the manifest is missing or malformed; the caller reports that.
    """
    manifest = config / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict = {}
    for key, records in data.get("plugins", {}).items():
        if isinstance(records, list) and records:
            out[key] = records[0]
        elif isinstance(records, dict):
            out[key] = records
    return out


def _subdirs(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(child.name for child in path.iterdir() if child.is_dir())


def enumerate_plugins(cache_dir: Path, installed: dict) -> list[PluginInfo]:
    """Walk cache/<marketplace>/<plugin>/ and pair each with its manifest entry."""
    infos: list[PluginInfo] = []
    if not cache_dir.is_dir():
        return infos
    for marketplace_dir in sorted(p for p in cache_dir.iterdir() if p.is_dir()):
        for plugin_dir in sorted(p for p in marketplace_dir.iterdir() if p.is_dir()):
            key = f"{plugin_dir.name}@{marketplace_dir.name}"
            record = installed.get(key)
            active = record.get("version") if record else None
            infos.append(
                PluginInfo(
                    name=plugin_dir.name,
                    marketplace=marketplace_dir.name,
                    active_version=active,
                    cached_versions=tuple(_subdirs(plugin_dir)),
                    cache_dir=plugin_dir,
                )
            )
    return infos
