# Audit conventions

Shared contracts for every claude-checkup audit. Each skill points here instead
of restating these, so the rules live in one place.

## Finding schema

Scripted audits emit findings with this shape (defined in `lib/findings.py`):

```
{ "severity", "title", "fix", "file", "line", "audit" }
```

- `severity`: one of `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`.
- `fix`: a ready-to-apply command or edit (may be empty).
- `file` / `line`: source location, both optional. Render as `file:line`, or
  just `file`, or nothing -- never `file:None`.
- `audit`: which audit produced it (lets the orchestrator group findings).

## Severity meaning

| Severity | Meaning | When to act |
|----------|---------|-------------|
| CRITICAL | Data loss or secret exposure risk | Now |
| HIGH     | Real bug or significant risk | This week |
| MEDIUM   | Maintainability / cleanup | When convenient |
| LOW      | Minor / style / reclaimable | Backlog |
| INFO     | Could not determine, or context only | No action implied |

INFO never implies a fix. In particular, an INFO "could not determine usage" or
"could not resolve path" must never be turned into a deletion suggestion.

## Severity report block

Group findings by severity, most urgent first, and omit any group with zero
findings. Render each finding on one line:

```
- [SEVERITY] {title} ({file}:{line}) — {fix}
```

Drop the `({file}:{line})` part when there is no location. End with the summary
counts. If there are no findings at all, say so plainly (e.g. "Config audit: clean.").

## Script-failure contract

When a skill runs a helper script: capture stdout. If the script exits non-zero,
surface its stderr and stop. Report the audit as FAIL. Never fabricate findings
when the script did not produce them.

## Consent and safety boundary

Audits report and suggest; they do not change anything on their own.

- Ask before editing settings, rules, memories, or deleting files.
- Present destructive commands (`rm -rf`, settings edits) for the user to review;
  run them only after explicit confirmation.
- Group related fixes so the user can approve them together.
- Never delete or remove based on an INFO "could not determine" finding.
