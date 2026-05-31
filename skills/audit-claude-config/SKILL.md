---
name: audit-claude-config
description: Use when performing a Claude Code health check or reviewing setup quality. Triggers on "audit claude config", "full audit", "health check", "audit everything", "check my setup".
---

# Audit Claude Config

Run the audit skills, print one dashboard, and build a prioritized remediation
plan. Findings, severities, and the consent boundary follow
`reference/conventions.md`.

## Modes

| Argument | Runs |
|----------|------|
| *(none)* / `full` | every audit + `/doctor` |
| `fast` | everything except `audit-sessions` (the slow one) |

## Audit registry (run in this order: scripted/fast first, slow last)

1. `/doctor` (built-in) — run only if available
2. `audit-config` — settings.json: permissions, hooks, secrets, MCP risk, conflicts
3. `audit-context` — token-budget overhead
4. `audit-filesystem` — plugin caches, project orphans, memory hygiene
5. `audit-authoring` — skill + rule quality
6. `audit-mcp-health` — MCP servers vs live tools
7. `/warden:review-decisions` — run only if the warden plugin is installed
8. `audit-sessions` — transcript patterns (skipped in `fast` mode)

## Step 1: Run each audit

Run `/doctor` first if present; record its output (note critical issues but
continue). For each audit in the registry, invoke it via the Skill tool and
record: status (PASS = no findings, WARN = has findings, INFO = suggestions only,
FAIL = the audit errored), the finding count, the critical count, and the
findings themselves (shared schema from `reference/conventions.md`).

`/doctor` and `/warden:review-decisions` are optional. If a tool is not
installed, skip it silently — do not record it as FAIL. Only a real error in an
installed audit is FAIL (per the script-failure contract).

## Step 2: Dashboard

Print one markdown table (no box-drawing), sorted by registry order:

```
| Audit | Status | Findings | Critical |
|-------|--------|----------|----------|
| audit-config | WARN | 12 | 1 |
| ... | ... | ... | ... |
| OVERALL | WARN | 37 | 1 |
```

Overall status = worst status across audits (FAIL > WARN > INFO > PASS).

## Step 3: Remediation plan

Collect all findings, sort by severity (CRITICAL > HIGH > MEDIUM > LOW > INFO),
and group under markdown headers (`### CRITICAL (fix now)`, etc.; omit empty
groups). Render each finding:

```
- Issue: {title} ({file}:{line})
  Fix:   {fix}
```

The `fix` field is usually ready to apply. To make fixes exact, read the files a
finding points at rather than guessing. Do not propose deletions for INFO
"could not determine" findings.

## Step 4: Save the report

Write the dashboard + remediation plan to
`dev/local/audit-results/{YYYY-MM-DD}.md`, ending with a summary line
(`{total} findings: {crit} critical, {high} high, {med} medium, {low} low`).
Saving the dated report is enough — do not try to diff against previous reports
(free-text findings have no stable IDs, so the diff is unreliable).

## Step 5: Next steps

- If CRITICAL findings exist: offer to fix them now.
- Otherwise: "Setup is clean — consider scheduling periodic audits with `/schedule`."

Follow the consent boundary in `reference/conventions.md`: ask before any change.
