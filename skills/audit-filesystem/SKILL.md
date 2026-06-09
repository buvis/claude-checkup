---
name: audit-filesystem
description: >-
  Reclaim disk and find stale ~/.claude config: orphaned plugin caches, dormant
  project dirs, memory drift. Triggers on "audit filesystem", "audit plugins",
  "audit project orphans", "audit memory", "clean plugin cache", "memory cleanup".
---

# Audit Filesystem

Find reclaimable and stale state under the Claude config dir: plugin caches,
project-config orphans, and memory index/staleness. Deterministic work runs in
`scripts/audit_filesystem.py`; this skill runs it and turns findings into safe,
actionable cleanup.

## Step 1: Run the audit

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_filesystem.py"
```

Capture stdout JSON `{audit, scanned, findings, summary}`; each finding is the
shared schema `{severity, title, fix, file, line, audit}` (see
`reference/conventions.md`). Per the script-failure contract there: if it exits
non-zero, surface stderr and stop.

## Step 2: Present findings

Group by severity, most urgent first. Render each as
`- [SEVERITY] {title} — {fix}`. Omit empty groups. End with `summary` counts.

Safety: `INFO` "source path could not be resolved" means the project dir name
could not be decoded to a verified path. **Never** offer to delete these -- the
`fix` field tells the user to verify manually. Only `LOW` "orphan project config"
findings (whose source path was checked and is gone) carry a real `rm -rf` fix.

## Step 3: Deeper memory review (model-led)

The script covers index consistency, type, and age. Complete the picture by
reading the memory files yourself (this is part of the default audit, because
deciding which cited tokens are real path references is a judgment call):

- For `reference` and `feedback` memories, check that the paths and files they
  cite still exist; flag any that are gone. (Resolving a project's source dir
  from its config-dir name is lossy, so treat a miss as "verify manually", not
  as confirmed breakage.)
- Flag cross-project near-duplicate memories (identical `name`, or descriptions
  that clearly overlap).

## Step 4: Offer cleanup

Follow the consent/safety boundary in `reference/conventions.md`. Group the
`rm -rf` commands for stale plugin versions for easy copy-paste. For confirmed
orphan project configs, offer either deletion or archiving (move to
`~/.claude/projects-archive/`). For stale memories, offer to review and remove
individually. Take no destructive action without confirmation.
