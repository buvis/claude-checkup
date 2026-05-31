"""Cross-level settings consistency: unknown keys, duplicates, no-ops, conflicts.

Compares an effective-global config against higher-priority overlays (project /
local). The old skill globbed ~/.claude/projects/*/settings.json for "project
settings", but that path holds session transcripts, not settings -- so the
caller passes real overlays (the working dir's .claude/settings*.json).
"""

from __future__ import annotations

import fnmatch

from findings import Finding

KNOWN_KEYS = frozenset({
    "$schema", "permissions", "env", "hooks", "mcpServers", "enabledPlugins",
    "extraKnownMarketplaces", "effortLevel", "skipDangerousModePermissionPrompt",
    "model", "preferredNotifChannel", "trustedDirectories", "allowedTools",
    "apiKeyHelper", "customApiKeyResponses", "enableAllProjectMcpServers", "projects",
})


def _equal(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(repr, a)) == sorted(map(repr, b))
    return a == b


def _unknown_keys(settings: dict, label: str) -> list[Finding]:
    return [
        Finding("MEDIUM", f"unknown settings key '{key}' in {label} (typo?)",
                "Remove the key or correct the spelling", audit="config")
        for key in settings
        if key not in KNOWN_KEYS
    ]


def _duplicate_mcp(global_eff: dict, overlay: dict, label: str) -> list[Finding]:
    g = global_eff.get("mcpServers") or {}
    o = overlay.get("mcpServers") or {}
    findings: list[Finding] = []
    for name in sorted(set(g) & set(o)):
        if g[name] == o[name]:
            findings.append(Finding("LOW", f"MCP server '{name}' in {label} duplicates global",
                                    "Remove the redundant project-level definition", audit="config"))
        else:
            findings.append(Finding("MEDIUM", f"MCP server '{name}' diverges between global and {label}",
                                    "Reconcile the two definitions", audit="config"))
    return findings


def _deny_override(global_eff: dict, overlay: dict, label: str) -> list[Finding]:
    deny = (global_eff.get("permissions") or {}).get("deny", []) or []
    allow = (overlay.get("permissions") or {}).get("allow", []) or []
    findings: list[Finding] = []
    for entry in allow:
        if any(fnmatch.fnmatch(entry, d) for d in deny):
            findings.append(Finding("CRITICAL",
                                    f"{label} allows {entry}, which global denies",
                                    "A lower level must not circumvent a global deny",
                                    audit="config"))
    return findings


def _noops_and_conflicts(global_eff: dict, overlay: dict, label: str) -> list[Finding]:
    findings: list[Finding] = []
    for key, value in overlay.items():
        if key in ("$schema", "mcpServers") or key not in global_eff:
            continue
        if _equal(value, global_eff[key]):
            findings.append(Finding("LOW", f"{label} key '{key}' duplicates the global value",
                                    "Remove the redundant override", audit="config"))
        else:
            findings.append(Finding("INFO", f"{label} overrides global '{key}'",
                                    "Override system working as designed; verify intent",
                                    audit="config"))
    return findings


def check_settings(global_eff: dict, overlays: list[tuple[str, dict]]) -> list[Finding]:
    findings = _unknown_keys(global_eff, "global")
    for label, overlay in overlays:
        findings.extend(_unknown_keys(overlay, label))
        findings.extend(_duplicate_mcp(global_eff, overlay, label))
        findings.extend(_deny_override(global_eff, overlay, label))
        findings.extend(_noops_and_conflicts(global_eff, overlay, label))
    return findings
