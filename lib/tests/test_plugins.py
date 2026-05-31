"""Tests for plugin-cache enumeration: active version, stale versions, orphan caches."""

import json
from pathlib import Path

from plugins import enumerate_plugins, read_installed_plugins


def _make_cache(tmp_path: Path, layout: dict) -> Path:
    """layout: {marketplace: {plugin: [versions]}} -> create cache/<mp>/<plugin>/<ver>/."""
    cache = tmp_path / "plugins" / "cache"
    for marketplace, plugins in layout.items():
        for plugin, versions in plugins.items():
            for ver in versions:
                (cache / marketplace / plugin / ver).mkdir(parents=True)
    return cache


def test_read_installed_plugins_flattens_records(tmp_path):
    cfg = tmp_path
    (cfg / "plugins").mkdir()
    (cfg / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "superpowers@official": [
                        {"version": "5.1.0", "installPath": "/x", "lastUpdated": "2026-05-06T16:40:22.744Z"}
                    ]
                },
            }
        )
    )
    installed = read_installed_plugins(cfg)
    assert installed["superpowers@official"]["version"] == "5.1.0"


def test_enumerate_marks_stale_versions(tmp_path):
    cache = _make_cache(tmp_path, {"official": {"superpowers": ["5.0.6", "5.1.0"]}})
    installed = {"superpowers@official": {"version": "5.1.0"}}
    infos = {p.name: p for p in enumerate_plugins(cache, installed)}
    sp = infos["superpowers"]
    assert sp.active_version == "5.1.0"
    assert set(sp.cached_versions) == {"5.0.6", "5.1.0"}
    assert sp.stale_versions == ("5.0.6",)
    assert sp.is_orphan is False


def test_enumerate_flags_orphan_cache(tmp_path):
    # Cache dir present, but no manifest entry -> fully orphaned install.
    cache = _make_cache(tmp_path, {"official": {"ghost": ["1.0.0"]}})
    infos = {p.name: p for p in enumerate_plugins(cache, installed={})}
    ghost = infos["ghost"]
    assert ghost.is_orphan is True
    assert ghost.active_version is None
    assert ghost.stale_versions == ()


def test_enumerate_handles_unknown_version(tmp_path):
    cache = _make_cache(tmp_path, {"official": {"frontend-design": ["unknown"]}})
    installed = {"frontend-design@official": {"version": "unknown"}}
    infos = {p.name: p for p in enumerate_plugins(cache, installed)}
    fd = infos["frontend-design"]
    assert fd.active_version == "unknown"
    assert fd.stale_versions == ()
