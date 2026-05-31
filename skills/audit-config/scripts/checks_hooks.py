"""Hook health: existence, executability, error suppression, injection, performance.

Iterates EVERY event key under `hooks` (not a hardcoded allowlist, so hooks on
UserPromptSubmit/PreCompact are not silently skipped), expands ~, and scans both
the command string and any resolved script file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from findings import Finding

_INTERPOLATION = re.compile(r"\$\{(file|command|content|input|tool_input|output)\}")
_EXFIL = re.compile(r"(curl\s+.*(-X\s*POST|--data|-d\s)|wget\s+.*--post)", re.IGNORECASE)
_DOWNLOAD_EXEC = re.compile(r"(curl|wget)\s+.*\|\s*(sh|bash)", re.IGNORECASE)
_PERF_TOKENS = ("curl", "wget", "fetch", "npm", "npx", "cargo build", "make", "docker", "sleep")

# Error-suppression markers and how bad each is. trap '' ERR hides everything.
_SUPPRESSION = (
    (re.compile(r"trap\s+''\s+ERR"), "HIGH", "ignores all errors via trap"),
    (re.compile(r"2>/dev/null"), "MEDIUM", "suppresses stderr"),
    (re.compile(r">/dev/null 2>&1"), "MEDIUM", "suppresses all output"),
    (re.compile(r"\|\|\s*true"), "MEDIUM", "swallows non-zero exit"),
    (re.compile(r"\|\|\s*:"), "MEDIUM", "swallows non-zero exit"),
    (re.compile(r"\|\|\s*exit\s+0"), "MEDIUM", "forces success exit"),
    (re.compile(r"set \+e"), "MEDIUM", "disables errexit"),
)


def flatten_hooks(settings: dict) -> list[dict]:
    """One record per command across all event types and matchers."""
    out: list[dict] = []
    hooks = settings.get("hooks") or {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            hook_list = entry.get("hooks") or ([entry] if entry.get("type") else [])
            for hook in hook_list:
                out.append({
                    "event": event,
                    "matcher": entry.get("matcher", "all"),
                    "command": hook.get("command", ""),
                    "timeout": hook.get("timeout"),
                })
    return out


def resolve_executable(command: str, config: Path) -> Path | None:
    """Pull the script path out of a hook command, expanding ~ and ~/.claude/."""
    for token in command.split():
        if token.endswith((".sh", ".bash", ".py")):
            expanded = token.replace("~/.claude/", str(config) + "/")
            expanded = expanded.replace("~/", str(Path.home()) + "/")
            return Path(expanded)
    return None


def _scan_script(script: Path, event: str) -> list[Finding]:
    try:
        lines = script.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    src = str(script)
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue
        if _INTERPOLATION.search(line):
            findings.append(Finding("HIGH", "variable interpolation in hook script",
                                    "Parse stdin JSON with jq instead of interpolating",
                                    src, i, "config"))
        for pattern, sev, desc in _SUPPRESSION:
            if pattern.search(line):
                findings.append(Finding(sev, f"hook script {desc}",
                                        "Let errors propagate so failures are visible",
                                        src, i, "config"))
                break
        if _EXFIL.search(line):
            findings.append(Finding("MEDIUM", "possible exfiltration: HTTP POST in hook script",
                                    "Confirm this outbound request is intended", src, i, "config"))
        if event == "SessionStart" and _DOWNLOAD_EXEC.search(line):
            findings.append(Finding("HIGH", "SessionStart hook downloads and executes a script",
                                    "Pin scripts locally instead of fetching at runtime",
                                    src, i, "config"))
    return findings


def check_hooks(settings: dict, source: str, config: Path) -> list[Finding]:
    findings: list[Finding] = []
    for hook in flatten_hooks(settings):
        cmd, event = hook["command"], hook["event"]
        findings.extend(_check_command(cmd, event, hook["timeout"], source))
        script = resolve_executable(cmd, config)
        if script is None:
            continue
        if not script.is_file():
            findings.append(Finding("CRITICAL", f"hook script not found: {script}",
                                    "Remove the dead hook entry or restore the script",
                                    source, audit="config"))
            continue
        if script.suffix in (".sh", ".bash") and not os.access(script, os.X_OK):
            findings.append(Finding("HIGH", f"hook script not executable: {script}",
                                    f"chmod +x {script}", source, audit="config"))
        findings.extend(_scan_script(script, event))
    return findings


def _check_command(cmd: str, event: str, timeout, source: str) -> list[Finding]:
    findings: list[Finding] = []
    if _INTERPOLATION.search(cmd):
        sev = "CRITICAL" if "sh -c" in cmd else "HIGH"
        findings.append(Finding(sev, f"variable interpolation in {event} hook command",
                                "Read tool_input from stdin JSON, do not interpolate",
                                source, audit="config"))
    for pattern, sev, desc in _SUPPRESSION:
        if pattern.search(cmd):
            findings.append(Finding(sev, f"{event} hook command {desc}",
                                    "Let errors propagate so failures are visible",
                                    source, audit="config"))
            break
    if event == "PreToolUse":
        slow = next((t for t in _PERF_TOKENS if t in cmd), None)
        if slow:
            findings.append(Finding("MEDIUM", f"PreToolUse hook runs a slow operation ({slow})",
                                    "Move heavy work off the per-tool-call path",
                                    source, audit="config"))
        if isinstance(timeout, (int, float)) and timeout > 10:
            findings.append(Finding("MEDIUM", "PreToolUse hook has a high timeout (runs every call)",
                                    "Lower the timeout or move the work elsewhere",
                                    source, audit="config"))
    return findings
