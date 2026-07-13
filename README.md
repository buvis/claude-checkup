# Claude Checkup

[![GitHub license](https://img.shields.io/github/license/buvis/claude-checkup)](https://github.com/buvis/claude-checkup/blob/master/LICENSE)

A health-check toolkit for [Claude Code](https://claude.ai/code). Six focused
audit skills plus a single orchestrator that runs them all, prints a dashboard,
and produces a prioritized remediation plan. Deterministic work runs in helper
scripts (so audits are reproducible); judgment calls stay with the model.

## What it audits

| Skill | Catches |
|-------|---------|
| `audit-config` | Loose permissions, hardcoded secrets, hook health/injection, risky MCP servers, cross-level settings conflicts |
| `audit-filesystem` | Stale/orphaned plugin caches, orphaned and dormant project configs, memory index drift and stale memories |
| `audit-authoring` | Skill structure/frontmatter, duplicate or confusable skills, rule conflicts/redundancy/shadowing/staleness |
| `audit-context` | Per-component token overhead, classified as always-loaded / hidden tax / on-demand |
| `audit-mcp-health` | Configured MCP servers vs live tools, disconnected servers, last-used tracking |
| `audit-sessions` | Patterns, anomalies, and unused skills across past session transcripts |
| `audit-claude-config` | **Orchestrator** — runs them all, prints a dashboard, builds a remediation plan |

## Install

Two commands inside Claude Code:

```
/plugin marketplace add buvis/claude-plugins
/plugin install claude-checkup@buvis-plugins
```

Restart Claude Code, then run `/audit-claude-config` to get a full health report.

### Update

```
/plugin update claude-checkup@buvis-plugins
```

### Alternative: install directly from this repo

```
/plugin marketplace add buvis/claude-checkup
/plugin install claude-checkup@claude-checkup
```

## Usage

```
audit my claude config        # run everything, build remediation plan
audit my claude config fast   # skip the slow session-transcript audit
```

Or invoke any individual audit by name, e.g. `audit security`, `audit hooks`,
`audit memory`, `audit plugins` — those phrases still route (to `audit-config`,
`audit-config`, `audit-filesystem`, `audit-filesystem` respectively).

The orchestrator saves a dated report to `dev/local/audit-results/{YYYY-MM-DD}.md`.

## Severity grading

Each finding gets a severity, prioritized in the remediation plan:

- **CRITICAL** — fix now (data loss, secret exposure, broken hooks)
- **HIGH** — fix this week (permission escalations, conflicting rules)
- **MEDIUM** — fix when convenient (cleanup opportunities)
- **LOW** — backlog (style, minor consistency, reclaimable disk)
- **INFO** — context only; never implies a deletion (e.g. "usage could not be determined")

## Requirements

- Claude Code with plugin support
- `python3` on PATH (helper scripts for `audit-config`, `audit-filesystem`,
  `audit-context`, `audit-sessions`)
- `PyYAML` for the skill validator used by `audit-authoring`
- Optional: [warden](https://github.com/buvis/claude-warden) — if installed, the
  orchestrator also runs `/warden:review-decisions`

## Releasing

`dev/bin/release [patch|minor|major]` is a thin shim. The shared release
script lives in the central marketplace repo,
[buvis/claude-plugins](https://github.com/buvis/claude-plugins), and every
release also bumps this plugin's entry there. Developing this plugin
therefore needs that repo cloned beside this one:

```bash
git clone git@github.com:buvis/claude-plugins.git ../claude-plugins
```

Repo-specific pre-release checks live in `dev/bin/release-checks`.

## License

MIT
