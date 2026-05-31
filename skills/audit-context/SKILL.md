---
name: audit-context
description: Use when auditing token overhead or context budget. Estimates per-component tokens, classifies as always-loaded/on-demand/hidden tax. Triggers on "audit context", "check token usage", "context budget", "how much context am I using", "token overhead".
---

# Audit Context Budget

Estimate always-loaded token overhead per component and report the biggest
trim opportunities. The counting, token math, classification, and totals run in
`scripts/audit_context.py` (deterministic -- the model cannot reliably char-count
across hundreds of files). You supply the one thing the script cannot see: the
live MCP tool count.

## Step 1: Count live MCP tools

Look at this session's deferred tool list and count the `mcp__*` tool names.
That count is authoritative for what is actually loaded now (a script only sees
configured servers, not the live list).

## Step 2: Run the audit

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/audit_context.py" --mcp-tools <count>
```

Add `--context-window 1000000` if this session is on the 1M-context model
(default is 200000). Per the script-failure contract in
`reference/conventions.md`, surface stderr and stop if it exits non-zero.

Output is `{components, totals, window, pct_of_window, note}`; each component is
`{label, kind, classification, tokens}`.

## Step 3: Present the budget

Report the `totals` (always_loaded, hidden_tax, on_demand, loaded_overhead) and
`pct_of_window`, then the top components by `tokens`. Pass through the `note`:
counts are estimates, and settings.json is excluded (it is not loaded into
context).

Caveat to state: project `CLAUDE.md`/memory files are counted per project, but
only the *active* project's are loaded in any one session -- so the sum is an
upper bound across projects, not simultaneous load.

## Step 4: Recommend trims

List the top 3 `always_loaded` + `hidden_tax` components with a concrete action
and the tokens it would save (e.g. disable an unused MCP server, archive an
inactive project's CLAUDE.md, slim a large global CLAUDE.md). On-demand content
(skill/command bodies) is not counted against the budget -- do not recommend
trimming it for context reasons.
