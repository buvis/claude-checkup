"""Plugin-cache hygiene: stale cached versions and fully orphaned caches.

Disk reclaim is the reliable signal. The old skill's grep-the-session-logs
"unused plugin" check was weak and is dropped (see the SKILL.md note).
"""

from __future__ import annotations

from pathlib import Path

from disk import dir_size, human_size
from findings import Finding
from plugins import enumerate_plugins, read_installed_plugins


def check_plugins(config: Path) -> list[Finding]:
    installed = read_installed_plugins(config)
    cache = config / "plugins" / "cache"
    findings: list[Finding] = []
    for info in enumerate_plugins(cache, installed):
        if info.is_orphan:
            size = dir_size(info.cache_dir)
            findings.append(Finding(
                "LOW", f"orphaned plugin cache '{info.name}' (no manifest entry)",
                f"rm -rf {info.cache_dir}  # reclaims {human_size(size)}",
                str(info.cache_dir), audit="filesystem"))
            continue
        for version in info.stale_versions:
            version_dir = info.cache_dir / version
            findings.append(Finding(
                "LOW",
                f"stale cached version {info.name} {version} (active is {info.active_version})",
                f"rm -rf {version_dir}  # reclaims {human_size(dir_size(version_dir))}",
                str(version_dir), audit="filesystem"))
    return findings
