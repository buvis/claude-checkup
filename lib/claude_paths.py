"""Path resolution and usage telemetry for the Claude config dir.

Centralises the subtle, load-bearing logic that several audits used to restate
in prose: where the config dir is, how to turn a ~/.claude/projects/<dir> name
back into a real filesystem path (lossy -- see resolve_project_path), how to
read session/observation JSONL, and how to tell whether usage telemetry even
exists before claiming something is "unused".
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Staleness windows, documented once. Days since last use beyond which a thing
# is reported stale. Different concerns tolerate different ages.
STALENESS_DAYS = {
    "permission": 30,
    "project_orphan": 90,
    "memory_project": 30,
    "memory_user": 180,
}


def config_dir() -> Path:
    """Honour CLAUDE_CONFIG_DIR; fall back to ~/.claude. Never hardcode the home path."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def decode_project_dir(name: str) -> str:
    """Best-effort decode of a projects/ dir name back to a path.

    The encoding maps both `/` and `.` to `-`, so it is NOT reversible. This
    returns the naive candidate (leading `-` -> `/`, remaining `-` -> `/`); a
    `/.`-prefixed segment shows up as `//`, which resolve_project_path corrects
    and then verifies on disk.
    """
    if name.startswith("-"):
        return "/" + name[1:].replace("-", "/")
    return name.replace("-", "/")


def _decode_variants(name: str) -> list[str]:
    naive = decode_project_dir(name)
    variants = [naive]
    corrected = naive.replace("//", "/.")
    if corrected != naive:
        variants.append(corrected)
    return variants


@dataclass(frozen=True)
class ResolvedPath:
    status: str  # "RESOLVED" | "UNRESOLVED"
    path: str | None


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield each well-formed JSON object in a .jsonl file; skip malformed lines."""
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _index_entries(project_dir: Path) -> list[dict]:
    index = project_dir / "sessions-index.json"
    if not index.is_file():
        return []
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        entries = data.get("entries", [])
    elif isinstance(data, list):
        entries = data
    else:
        entries = []
    return [e for e in entries if isinstance(e, dict)]


def _path_from_sessions(project_dir: Path) -> str | None:
    for entry in _index_entries(project_dir):
        if entry.get("projectPath"):
            return str(entry["projectPath"])
    for jsonl in sorted(project_dir.glob("*.jsonl")):
        for row in iter_jsonl(jsonl):
            candidate = row.get("cwd") or row.get("projectPath")
            if candidate:
                return str(candidate)
    return None


def resolve_project_path(project_dir: Path, *, exists=os.path.isdir) -> ResolvedPath:
    """Resolve a projects/ dir to its source path, or UNRESOLVED.

    Order: authoritative sessions-index.json / .jsonl cwd, then a verified
    decode. Never returns a guessed path -- a path that does not verify on disk
    yields UNRESOLVED, so downstream deletion suggestions can never target a
    mis-decoded directory.
    """
    authoritative = _path_from_sessions(project_dir)
    if authoritative:
        return ResolvedPath("RESOLVED", authoritative)
    for candidate in _decode_variants(project_dir.name):
        if exists(candidate):
            return ResolvedPath("RESOLVED", candidate)
    return ResolvedPath("UNRESOLVED", None)


def last_session_date(project_dir: Path) -> datetime | None:
    """Most recent activity for a project dir, from the index or newest .jsonl mtime."""
    stamps = [
        _parse_iso(str(entry["modified"]))
        for entry in _index_entries(project_dir)
        if entry.get("modified")
    ]
    stamps = [s for s in stamps if s is not None]
    if stamps:
        return max(stamps)
    jsonls = list(project_dir.glob("*.jsonl"))
    if jsonls:
        newest = max(jsonls, key=lambda p: p.stat().st_mtime)
        return datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
    return None


def telemetry_sources(config: Path) -> dict[str, bool]:
    """Which usage-data sources exist. Absence must downgrade 'unused' verdicts."""
    return {
        "instincts": (config / "instincts" / "projects.json").is_file(),
        "warden_audit": (config / "warden-audit.jsonl").is_file(),
    }


def any_usage_telemetry(config: Path) -> bool:
    return any(telemetry_sources(config).values())
