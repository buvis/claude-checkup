"""JSONL session-transcript parser and skill-inventory loader.

Used by analyze.py. No heuristics live here — only schema-faithful
extraction of user messages, tool calls, tool results, and compaction
markers from one transcript file, plus on-disk skill metadata.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# -----------------------------------------------------------------------------
# Data classes (frozen for immutability)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    tool: str
    input_excerpt: str
    line_no: int
    rejected: bool
    skill_name: str | None  # populated when tool == "Skill"


@dataclass(frozen=True)
class UserMessage:
    text: str
    line_no: int
    follows_skill: str | None


@dataclass(frozen=True)
class SessionData:
    session_id: str
    project_path: str
    file_path: str
    message_count: int
    earliest: datetime | None
    latest: datetime | None
    user_messages: tuple[UserMessage, ...]
    tool_calls: tuple[ToolCall, ...]
    skill_invocations: tuple[str, ...]
    compaction_lines: tuple[int, ...]


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    triggers: tuple[str, ...]


# -----------------------------------------------------------------------------
# JSONL entry classification helpers
# -----------------------------------------------------------------------------

# promptSource values that mean "a machine wrote this prompt". Autopilot
# dispatches reviewers and implementors through the SDK, and each such session
# opens with a generated persona prompt ("You are Pat, the per-task code
# reviewer...") carrying role=user and no isMeta, so nothing else here catches
# it. Measured 2026-08-26 over 406 transcripts: 170 of the 416 prompts that
# survived this function were promptSource "sdk".
#
# A negative check on this field, rather than a positive check on
# origin.kind == "human", is deliberate: 1 of those 416 came from a transcript
# predating both fields, and a positive check would silently drop it.
_MACHINE_PROMPT_SOURCES = frozenset({"sdk"})

# User content wrappers that mark a non-user system message.
_SYNTHETIC_USER_PREFIXES = (
    "<local-command-caveat>",
    "<command-name>",
    "<command-message>",
    "<command-stdout>",
    "<local-command-stdout>",
    "<system-reminder>",
    "<task-notification>",
    "[Request interrupted by user",
)


def _content_to_text(content: Any) -> str:
    """Reduce message.content (string or list-of-blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return ""


def _is_real_user_prompt(entry: dict) -> bool:
    """True if this entry represents a genuine user-typed prompt."""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    if entry.get("promptSource") in _MACHINE_PROMPT_SOURCES:
        return False
    msg = entry.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    ):
        return False
    text = _content_to_text(content).strip()
    if not text:
        return False
    return not text.startswith(_SYNTHETIC_USER_PREFIXES)


def _extract_tool_calls(entry: dict) -> list[tuple[str, Any, str | None]]:
    """Return [(tool_name, input, tool_use_id)] for tool_use blocks."""
    if entry.get("type") != "assistant":
        return []
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    out: list[tuple[str, Any, str | None]] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            out.append(
                (block.get("name", ""), block.get("input", {}), block.get("id"))
            )
    return out


def _tool_results(entry: dict) -> list[dict]:
    """Return tool_result blocks from a user-role entry; [] otherwise."""
    if entry.get("type") != "user":
        return []
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]


def _is_compaction(entry: dict) -> bool:
    """Heuristic: detect compaction markers in observed Claude Code formats."""
    if entry.get("isCompactSummary") is True:
        return True
    sub = entry.get("subtype", "")
    if isinstance(sub, str) and "compact" in sub:
        return True
    att = entry.get("attachment")
    if isinstance(att, dict) and "compact" in str(att.get("type", "")):
        return True
    return False


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _stringify_input(tinput: Any) -> str:
    if isinstance(tinput, str):
        return tinput
    try:
        return json.dumps(tinput, sort_keys=True)
    except (TypeError, ValueError):
        return str(tinput)


# -----------------------------------------------------------------------------
# Per-line dispatcher (keeps parse_session under 50 lines)
# -----------------------------------------------------------------------------


