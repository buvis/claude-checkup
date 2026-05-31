---
name: audit-config
description: >-
  Use when auditing Claude settings.json: loose permissions, hardcoded secrets,
  hook health/injection, risky MCP servers, cross-level conflicts. Triggers on
  "audit config", "audit security", "audit permissions", "audit hooks", "audit settings".
---

# Audit Config

Audit settings.json (global + project) for security and consistency: permission
risk, hook health, settings conflicts, hardcoded secrets, risky MCP. All
deterministic work runs in `scripts/audit_config.py`; this skill runs it and
turns its findings into a prioritized, actionable report.

## Step 1: Run the audit

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_config.py"
```

Pass `--project-dir <repo>` to point at a specific repo's `.claude/` (default:
current working directory). Capture stdout JSON. Per the script-failure contract
in `reference/conventions.md`: if it exits non-zero, surface stderr and stop --
do not fabricate findings.

The output is `{audit, scanned, findings, summary}`. Each finding is
`{severity, title, fix, file, line, audit}` (the shared schema -- see
`reference/conventions.md`).

## Step 2: Present findings

Group by severity, most urgent first (CRITICAL > HIGH > MEDIUM > LOW > INFO).
For each finding render one line:

```
- [SEVERITY] {title} ({file}:{line}) — {fix}
```

Omit the `(file:line)` when absent. Omit any severity group with no findings.
End with the `summary` counts. If `findings` is empty: "Config audit: clean."

Bounded `Bash(<tool>:*)` grants are graded MEDIUM and are often numerous; group
them into one line ("N bounded Bash(tool:*) grants") rather than listing each.

INFO findings flag where a verdict could not be reached (e.g. usage telemetry
absent). Never recommend deleting a grant on the basis of an INFO "cannot
determine usage" finding.

## Step 3: Offer remediation

Follow the consent/safety boundary in `reference/conventions.md`: for CRITICAL
and HIGH findings, offer the concrete fix (the `fix` field is ready to apply);
for MEDIUM/LOW, note they may be intentional. Ask before editing settings.json.
