#!/usr/bin/env python3
"""Deterministic analyzer for Claude Code session transcripts.

Scans ~/.claude/projects/*/*.jsonl, extracts user prompts, tool calls,
skill invocations, and emits a JSON report of patterns: tool-sequence
n-grams, repeated prompts, rule violations, rejection storms, unused
skills, skills with negative follow-up, token-heavy sessions.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# Re-export parser symbols so existing test imports `analyze.SessionData`
# (etc.) continue to work without churn.
from parser import (
    SessionData,
    SkillMeta,
    ToolCall,
    UserMessage,
    load_skill_inventory,
    parse_session,
)

__all__ = [
    # re-exported from parser
    "SessionData",
    "SkillMeta",
    "ToolCall",
    "UserMessage",
    "load_skill_inventory",
    "parse_session",
    # public analysis surface
    "analyze",
    "discover_sessions",
    "normalize_prompt",
    "detect_rule_violations",
    "detect_tool_sequences",
    "detect_repeated_prompts",
    "detect_rejection_storms",
    "detect_unused_skills",
    "detect_skill_negative_followup",
    "detect_token_heavy",
    "detect_compaction_early",
]


# -----------------------------------------------------------------------------
# Heuristic constants
# -----------------------------------------------------------------------------

# `rg` is allowed (faster than grep, respects .gitignore) per aegis tools policy.
_BASH_GREP_RE = re.compile(r"^(grep|ag)\b")
_BASH_GIT_GREP_RE = re.compile(r"^git\s+(grep|log)\b")
_BASH_CAT_RE = re.compile(r"^(cat|head|tail|less|more)\s+\S")
_BASH_HEREDOC_RE = re.compile(r"<<\s*['\"]?[A-Za-z]+")
_BASH_FIND_RE = re.compile(r"^find\s+\S")
_BASH_ECHO_RE = re.compile(r"^(echo|printf)\b.*?[>|]\s*\S")
_BASH_NEWLINE_RE = re.compile(r"\n\s*\S")
# Match shell pipes (whitespace on both sides), excluding regex pipes
# inside quoted patterns. Allowlist common stdout filters.
_BASH_PIPE_RE = re.compile(
    r"\s\|\s+(?!jq\b|grep\b|rg\b|head\b|tail\b|sort\b|uniq\b|wc\b|awk\b|sed\b|cut\b|tr\b|xargs\b|column\b|less\b|more\b|tee\b)\w"
)
# Single- or double-quoted spans, stripped before the pipe check so a
# space-padded pipe inside a quoted regex (e.g. `rg 'foo | bar' file`) is
# not mistaken for a shell pipe.
_QUOTED_SPAN_RE = re.compile(r"'[^']*'|\"[^\"]*\"")

_LEAD_SEGMENT_SPLIT_RE = re.compile(r"\s\|\s|;|&&|\|\|")

_CORRECTION_TOKENS = (
    "no,",
    "no.",
    "wrong",
    "actually",
    "instead",
    "undo",
    "revert",
    "try again",
    "that's not right",
    "not what i wanted",
    "stop",
)

_STOPWORDS = frozenset(
    "a an the and or but if then to of in on for with at by from is are was were be been "
    "this that those these it its their our your my we you i he she they me him her us them".split()
)
_PATH_RE = re.compile(r"(?:/[\w.-]+)+|~[/\w.-]*|\b[\w.-]+\.[a-zA-Z]{1,5}\b")
_NONWORD_RE = re.compile(r"[^\w\s]+")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def normalize_prompt(text: str) -> str:
    t = text.lower()
    t = _PATH_RE.sub(" ", t)
    t = _NONWORD_RE.sub(" ", t)
    tokens = [w for w in t.split() if w and w not in _STOPWORDS and len(w) > 1]
    return " ".join(tokens)


def _extract_bash_command(input_excerpt: str) -> str:
    """Pull the 'command' field out of a Bash tool input excerpt."""
    try:
        obj = json.loads(input_excerpt)
        if isinstance(obj, dict):
            return str(obj.get("command", ""))
    except (json.JSONDecodeError, TypeError):
        pass
    return input_excerpt


def _first_command_segment(cmd: str) -> str:
    """Return the leading command before any pipe/separator.

    `mise ls | grep foo` → `mise ls` (so we don't flag the grep filter).
    `cat foo` → `cat foo` (no separator, full string).
    """
    parts = _LEAD_SEGMENT_SPLIT_RE.split(cmd, maxsplit=1)
    return parts[0].strip()


def _check_grep(cmd: str) -> bool:
    head = _first_command_segment(cmd)
    if _BASH_GIT_GREP_RE.search(head):
        return False
    return bool(_BASH_GREP_RE.search(head))


def _check_cat(cmd: str) -> bool:
    head = _first_command_segment(cmd)
    if _BASH_HEREDOC_RE.search(head):
        return False
    return bool(_BASH_CAT_RE.search(head))


def _check_find(cmd: str) -> bool:
    return bool(_BASH_FIND_RE.search(_first_command_segment(cmd)))


def _check_echo(cmd: str) -> bool:
    return bool(_BASH_ECHO_RE.search(_first_command_segment(cmd)))


def _check_multiline(cmd: str) -> bool:
    return bool(_BASH_NEWLINE_RE.search(cmd))


def _check_pipe(cmd: str) -> bool:
    # Blank out quoted spans first so a space-padded pipe inside a quoted
    # regex doesn't read as a shell pipe; pipes outside quotes survive.
    return bool(_BASH_PIPE_RE.search(_QUOTED_SPAN_RE.sub(" ", cmd)))


# -----------------------------------------------------------------------------
# Heuristic detectors
# -----------------------------------------------------------------------------


def detect_rule_violations(sessions: Iterable[SessionData]) -> list[dict]:
    """Find Bash usages that should have used dedicated tools."""
    rules = (
        ("bash_grep", "Use Grep tool instead of Bash(grep/ag)", _check_grep),
        ("bash_cat", "Use Read tool instead of Bash(cat/head/tail/less/more)", _check_cat),
        ("bash_find", "Use Glob tool instead of Bash(find)", _check_find),
        ("bash_echo_redirect", "Use Write tool instead of Bash(echo/printf > file)", _check_echo),
        ("bash_multiline", "Split multi-line Bash into separate calls", _check_multiline),
        ("bash_heterogeneous_pipe", "Avoid pipe between heterogeneous commands", _check_pipe),
    )

    counts: Counter[str] = Counter()
    evidence: dict[str, list[dict]] = defaultdict(list)
    sessions_by_kind: dict[str, set[str]] = defaultdict(set)

    for sess in sessions:
        for tc in sess.tool_calls:
            if tc.tool != "Bash":
                continue
            cmd = _extract_bash_command(tc.input_excerpt)
            for kind, _label, checker in rules:
                if not checker(cmd):
                    continue
                counts[kind] += 1
                sessions_by_kind[kind].add(sess.session_id)
                if len(evidence[kind]) < 5:
                    evidence[kind].append(
                        {"session": sess.session_id, "line": tc.line_no, "snippet": cmd[:150]}
                    )

    findings: list[dict] = []
    for kind, label, _ in rules:
        if counts[kind] == 0:
            continue
        findings.append(
            {
                "category": "rule_violation",
                "classification": "workflow_improvement",
                "title": label,
                "frequency": counts[kind],
                "sessions": sorted(sessions_by_kind[kind]),
                "projects": [],
                "evidence": evidence[kind],
                "details": {"rule": kind},
            }
        )
    return findings


def detect_tool_sequences(sessions: list[SessionData], top_k: int = 20) -> list[dict]:
    """Find recurring n-grams of consecutive tool names across sessions."""
    ngram_counts: Counter[tuple[str, ...]] = Counter()
    ngram_sessions: dict[tuple[str, ...], set[str]] = defaultdict(set)
    ngram_evidence: dict[tuple[str, ...], list[dict]] = defaultdict(list)

    for sess in sessions:
        names = tuple(tc.tool for tc in sess.tool_calls)
        for n in (3, 4, 5):
            seen_in_session: set[tuple[str, ...]] = set()
            for i in range(len(names) - n + 1):
                gram = names[i : i + n]
                if len(set(gram)) == 1:
                    continue
                ngram_counts[gram] += 1
                ngram_sessions[gram].add(sess.session_id)
                if gram not in seen_in_session:
                    seen_in_session.add(gram)
                    if len(ngram_evidence[gram]) < 3:
                        ngram_evidence[gram].append(
                            {
                                "session": sess.session_id,
                                "line": sess.tool_calls[i].line_no,
                                "snippet": " → ".join(gram),
                            }
                        )

    candidates = [
        (gram, cnt)
        for gram, cnt in ngram_counts.most_common()
        if cnt >= 3 and len(ngram_sessions[gram]) >= 2
    ]
    findings: list[dict] = []
    for gram, cnt in candidates[:top_k]:
        findings.append(
            {
                "category": "tool_sequence",
                "classification": "skill_candidate",
                "title": " → ".join(gram),
                "frequency": cnt,
                "sessions": sorted(ngram_sessions[gram]),
                "projects": [],
                "evidence": ngram_evidence[gram],
                "details": {"length": len(gram)},
            }
        )
    return findings


def detect_repeated_prompts(sessions: list[SessionData]) -> list[dict]:
    """Cluster user prompts by exact normalized form."""
    clusters: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for sess in sessions:
        for um in sess.user_messages:
            norm = normalize_prompt(um.text)
            if len(norm.split()) < 3:
                continue
            clusters[norm].append((sess.session_id, um.text, um.line_no))

    findings: list[dict] = []
    for norm, items in clusters.items():
        sessions_in_cluster = {sid for sid, _, _ in items}
        if len(items) < 3 or len(sessions_in_cluster) < 2:
            continue
        evidence = [
            {"session": sid, "line": ln, "snippet": txt[:200]}
            for sid, txt, ln in items[:5]
        ]
        findings.append(
            {
                "category": "repeated_prompt",
                "classification": "skill_candidate",
                "title": norm[:80],
                "frequency": len(items),
                "sessions": sorted(sessions_in_cluster),
                "projects": [],
                "evidence": evidence,
                "details": {"normalized": norm},
            }
        )
    findings.sort(key=lambda f: f["frequency"], reverse=True)
    return findings


def _longest_rejection_streak(
    tool_calls: tuple[ToolCall, ...],
) -> tuple[int, str, int]:
    """Return (best_streak, best_tool, best_start_line) for consecutive same-tool rejections."""
    best_streak = 0
    best_tool = ""
    best_start_line = 0
    cur_streak = 0
    cur_tool: str | None = None
    cur_start_line = 0
    for tc in tool_calls:
        if tc.rejected and tc.tool == cur_tool:
            cur_streak += 1
        elif tc.rejected:
            cur_tool = tc.tool
            cur_streak = 1
            cur_start_line = tc.line_no
        else:
            cur_tool = None
            cur_streak = 0
        if cur_streak > best_streak:
            best_streak = cur_streak
            best_tool = cur_tool or ""
            best_start_line = cur_start_line
    return best_streak, best_tool, best_start_line


def detect_rejection_storms(
    sessions: list[SessionData], top_k: int = 20
) -> list[dict]:
    """Flag retry loops: ≥3 *consecutive* rejections of the same tool."""
    findings: list[dict] = []
    for sess in sessions:
        streak, tool, start_line = _longest_rejection_streak(sess.tool_calls)
        if streak < 3:
            continue
        findings.append(
            {
                "category": "rejection_storm",
                "classification": "config_fix",
                "title": f"{tool} rejected {streak}× in a row",
                "frequency": streak,
                "sessions": [sess.session_id],
                "projects": [sess.project_path],
                "evidence": [
                    {
                        "session": sess.session_id,
                        "line": start_line,
                        "snippet": f"{streak} consecutive {tool} rejections starting line {start_line}",
                    }
                ],
                "details": {"worst_tool": tool, "streak": streak},
            }
        )
    findings.sort(key=lambda f: f["frequency"], reverse=True)
    return findings[:top_k]


def detect_unused_skills(
    sessions: list[SessionData], inventory: dict[str, SkillMeta]
) -> tuple[dict[str, int], list[str], list[dict]]:
    """Compute invocation histogram, never-invoked list, and skill_unused findings."""
    invoked: Counter[str] = Counter()
    for sess in sessions:
        invoked.update(sess.skill_invocations)

    never = sorted(set(inventory) - set(invoked))
    findings: list[dict] = []
    all_user_text = "\n".join(
        um.text.lower() for sess in sessions for um in sess.user_messages
    )

    for skill_name in never:
        meta = inventory[skill_name]
        triggers = [t.lower() for t in meta.triggers if len(t) >= 4]
        matches = [t for t in triggers if t in all_user_text]
        if not matches:
            continue
        findings.append(
            {
                "category": "skill_unused",
                "classification": "config_fix",
                "title": f"Skill '{skill_name}' never invoked despite trigger matches",
                "frequency": len(matches),
                "sessions": [],
                "projects": [],
                "evidence": [
                    {
                        "session": "",
                        "line": 0,
                        "snippet": f"matched triggers: {matches[:5]}",
                    }
                ],
                "details": {"skill": skill_name, "matched_triggers": matches[:10]},
            }
        )
    return dict(invoked), never, findings


def detect_skill_negative_followup(sessions: list[SessionData]) -> list[dict]:
    by_skill: dict[str, list[dict]] = defaultdict(list)
    for sess in sessions:
        for um in sess.user_messages:
            if not um.follows_skill:
                continue
            low = um.text.lower()
            if any(tok in low for tok in _CORRECTION_TOKENS):
                by_skill[um.follows_skill].append(
                    {
                        "session": sess.session_id,
                        "line": um.line_no,
                        "snippet": um.text[:160],
                    }
                )

    findings: list[dict] = []
    for skill, evidences in by_skill.items():
        if len(evidences) < 2:
            continue
        findings.append(
            {
                "category": "skill_negative",
                "classification": "config_fix",
                "title": f"Skill '{skill}' had {len(evidences)} negative follow-ups",
                "frequency": len(evidences),
                "sessions": sorted({e["session"] for e in evidences}),
                "projects": [],
                "evidence": evidences[:5],
                "details": {"skill": skill},
            }
        )
    findings.sort(key=lambda f: f["frequency"], reverse=True)
    return findings


def detect_token_heavy(sessions: list[SessionData], top_k: int = 10) -> list[dict]:
    """Flag the top-K longest sessions over a strict threshold."""
    if not sessions:
        return []
    counts = [s.message_count for s in sessions]
    median = statistics.median(counts)
    threshold = max(3 * median, 100)
    heavy = sorted(
        (s for s in sessions if s.message_count > threshold),
        key=lambda s: s.message_count,
        reverse=True,
    )[:top_k]
    findings: list[dict] = []
    for s in heavy:
        findings.append(
            {
                "category": "token_heavy_session",
                "classification": "workflow_improvement",
                "title": f"Session {s.message_count} msgs (>{int(threshold)} threshold)",
                "frequency": 1,
                "sessions": [s.session_id],
                "projects": [s.project_path],
                "evidence": [
                    {
                        "session": s.session_id,
                        "project": s.project_path,
                        "message_count": s.message_count,
                        "threshold": int(threshold),
                    }
                ],
                "details": {"message_count": s.message_count, "threshold": threshold},
            }
        )
    return findings


def detect_compaction_early(sessions: list[SessionData]) -> list[dict]:
    findings: list[dict] = []
    for s in sessions:
        if not s.compaction_lines or s.message_count < 30:
            continue
        first_third = s.message_count / 3
        early = [ln for ln in s.compaction_lines if ln < first_third]
        if not early:
            continue
        findings.append(
            {
                "category": "compaction_early",
                "classification": "workflow_improvement",
                "title": f"Compaction at line {early[0]} (session has {s.message_count})",
                "frequency": len(early),
                "sessions": [s.session_id],
                "projects": [s.project_path],
                "evidence": [
                    {
                        "session": s.session_id,
                        "project": s.project_path,
                        "first_compaction_line": early[0],
                        "message_count": s.message_count,
                    }
                ],
                "details": {"early_lines": early, "message_count": s.message_count},
            }
        )
    return findings


# -----------------------------------------------------------------------------
# Discovery + pipeline
# -----------------------------------------------------------------------------


def discover_sessions(
    projects_dir: Path,
    days: int,
    min_messages: int = 10,
) -> tuple[list[SessionData], int]:
    """Glob all .jsonl files, parse, filter by lookback + min message count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    qualifying: list[SessionData] = []
    skipped_short = 0

    for jsonl in sorted(projects_dir.glob("*/*.jsonl")):
        sess = parse_session(jsonl)
        if sess is None:
            continue
        if sess.latest is None or sess.latest < cutoff:
            continue
        if sess.message_count < min_messages:
            skipped_short += 1
            continue
        qualifying.append(sess)
    return qualifying, skipped_short


def _annotate_projects(findings: list[dict], sessions: list[SessionData]) -> None:
    sess_to_proj = {s.session_id: s.project_path for s in sessions}
    for f in findings:
        if f.get("projects"):
            continue
        projs = sorted(
            {sess_to_proj.get(sid, "") for sid in f.get("sessions", []) if sid}
        )
        f["projects"] = [p for p in projs if p]


def analyze(claude_dir: Path, projects_dir: Path, days: int) -> dict:
    sessions, skipped_short = discover_sessions(projects_dir, days)
    inventory = load_skill_inventory(claude_dir)

    findings: list[dict] = []
    findings.extend(detect_tool_sequences(sessions))
    findings.extend(detect_repeated_prompts(sessions))
    findings.extend(detect_rule_violations(sessions))
    findings.extend(detect_rejection_storms(sessions))
    findings.extend(detect_token_heavy(sessions))
    findings.extend(detect_compaction_early(sessions))
    invoked, never, unused_findings = detect_unused_skills(sessions, inventory)
    findings.extend(unused_findings)
    negative_findings = detect_skill_negative_followup(sessions)
    findings.extend(negative_findings)
    _annotate_projects(findings, sessions)

    counts = [s.message_count for s in sessions]
    earliest_dates = [s.earliest for s in sessions if s.earliest]
    latest_dates = [s.latest for s in sessions if s.latest]

    return {
        "scanned": {
            "days": days,
            "sessions_total": len(sessions),
            "sessions_skipped_short": skipped_short,
            "projects": len({s.project_path for s in sessions}),
            "date_range": {
                "earliest": min(earliest_dates).isoformat() if earliest_dates else None,
                "latest": max(latest_dates).isoformat() if latest_dates else None,
            },
            "median_message_count": int(statistics.median(counts)) if counts else 0,
        },
        "findings": findings,
        "skill_usage": {
            "invoked": invoked,
            "never_invoked": never,
        },
    }


def main() -> int:
    arg_parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    arg_parser.add_argument("--days", type=int, default=30, help="lookback window in days")
    arg_parser.add_argument("--claude-dir", type=Path, default=Path.home() / ".claude")
    arg_parser.add_argument(
        "--projects-dir",
        type=Path,
        default=None,
        help="default: <claude-dir>/projects",
    )
    args = arg_parser.parse_args()
    projects_dir = args.projects_dir or (args.claude_dir / "projects")

    if not projects_dir.is_dir():
        print(f"projects dir not found: {projects_dir}", file=sys.stderr)
        return 1

    result = analyze(args.claude_dir, projects_dir, args.days)
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
