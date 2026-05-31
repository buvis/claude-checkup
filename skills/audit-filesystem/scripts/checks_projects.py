"""Project-config hygiene: orphaned and dormant ~/.claude/projects/ directories.

Safety: a project dir whose source path cannot be verified is reported INFO
(unresolved) -- never as an orphan with a deletion command -- so a mis-decoded
path can never become an rm -rf target.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from claude_paths import STALENESS_DAYS, last_session_date, resolve_project_path
from disk import dir_size, human_size
from findings import Finding


def check_projects(config: Path, now: datetime) -> list[Finding]:
    projects = config / "projects"
    if not projects.is_dir():
        return []
    findings: list[Finding] = []
    for project_dir in sorted(p for p in projects.iterdir() if p.is_dir()):
        resolved = resolve_project_path(project_dir)
        if resolved.status == "UNRESOLVED":
            findings.append(Finding(
                "INFO", f"project config {project_dir.name}: source path could not be resolved",
                "Verify the source path manually before removing anything",
                str(project_dir), audit="filesystem"))
            continue
        if not Path(resolved.path).is_dir():
            size = dir_size(project_dir)
            findings.append(Finding(
                "LOW", f"orphan project config: {resolved.path} no longer exists",
                f"rm -rf {project_dir}  # reclaims {human_size(size)}",
                str(project_dir), audit="filesystem"))
            continue
        last = last_session_date(project_dir)
        if last and (now - last).days > STALENESS_DAYS["project_orphan"]:
            findings.append(Finding(
                "INFO",
                f"dormant project {resolved.path} (last session {last.date()}, "
                f">{STALENESS_DAYS['project_orphan']}d)",
                "Review whether this project is still active", str(project_dir), audit="filesystem"))
    return findings
