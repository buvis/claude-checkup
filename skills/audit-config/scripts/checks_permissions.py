"""Permission-grant risk classification and unused-grant detection.

Merges the risk tables from the old audit-permissions skill with scan.py's
pattern matching into one deterministic classifier. Unused-grant detection is
telemetry-gated: with no usage data, it reports "cannot determine" rather than
recommending removal (the dangerous false positive in a cleanup tool).
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from claude_paths import any_usage_telemetry, iter_jsonl
from findings import Finding

SENSITIVE_PATHS = ("~/.ssh", "~/.aws", "~/.gnupg", "/etc/")
_UNRESTRICTED = re.compile(r"^(Bash|Write|Edit|Read)\(\*{1,2}(:\*)?\)$")
_BROAD_WRITE = re.compile(r"^(Write|Edit)\((~|\.)?/?\*\*\)$")
_MCP_WILDCARD = re.compile(r"^mcp__[^_]+__\*$|^mcp__\*")
_BOUNDED_BASH = re.compile(r"^Bash\([^*]+:\*\)$|^Bash\([^*]+ \*\)$")
_BROAD_READ = re.compile(r"^Read\((~|\.).*\*\*\)$")
_NARROW = re.compile(r"^(Grep|Glob|WebSearch)(\(\*?\))?$")


def split_permission(entry: str) -> tuple[str, str | None]:
    """`Bash(npm:*)` -> ("Bash", "npm:*"); `WebSearch` -> ("WebSearch", None)."""
    match = re.match(r"^([A-Za-z_]+)\((.*)\)$", entry)
    if match:
        return match.group(1), match.group(2)
    return entry, None


def classify_permission(entry: str) -> tuple[str, str, str]:
    """Return (severity, reason, fix) for one allow-list entry."""
    if any(sp in entry for sp in SENSITIVE_PATHS):
        return ("HIGH", f"grants access to a sensitive path: {entry}",
                "Remove the sensitive path unless strictly required")
    if _UNRESTRICTED.match(entry):
        return ("CRITICAL", f"{entry} grants unrestricted access",
                "Restrict to specific commands or paths")
    if entry.startswith("Bash(sudo"):
        return ("HIGH", f"{entry} permits privileged commands",
                "Avoid blanket sudo grants")
    if _BROAD_WRITE.match(entry) or _MCP_WILDCARD.match(entry):
        return ("HIGH", f"{entry} is a broad write/tool wildcard",
                "Scope to specific paths or tools")
    if _BROAD_READ.match(entry) or _BOUNDED_BASH.match(entry) or entry.startswith("WebFetch("):
        return ("MEDIUM", f"{entry} is broad but bounded",
                "Tighten the scope if this grant is not exercised")
    if _NARROW.match(entry):
        return ("LOW", f"{entry} is narrow and read/search-only", "")
    return ("LOW", f"{entry}", "")


def _find_line(raw_text: str, entry: str) -> int | None:
    for i, line in enumerate(raw_text.splitlines(), 1):
        if f'"{entry}"' in line:
            return i
    return None


def check_permissions(settings: dict, source: str, raw_text: str) -> list[Finding]:
    perms = settings.get("permissions", {})
    allow = perms.get("allow", []) or []
    deny = perms.get("deny", []) or []
    findings: list[Finding] = []

    for entry in allow:
        severity, reason, fix = classify_permission(entry)
        if severity == "LOW":
            continue  # narrow grants are not worth reporting individually
        findings.append(
            Finding(severity=severity, title=reason, fix=fix, file=source,
                    line=_find_line(raw_text, entry), audit="config")
        )

    for entry in allow:
        for denied in deny:
            if fnmatch.fnmatch(entry, denied):
                findings.append(Finding(
                    severity="CRITICAL",
                    title=f"allow entry {entry} is also denied ({denied}); deny should win",
                    fix="Remove the conflicting allow entry",
                    file=source, line=_find_line(raw_text, entry), audit="config"))

    if allow and not deny:
        findings.append(Finding(
            severity="MEDIUM",
            title="allow list present but no deny list defined",
            fix="Add a deny list for secrets/.env/credentials/SSH keys",
            file=source, audit="config"))
    return findings


def check_unused_permissions(allow: list[str], config: Path) -> list[Finding]:
    """Flag grants with no usage in telemetry; downgrade to INFO when no telemetry."""
    if not allow:
        return []
    if not any_usage_telemetry(config):
        return [Finding(
            severity="INFO",
            title=f"{len(allow)} permission grants present; usage telemetry absent, "
                  "cannot determine which are unused",
            fix="No action -- do not remove grants based on missing usage data",
            audit="config")]

    used_tools = _observed_tools(config)
    findings: list[Finding] = []
    for entry in allow:
        tool, _pattern = split_permission(entry)
        if tool not in used_tools:
            findings.append(Finding(
                severity="LOW",
                title=f"permission {entry} has no usage in tracked history",
                fix="Consider removing if intentionally unused",
                audit="config"))
    return findings


def _observed_tools(config: Path) -> set[str]:
    tools: set[str] = set()
    obs_dir = config / "instincts" / "projects"
    if obs_dir.is_dir():
        for jsonl in obs_dir.glob("*/observations.jsonl"):
            for row in iter_jsonl(jsonl):
                if row.get("tool"):
                    tools.add(str(row["tool"]))
    return tools
