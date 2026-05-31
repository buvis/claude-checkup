#!/usr/bin/env python3
"""Audit context-window overhead: estimate always-loaded tokens per component.

Replaces the old hand-counted recipe -- the model can't reliably char-count and
sum across dozens of files, so the same input gave different totals each run.
This does the globbing, counting, token math, classification, and totals in code.

The one thing a script cannot see is the live session's MCP tool list, so the
count is passed in via --mcp-tools (the skill reads it from the deferred list).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Bootstrap shared lib; fail loud if missing.
_LIB = Path(__file__).resolve().parents[3] / "lib"
if not _LIB.is_dir():
    sys.exit(f"claude-checkup: shared lib not found at {_LIB}")
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

ALWAYS = "always_loaded"
HIDDEN = "hidden_tax"
ON_DEMAND = "on_demand"


@dataclass(frozen=True)
class Component:
    label: str
    kind: str
    classification: str
    tokens: int


def _counts(path: Path) -> tuple[int, int]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0
    return len(text), len(text.split())


def _split_frontmatter(path: Path) -> tuple[int, int]:
    """Return (frontmatter_words, body_words). Frontmatter is the name+desc snippet."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return len(text[3:end].split()), len(text[end + 4:].split())
    return 0, len(text.split())


def _prose(label: str, kind: str, classification: str, path: Path) -> Component:
    from tokens import prose_tokens

    _chars, words = _counts(path)
    return Component(label, kind, classification, prose_tokens(words))


def _authored(label: str, kind: str, path: Path) -> list[Component]:
    """A skill/command: name+desc always loaded, body on demand."""
    from tokens import prose_tokens

    fm_words, body_words = _split_frontmatter(path)
    return [
        Component(label, kind, ALWAYS, prose_tokens(fm_words)),
        Component(f"{label} (body)", kind, ON_DEMAND, prose_tokens(body_words)),
    ]


def _agent(label: str, path: Path) -> list[Component]:
    """A plugin agent: its description is hidden tax (Agent tool); body on demand."""
    from tokens import prose_tokens

    fm_words, body_words = _split_frontmatter(path)
    return [
        Component(label, "plugin-agent", HIDDEN, prose_tokens(fm_words)),
        Component(f"{label} (body)", "plugin-agent", ON_DEMAND, prose_tokens(body_words)),
    ]


def _scan_plugins(config: Path) -> list[Component]:
    from plugins import enumerate_plugins, read_installed_plugins

    installed = read_installed_plugins(config)
    components: list[Component] = []
    for info in enumerate_plugins(config / "plugins" / "cache", installed):
        if not info.active_version:
            continue
        root = info.cache_dir / info.active_version
        for agent in sorted(root.glob("agents/*.md")):
            components += _agent(f"{info.name}:{agent.stem}", agent)
        for skill in sorted(root.glob("skills/*/SKILL.md")):
            components += _authored(f"{info.name}:{skill.parent.name}", "plugin-skill", skill)
        for command in sorted(root.glob("commands/*.md")):
            components += _authored(f"{info.name}:{command.stem}", "plugin-command", command)
    return components


def run(config: Path, mcp_tools: int, window: int) -> dict:
    from tokens import mcp_name_tokens

    components: list[Component] = []
    claude_md = config / "CLAUDE.md"
    if claude_md.is_file():
        components.append(_prose("~/.claude/CLAUDE.md", "memory", ALWAYS, claude_md))
    for proj_md in sorted(config.glob("projects/*/CLAUDE.md")):
        components.append(_prose(f"{proj_md.parent.name}/CLAUDE.md", "memory", ALWAYS, proj_md))
    for mem in sorted(config.glob("projects/*/memory/*.md")):
        components.append(_prose(f"{mem.parent.parent.name}/memory/{mem.name}", "memory", ALWAYS, mem))
    for skill in sorted(config.glob("skills/*/SKILL.md")):
        components += _authored(f"skill:{skill.parent.name}", "user-skill", skill)
    components += _scan_plugins(config)
    if mcp_tools > 0:
        components.append(
            Component(f"MCP tool names ({mcp_tools})", "mcp", ALWAYS, mcp_name_tokens(mcp_tools)))

    totals = {
        ALWAYS: sum(c.tokens for c in components if c.classification == ALWAYS),
        HIDDEN: sum(c.tokens for c in components if c.classification == HIDDEN),
        ON_DEMAND: sum(c.tokens for c in components if c.classification == ON_DEMAND),
    }
    loaded = totals[ALWAYS] + totals[HIDDEN]
    components.sort(key=lambda c: c.tokens, reverse=True)
    return {
        "audit": "context",
        "note": "token counts are estimates (word x 1.3, MCP name x 50); settings.json is "
                "excluded because it is runtime config, not loaded into the context window",
        "components": [vars(c) for c in components],
        "totals": {**totals, "loaded_overhead": loaded},
        "window": window,
        "pct_of_window": round(100 * loaded / window, 1) if window else None,
    }


def main() -> int:
    from claude_paths import config_dir

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config-dir", type=Path, default=config_dir())
    parser.add_argument("--mcp-tools", type=int, default=0,
                        help="count of live mcp__* tool names (the skill reads this from the session)")
    parser.add_argument("--context-window", type=int, default=200_000,
                        help="context window size for the percentage (use 1000000 on the 1M model)")
    args = parser.parse_args()
    json.dump(run(args.config_dir, args.mcp_tools, args.context_window), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