class _SessionBuilder:
    """Mutable accumulator for parsing one JSONL file. Internal only."""

    def __init__(self, session_id: str, project_path: str, file_path: str) -> None:
        self.session_id = session_id
        self.project_path = project_path
        self.file_path = file_path
        self.user_messages: list[UserMessage] = []
        self.tool_calls: list[ToolCall] = []
        self.skill_invocations: list[str] = []
        self.compaction_lines: list[int] = []
        self.earliest: datetime | None = None
        self.latest: datetime | None = None
        self.message_count = 0
        # tool_use_id -> index in tool_calls (for back-patching rejections)
        self._pending: dict[str, int] = {}
        # (skill_name, len(user_messages)) at last Skill invocation
        self._last_skill: tuple[str, int] | None = None

    def consume(self, line_no: int, entry: dict) -> None:
        self.message_count = line_no
        ts = _parse_ts(entry.get("timestamp"))
        if ts is not None:
            if self.earliest is None or ts < self.earliest:
                self.earliest = ts
            if self.latest is None or ts > self.latest:
                self.latest = ts
        if _is_compaction(entry):
            self.compaction_lines.append(line_no)
        if _is_real_user_prompt(entry):
            self._add_user_message(entry, line_no)
            return
        for tname, tinput, tu_id in _extract_tool_calls(entry):
            self._add_tool_call(tname, tinput, tu_id, line_no)
        for tr in _tool_results(entry):
            self._mark_rejection_if_error(tr)

    def _add_user_message(self, entry: dict, line_no: int) -> None:
        text = _content_to_text((entry.get("message") or {}).get("content")).strip()
        follows = None
        if self._last_skill is not None:
            skill_name, idx_at_invoke = self._last_skill
            # Match first 3 user messages strictly after the invocation.
            if len(self.user_messages) - idx_at_invoke < 3:
                follows = skill_name
        self.user_messages.append(
            UserMessage(text=text, line_no=line_no, follows_skill=follows)
        )

    def _add_tool_call(
        self, tname: str, tinput: Any, tu_id: str | None, line_no: int
    ) -> None:
        excerpt = _stringify_input(tinput)[:200]
        skill_name = None
        if tname == "Skill" and isinstance(tinput, dict):
            skill_name = str(tinput.get("skill", "")) or None
            if skill_name:
                self.skill_invocations.append(skill_name)
                self._last_skill = (skill_name, len(self.user_messages))
        self.tool_calls.append(
            ToolCall(
                tool=tname,
                input_excerpt=excerpt,
                line_no=line_no,
                rejected=False,
                skill_name=skill_name,
            )
        )
        if tu_id:
            self._pending[tu_id] = len(self.tool_calls) - 1

    def _mark_rejection_if_error(self, tr: dict) -> None:
        tu_id = tr.get("tool_use_id")
        is_err = bool(tr.get("is_error"))
        if not is_err:
            c = str(tr.get("content", "")).lower()
            if any(w in c for w in ("permission denied", "rejected", "denied:")):
                is_err = True
        if not (is_err and tu_id and tu_id in self._pending):
            return
        idx = self._pending[tu_id]
        old = self.tool_calls[idx]
        self.tool_calls[idx] = ToolCall(
            tool=old.tool,
            input_excerpt=old.input_excerpt,
            line_no=old.line_no,
            rejected=True,
            skill_name=old.skill_name,
        )

    def build(self) -> SessionData:
        return SessionData(
            session_id=self.session_id,
            project_path=self.project_path,
            file_path=self.file_path,
            message_count=self.message_count,
            earliest=self.earliest,
            latest=self.latest,
            user_messages=tuple(self.user_messages),
            tool_calls=tuple(self.tool_calls),
            skill_invocations=tuple(self.skill_invocations),
            compaction_lines=tuple(self.compaction_lines),
        )


def parse_session(path: Path) -> SessionData | None:
    """Parse one JSONL file into a SessionData. Returns None if unreadable."""
    builder = _SessionBuilder(
        session_id=path.stem,
        project_path=path.parent.name,
        file_path=str(path),
    )
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                builder.consume(line_no, entry)
    except (OSError, UnicodeDecodeError):
        return None
    if builder.message_count == 0:
        return None
    return builder.build()


# -----------------------------------------------------------------------------
# Skill inventory loader
# -----------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_QUOTED_RE = re.compile(r'"([^"]+)"')


def load_skill_inventory(claude_dir: Path) -> dict[str, SkillMeta]:
    """Load installed skills from personal + plugin directories."""
    inventory: dict[str, SkillMeta] = {}
    paths = list(claude_dir.glob("skills/*/SKILL.md"))
    paths.extend(claude_dir.glob("plugins/installed/*/skills/*/SKILL.md"))

    for skill_md in paths:
        try:
            content = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = _FRONTMATTER_RE.match(content)
        if not m:
            continue
        fm = m.group(1)
        name = _yaml_field(fm, "name")
        desc = _yaml_field(fm, "description")
        if not name:
            continue
        triggers = tuple(_QUOTED_RE.findall(desc)) if desc else ()
        inventory[name] = SkillMeta(
            name=name, description=desc or "", triggers=triggers
        )
    return inventory


def _yaml_field(fm: str, key: str) -> str:
    """Extract a YAML scalar field (handles plain and >- block forms)."""
    lines = fm.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith(f"{key}:"):
            continue
        rest = line[len(key) + 1 :].strip()
        if rest in (">-", ">", "|", "|-"):
            collected: list[str] = []
            for cont in lines[i + 1 :]:
                if cont.startswith(("  ", "\t")):
                    collected.append(cont.strip())
                else:
                    break
            return " ".join(collected)
        if (rest.startswith('"') and rest.endswith('"')) or (
            rest.startswith("'") and rest.endswith("'")
        ):
            rest = rest[1:-1]
        return rest
    return ""
