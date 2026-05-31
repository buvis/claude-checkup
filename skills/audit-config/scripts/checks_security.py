"""Secret scanning and risky MCP-server configuration.

One secret-pattern list is shared by the CLAUDE.md scan and the mcpServers.env
scan, so a Bearer/Google key is flagged wherever it appears (the old scan.py
used a narrower pattern set for env than for CLAUDE.md).
"""

from __future__ import annotations

import re
from pathlib import Path

from findings import Finding

SECRET_PATTERNS = (
    (re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"), "Anthropic API key"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub personal access token"),
    (re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"), "GitHub fine-grained PAT"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AWS access key"),
    (re.compile(r"AIza[a-zA-Z0-9_-]{35}"), "Google API key"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9_.-]{20,}"), "Bearer token"),
)
_URL_EXEC = re.compile(r"(curl|wget)\s+.*\|\s*(sh|bash)", re.IGNORECASE)


def find_secret(text: str) -> str | None:
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(text):
            return label
    return None


def check_mcp(settings: dict, source: str) -> list[Finding]:
    findings: list[Finding] = []
    for name, config in (settings.get("mcpServers") or {}).items():
        if not isinstance(config, dict):
            continue
        cmd = config.get("command", "")
        args = config.get("args", []) or []
        if "npx" in cmd and "-y" in args:
            findings.append(Finding("HIGH", f"MCP server '{name}' uses npx -y (auto-installs unreviewed)",
                                    "Install the package explicitly, then drop -y", source, audit="config"))
        if any("0.0.0.0" in str(part) for part in [cmd, *args]):
            findings.append(Finding("HIGH", f"MCP server '{name}' binds to 0.0.0.0 (network-exposed)",
                                    "Bind to 127.0.0.1/localhost", source, audit="config"))
        for key, val in (config.get("env") or {}).items():
            label = find_secret(val) if isinstance(val, str) else None
            if label:
                findings.append(Finding("CRITICAL", f"MCP server '{name}' has a hardcoded {label} in env.{key}",
                                        "Reference an environment variable instead", source, audit="config"))
    return findings


def check_secrets(config: Path) -> list[Finding]:
    findings: list[Finding] = []
    md_files = [config / "CLAUDE.md", *sorted(config.glob("projects/*/CLAUDE.md"))]
    for md in md_files:
        try:
            lines = md.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        src = str(md)
        for i, line in enumerate(lines, 1):
            label = find_secret(line)
            if label:
                findings.append(Finding("CRITICAL", f"hardcoded {label} in CLAUDE.md",
                                        "Remove the secret; use an environment variable", src, i, "config"))
            if _URL_EXEC.search(line):
                findings.append(Finding("HIGH", "instruction pipes a downloaded script into a shell",
                                        "Download and review scripts before executing", src, i, "config"))
    return findings
