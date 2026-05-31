# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **audit-config**: one scripted audit of settings.json covering permission risk, hook health (all event types; existence, executability, suppression, injection, performance), cross-level settings conflicts, hardcoded secrets, and risky MCP servers. Merges the old `audit-security`, `audit-permissions`, `audit-hooks`, and `audit-settings`.
- **audit-filesystem**: one scripted audit of `~/.claude` hygiene covering plugin-cache staleness/orphans/reclaimable disk, orphaned and dormant project configs, and MEMORY.md index/staleness. Merges the old `audit-plugins`, `audit-project-orphans`, and `audit-memory`.
- **audit-authoring**: skill structural validation plus model-led skill-quality, duplicate-name, and rule conflict/redundancy/shadowing/staleness checks. Merges the old `audit-skills` and `audit-rules`.

### Removed

- **audit-security, audit-permissions, audit-hooks, audit-settings**: merged into `audit-config`. Their `/audit-*` commands no longer resolve; the trigger phrases (e.g. "audit security", "audit hooks") now route to `audit-config`.
- **audit-plugins, audit-project-orphans, audit-memory**: merged into `audit-filesystem`.
- **audit-skills, audit-rules**: merged into `audit-authoring`. The false-positive-prone skill-quality heuristics (paragraph-duplication, guardrail-keyword, pairwise description similarity) were dropped.

### Changed

- **audit-context**: now backed by `audit_context.py` so token counts are reproducible (the model no longer hand-counts across hundreds of files). Excludes settings.json (not loaded into context) and takes `--context-window` instead of hardcoding 1M.
- **audit-claude-config**: slimmed to a 6-audit registry with `full`/`fast` modes, a single markdown-table dashboard, and an `Issue`/`Fix` remediation block. Dropped the security/health/efficiency argument matrix and the unreliable diff-against-previous-report step. `/doctor` and warden run only when present; fixed the reference to the nonexistent `warden:audit` (now `warden:review-decisions`).
- **claude-checkup**: deterministic logic (config-dir resolution, the lossy project-dir decoder, JSONL reading, token heuristic, finding model, plugin-cache enumeration) moved into a shared `lib/`.

### Fixed

- **audit-filesystem**: a project dir whose source path cannot be verified is reported as INFO and never given an `rm -rf` target (previously a mis-decoded path could be suggested for deletion). Memory type parsing tolerates `metadata.type` nesting, ending a false "no type" flood. Disk sizing is portable (no BSD-only `stat`/`du`).
- **audit-config**: every finding now carries a resolved `file:line` (no more `settings.json:None`); `Bash(*:*)`/`Bash(sudo …)` are detected; Bearer/Google secrets are flagged in `mcpServers.env`, not just CLAUDE.md; all hook event types are scanned (`UserPromptSubmit`/`PreCompact` no longer skipped); and when usage telemetry is absent, "unused" is downgraded to an INFO note instead of a removal recommendation. Honours `CLAUDE_CONFIG_DIR`; reads project settings from the working dir's `.claude/`, not the empty `~/.claude/projects/*/settings.json` path.

## [0.1.2] - 2026-05-17

### Fixed

- **audit-sessions**: the `Bash(grep)` rule-violation check no longer flags `rg`. `rg` is permitted by the aegis tools policy, so flagging it produced ~1800 false-positive violations per audit.

### Changed

- **claude-checkup**: renamed plugin from `audit-suite` to `claude-checkup`. Install command is now `/plugin install claude-checkup@buvis-plugins`; the old `audit-suite` name no longer resolves. Skill names (`audit-security`, `audit-skills`, ...) and the orchestrator command (`/audit-claude-config`) are unchanged.

## [0.1.1] - 2026-05-11

### Changed

- Helper-script paths in `audit-security`, `audit-sessions`, and `audit-skills` now use `${CLAUDE_SKILL_DIR}` (the env var Claude Code exports into the Bash tool for plugin skills) instead of hardcoded `~/.claude/skills/...` paths. Required so the scripts resolve when running from the plugin install rather than the personal skills directory.

### Added

- Bundled `validate_skill.py` inside `audit-skills/scripts/` (snapshot of the validator from the `create-skill` skill) so the audit is self-contained and does not depend on `create-skill` being installed locally.

## [0.1.0] - 2026-05-10

### Added

- Initial release with 13 audit skills:
  - `audit-claude-config` — orchestrator that runs every audit and produces a unified dashboard plus prioritized remediation plan
  - `audit-security` — hardcoded secrets, loose permissions, hook injection, risky MCP servers
  - `audit-permissions` — permission sprawl, unused grants, escalations
  - `audit-hooks` — hook health, existence, executability, silent failures, performance
  - `audit-settings` — settings conflicts across global/project/local scopes
  - `audit-mcp-health` — MCP server reachability, freshness, last-used tracking
  - `audit-plugins` — plugin freshness, stale cached versions, disk reclamation
  - `audit-memory` — memory index consistency, orphan and missing entries
  - `audit-skills` — skill structural validation, frontmatter, trigger patterns
  - `audit-rules` — rule conflicts, shadowing, redundancies, staleness
  - `audit-context` — per-component token overhead, cache classification
  - `audit-sessions` — session transcript analysis, anomalies, unused skills
  - `audit-project-orphans` — stale project configs in `~/.claude/projects/`
- Python helper scripts with full pytest coverage for `audit-security` (17 tests) and `audit-sessions` (26 tests).
