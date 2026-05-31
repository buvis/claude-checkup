"""Memory hygiene: MEMORY.md index consistency and type-based staleness.

Index parsing extracts every .md link target regardless of surrounding
punctuation, and the type parse finds `type:` whether top-level or nested under
`metadata:` -- so a slightly different bullet/frontmatter style no longer floods
the report with false "missing index" / "no type" findings.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from claude_paths import STALENESS_DAYS
from findings import Finding

KNOWN_TYPES = frozenset({"user", "feedback", "project", "reference"})
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_TYPE = re.compile(r"^\s*type:\s*([A-Za-z]+)", re.MULTILINE)


def parse_index(text: str) -> set[str]:
    """Referenced .md filenames (basenames) from MEMORY.md list items."""
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(("-", "*")):
            continue
        for match in _LINK.finditer(stripped):
            target = match.group(1)
            if target.endswith(".md"):
                names.add(Path(target).name)
    return names


def parse_type(text: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text
    match = _TYPE.search(block)
    return match.group(1) if match else None


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def check_memory(config: Path, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    for memory_dir in sorted(config.glob("projects/*/memory")):
        if not memory_dir.is_dir():
            continue
        project = memory_dir.parent.name
        present = {p.name for p in memory_dir.glob("*.md") if p.name != "MEMORY.md"}

        index_file = memory_dir / "MEMORY.md"
        if index_file.is_file():
            referenced = parse_index(index_file.read_text(encoding="utf-8", errors="replace"))
            for ref in sorted(referenced - present):
                findings.append(Finding(
                    "MEDIUM", f"orphan index entry in {project}: MEMORY.md references missing {ref}",
                    "Remove the stale pointer from MEMORY.md", str(index_file), audit="filesystem"))
            for name in sorted(present - referenced):
                findings.append(Finding(
                    "LOW", f"missing index entry in {project}: {name} is not listed in MEMORY.md",
                    "Add a pointer line to MEMORY.md", str(memory_dir / name), audit="filesystem"))

        # Type and staleness run on every memory file, indexed or not.
        findings.extend(_staleness(memory_dir, present, project, now))
    return findings


def _staleness(memory_dir: Path, present: set[str], project: str, now: datetime) -> list[Finding]:
    findings: list[Finding] = []
    for name in sorted(present):
        path = memory_dir / name
        text = path.read_text(encoding="utf-8", errors="replace")
        mtype = parse_type(text)
        age = (now - _mtime(path)).days
        if mtype not in KNOWN_TYPES:
            findings.append(Finding(
                "LOW", f"{project}/{name}: missing or unknown memory type",
                "Add a valid type (user/feedback/project/reference) to the frontmatter",
                str(path), audit="filesystem"))
        elif mtype == "project" and age > STALENESS_DAYS["memory_project"]:
            findings.append(Finding(
                "LOW", f"{project}/{name}: project memory is {age}d old (>{STALENESS_DAYS['memory_project']}d)",
                "Review and refresh or remove", str(path), audit="filesystem"))
        elif mtype == "user" and age > STALENESS_DAYS["memory_user"]:
            findings.append(Finding(
                "LOW", f"{project}/{name}: user memory is {age}d old (>{STALENESS_DAYS['memory_user']}d)",
                "Review and refresh or remove", str(path), audit="filesystem"))
    return findings
