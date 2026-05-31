#!/usr/bin/env python3
"""Audit Claude settings: permissions, hooks, cross-level consistency, secrets, MCP risk.

Parses the global and project settings.json/.local.json once and emits a single
JSON report of Findings. Replaces the old audit-security/permissions/hooks/settings
skills. Deterministic: same input -> same output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Bootstrap the shared lib + sibling check modules onto sys.path before they are
# imported (inside the functions below). Fail loud if the shared lib is missing.
_SCRIPTS = Path(__file__).resolve().parent
_LIB = _SCRIPTS.parents[2] / "lib"
if not _LIB.is_dir():
    sys.exit(f"claude-checkup: shared lib not found at {_LIB}")
for _entry in (str(_LIB), str(_SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def _load(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return (data if isinstance(data, dict) else {}), raw
    except (OSError, json.JSONDecodeError):
        return {}, ""


def _merge(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    merged.update(overlay)
    return merged


def run(config: Path, project_dir: Path) -> dict:
    from checks_hooks import check_hooks
    from checks_permissions import check_permissions, check_unused_permissions
    from checks_security import check_mcp, check_secrets
    from checks_settings import check_settings
    from findings import SEVERITIES, sort_findings, to_dict

    g_settings, g_raw = _load(config / "settings.json")
    g_local, g_local_raw = _load(config / "settings.local.json")
    p_settings, p_raw = _load(project_dir / ".claude" / "settings.json")
    p_local, p_local_raw = _load(project_dir / ".claude" / "settings.local.json")

    per_file = [
        ("global settings.json", g_settings, g_raw),
        ("global settings.local.json", g_local, g_local_raw),
        ("project .claude/settings.json", p_settings, p_raw),
        ("project .claude/settings.local.json", p_local, p_local_raw),
    ]

    findings = []
    for label, settings, raw in per_file:
        if not settings:
            continue
        findings += check_permissions(settings, label, raw)
        findings += check_hooks(settings, label, config)
        findings += check_mcp(settings, label)

    findings += check_secrets(config)

    global_eff = _merge(g_settings, g_local)
    project_eff = _merge(p_settings, p_local)
    overlays = [("project", project_eff)] if project_eff else []
    findings += check_settings(global_eff, overlays)

    global_allow = (global_eff.get("permissions") or {}).get("allow", []) or []
    findings += check_unused_permissions(global_allow, config)

    ordered = sort_findings(findings)
    summary = {sev: sum(1 for f in ordered if f.severity == sev) for sev in SEVERITIES}
    return {
        "audit": "config",
        "scanned": {"config_dir": str(config), "project_dir": str(project_dir)},
        "findings": [to_dict(f) for f in ordered],
        "summary": summary,
    }


def main() -> int:
    from claude_paths import config_dir

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config-dir", type=Path, default=config_dir(),
                        help="Claude config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd(),
                        help="repo whose .claude/ holds project settings (default: cwd)")
    args = parser.parse_args()
    json.dump(run(args.config_dir, args.project_dir), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
