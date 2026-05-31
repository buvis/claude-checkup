---
name: audit-authoring
description: >-
  Use when checking authored skills and rule files: skill structure/frontmatter,
  duplicate or confusable skills, rule conflicts, redundancy, shadowing, staleness.
  Triggers on "audit authoring", "audit skills", "audit rules".
---

# Audit Authoring

Review the quality of authored config content: skills and rule files. Structural
skill validation is deterministic and runs in `scripts/validate_skill.py`;
everything else here is a judgment call and is done by you, the model, because no
rubric captures "do these two rules contradict" or "is this description
confusable".

Present every finding using the shared schema and the severity report block in
`reference/conventions.md`.

## Part 1: Skills

### Discover

```
Glob ~/.claude/skills/*/SKILL.md                                  (personal)
Glob ~/.claude/plugins/cache/*/*/*/skills/*/SKILL.md              (plugin)
```

For plugins with several cached versions, use only the active one (the version
in `~/.claude/plugins/installed_plugins.json`); skip the rest.

### Validate structure (deterministic)

For each personal skill, run the validator and record its `[ERROR]`/`[WARN]` lines:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/validate_skill.py" <skill-dir>
```

Per the script-failure contract in `reference/conventions.md`, surface stderr and
stop if it errors. Skip plugin skills (they follow their own conventions).

### Judge quality (model)

- **Description**: should be trigger-led ("Use when…", lists triggers), not a
  procedural summary. Flag descriptions that read as workflow steps.
- **Duplicate names**: error if two skills share a name across personal + plugin.
- **Confusable descriptions**: flag only pairs so similar the router could not
  choose between them. Shared domain words ("audit") are fine; near-identical
  trigger sets are not.

Do not re-flag skill-authoring quality that the dedicated `create-skill` validator
owns (paragraph duplication, keyword guardrail heuristics) -- those produced more
noise than signal and were removed.

## Part 2: Rules

Read global rules (`~/.claude/rules/**/*.md`), `~/.claude/CLAUDE.md`, and any
project `CLAUDE.md`/`rules/`. Then judge, in this order:

1. **Contradictions** -- opposing guidance on one topic (HIGH if directly opposed).
2. **Redundancy** -- the same guidance copied across files (extension is fine;
   verbatim repetition is not).
3. **Shadowing** -- a project rule that silently overrides a global rule without
   saying so.
4. **Staleness** -- references to tools, paths, or APIs that no longer exist
   (verify paths before flagging).
5. **CLAUDE.md overlap** -- CLAUDE.md repeating what a rule file already covers
   (both are always-loaded, so this wastes context).

For each, name the files, explain the conflict, and suggest which file should own
the guidance (prefer consolidation over deletion).

## Token cost

Report a one-line estimate of always-loaded overhead (skill name+description
snippets + rule files). Use the heuristic words x 1.3; label it an estimate.

## Offer remediation

Follow the consent boundary in `reference/conventions.md`: offer `chmod +x` for
non-executable scripts and concrete rewrites/consolidations for the rest. Ask
before editing any file.
