"""Tests for analyze.py - session transcript analyzer."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import analyze


# -----------------------------------------------------------------------------
# Fixture helpers
# -----------------------------------------------------------------------------


def _now_iso(offset_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat().replace("+00:00", "Z")


def _ago_iso(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat().replace("+00:00", "Z")


def _user_text(text: str, ts: str | None = None, is_meta: bool = False) -> dict:
    return {
        "type": "user",
        "isMeta": is_meta,
        "message": {"role": "user", "content": text},
        "timestamp": ts or _now_iso(),
        "sessionId": "test",
    }


def _assistant_tool_use(
    tool: str, tool_input: dict, tool_use_id: str, ts: str | None = None
) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_use_id,
                    "name": tool,
                    "input": tool_input,
                }
            ],
        },
        "timestamp": ts or _now_iso(),
        "sessionId": "test",
    }


def _user_tool_result(
    tool_use_id: str, content: str, is_error: bool = False, ts: str | None = None
) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": is_error,
                }
            ],
        },
        "timestamp": ts or _now_iso(),
        "sessionId": "test",
    }


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


# -----------------------------------------------------------------------------
# Parsing tests
# -----------------------------------------------------------------------------


def test_extract_user_messages_skips_meta(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    _write_jsonl(
        p,
        [
            _user_text("real prompt one"),
            _user_text("meta caveat", is_meta=True),
            _user_text("<command-name>/clear</command-name>"),
            _user_text("<system-reminder>...</system-reminder>"),
            _user_text("real prompt two"),
        ],
    )
    sess = analyze.parse_session(p)
    assert sess is not None
    assert [um.text for um in sess.user_messages] == [
        "real prompt one",
        "real prompt two",
    ]


def test_extract_user_messages_handles_list_content(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    entries = [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello there"},
                    {"type": "text", "text": "second part"},
                ],
            },
            "timestamp": _now_iso(),
        }
    ]
    _write_jsonl(p, entries)
    sess = analyze.parse_session(p)
    assert sess is not None
    assert sess.user_messages[0].text == "hello there\nsecond part"


def test_extract_tool_calls(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    _write_jsonl(
        p,
        [
            _assistant_tool_use("Read", {"file_path": "/x"}, "tu_1"),
            _assistant_tool_use("Bash", {"command": "ls"}, "tu_2"),
        ],
    )
    sess = analyze.parse_session(p)
    assert sess is not None
    assert [tc.tool for tc in sess.tool_calls] == ["Read", "Bash"]


def test_detect_rejection(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    _write_jsonl(
        p,
        [
            _assistant_tool_use("Write", {"file_path": "/x"}, "tu_1"),
            _user_tool_result("tu_1", "<tool_use_error>...", is_error=True),
            _assistant_tool_use("Read", {"file_path": "/y"}, "tu_2"),
            _user_tool_result("tu_2", "ok", is_error=False),
        ],
    )
    sess = analyze.parse_session(p)
    assert sess is not None
    rejected = {tc.tool for tc in sess.tool_calls if tc.rejected}
    assert rejected == {"Write"}


def test_detect_rejection_textual_permission_denied(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    _write_jsonl(
        p,
        [
            _assistant_tool_use("Bash", {"command": "rm -rf /"}, "tu_1"),
            _user_tool_result("tu_1", "Permission denied by Warden", is_error=False),
        ],
    )
    sess = analyze.parse_session(p)
    assert sess is not None
    assert sess.tool_calls[0].rejected is True


def test_skill_invocation_recorded(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    _write_jsonl(
        p,
        [
            _assistant_tool_use("Skill", {"skill": "brainstorming"}, "tu_1"),
        ],
    )
    sess = analyze.parse_session(p)
    assert sess is not None
    assert sess.skill_invocations == ("brainstorming",)
    assert sess.tool_calls[0].skill_name == "brainstorming"


def test_follows_skill_window(tmp_path: Path) -> None:
    p = tmp_path / "proj/sess.jsonl"
    _write_jsonl(
        p,
        [
            _user_text("invoke brainstorming"),
            _assistant_tool_use("Skill", {"skill": "brainstorming"}, "tu_1"),
            _user_text("no, that's wrong"),  # 1st user message after skill
            _user_text("ok continue"),  # 2nd
            _user_text("further unrelated"),  # 3rd
            _user_text("totally separate later"),  # 4th, should NOT follow
        ],
    )
    sess = analyze.parse_session(p)
    assert sess is not None
    follows = [um.follows_skill for um in sess.user_messages]
    assert follows == [None, "brainstorming", "brainstorming", "brainstorming", None]


# -----------------------------------------------------------------------------
# Heuristic tests
# -----------------------------------------------------------------------------


def test_normalize_prompt_strips_paths_and_stopwords() -> None:
    norm = analyze.normalize_prompt(
        "Please review the file /Users/alice/foo.py and tell me what's wrong"
    )
    assert "users" not in norm
    assert "alice" not in norm
    assert "py" not in norm
    assert "foo" not in norm
    assert "review" in norm
    assert "the" not in norm  # stopword


def test_rule_violation_bash_grep() -> None:
    assert analyze._check_grep("grep -r foo .")
    assert analyze._check_grep("ag foo")
    # rg is allowed (faster than grep, respects .gitignore) per aegis tools policy
    assert not analyze._check_grep("rg foo")
    assert not analyze._check_grep("git grep foo")
    assert not analyze._check_grep("git log --grep=foo")
    # filtering CLI output through grep is fine, not a Grep-tool replacement
    assert not analyze._check_grep("mise ls 2>&1 | grep -i foo")
    assert not analyze._check_grep("docker ps | grep web")


def test_rule_violation_bash_cat_skips_heredoc_and_pipes() -> None:
    assert analyze._check_cat("cat /etc/hosts")
    assert not analyze._check_cat("cat <<EOF\nhello\nEOF")
    assert not analyze._check_cat("cat <<'EOF'\nx\nEOF")
    # head/tail used to truncate CLI output is legitimate
    assert not analyze._check_cat("mise doctor 2>&1 | head -80")
    assert not analyze._check_cat("ls | tail -5")


def test_rule_violation_bash_find() -> None:
    assert analyze._check_find("find . -name '*.py'")


def test_rule_violation_bash_echo_redirect() -> None:
    assert analyze._check_echo("echo hello > /tmp/foo")
    assert not analyze._check_echo("echo hello world")


def test_rule_violation_pipe_homogeneous_allowed() -> None:
    assert not analyze._check_pipe("ls | grep py")
    assert not analyze._check_pipe("cat foo | jq .")
    assert analyze._check_pipe("ls | xyz")
    # pipes inside quoted regex patterns shouldn't fire (no whitespace around |)
    assert not analyze._check_pipe("grep -E '(foo|bar|baz)' file")
    assert not analyze._check_pipe("rg '(alpha|beta)' .")


def test_rule_violation_pipe_ignores_space_padded_quoted_pipe() -> None:
    # A space-padded pipe inside a quoted regex must NOT be flagged as a
    # heterogeneous bash pipe (the false positive R2 fixes).
    assert not analyze._check_pipe("rg 'foo | bar' file")
    assert not analyze._check_pipe('rg "foo | bar" file')
    # A real heterogeneous pipe outside quotes still fires...
    assert analyze._check_pipe("cat x | python -c 'print(1)'")
    # ...including when a quoted span sits before the real pipe.
    assert analyze._check_pipe("rg 'pat' file | python -c 'print(1)'")
    # No-whitespace quoted alternation stays clean.
    assert not analyze._check_pipe("rg '(a|b)' .")


def test_skill_inventory_parses_frontmatter(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills/example-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\n'
        'name: example-skill\n'
        'description: >-\n'
        '  Use when "frobnicate the widget" or "calibrate frobnicator".\n'
        '---\n'
        '\n'
        'Body content.\n'
    )
    inv = analyze.load_skill_inventory(tmp_path)
    assert "example-skill" in inv
    triggers = inv["example-skill"].triggers
    assert "frobnicate the widget" in triggers
    assert "calibrate frobnicator" in triggers


def test_tool_sequence_ngrams_threshold() -> None:
    """3-gram appearing in 2 sessions, 3+ times total → flagged."""
    s1 = analyze.SessionData(
        session_id="s1",
        project_path="p",
        file_path="",
        message_count=20,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=tuple(
            analyze.ToolCall(t, "", i, False, None)
            for i, t in enumerate(["Read", "Edit", "Bash", "Read", "Edit", "Bash"])
        ),
        skill_invocations=(),
        compaction_lines=(),
    )
    s2 = analyze.SessionData(
        session_id="s2",
        project_path="p",
        file_path="",
        message_count=20,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=tuple(
            analyze.ToolCall(t, "", i, False, None)
            for i, t in enumerate(["Read", "Edit", "Bash"])
        ),
        skill_invocations=(),
        compaction_lines=(),
    )
    findings = analyze.detect_tool_sequences([s1, s2])
    titles = {f["title"] for f in findings}
    assert "Read → Edit → Bash" in titles


def test_tool_sequence_skips_homogeneous() -> None:
    sess = analyze.SessionData(
        session_id="s1",
        project_path="p",
        file_path="",
        message_count=20,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=tuple(
            analyze.ToolCall("Read", "", i, False, None) for i in range(10)
        ),
        skill_invocations=(),
        compaction_lines=(),
    )
    findings = analyze.detect_tool_sequences([sess, sess])
    assert all("Read → Read → Read" not in f["title"] for f in findings)


def test_repeated_prompt_clusters() -> None:
    def mk(sid: str, *texts: str) -> analyze.SessionData:
        return analyze.SessionData(
            session_id=sid,
            project_path="p",
            file_path="",
            message_count=20,
            earliest=None,
            latest=None,
            user_messages=tuple(
                analyze.UserMessage(text=t, line_no=i, follows_skill=None)
                for i, t in enumerate(texts)
            ),
            tool_calls=(),
            skill_invocations=(),
            compaction_lines=(),
        )

    s1 = mk("s1", "review the dependency PRs", "review the dependency PRs")
    s2 = mk("s2", "review the dependency PRs")
    findings = analyze.detect_repeated_prompts([s1, s2])
    assert findings
    assert findings[0]["frequency"] == 3


def test_skill_unused_set_difference() -> None:
    inventory = {
        "alpha": analyze.SkillMeta("alpha", "", ()),
        "beta": analyze.SkillMeta("beta", "", ()),
    }
    sess = analyze.SessionData(
        session_id="s1",
        project_path="p",
        file_path="",
        message_count=10,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=(),
        skill_invocations=("alpha",),
        compaction_lines=(),
    )
    invoked, never, _ = analyze.detect_unused_skills([sess], inventory)
    assert invoked == {"alpha": 1}
    assert never == ["beta"]


def test_skill_unused_with_trigger_match() -> None:
    inventory = {
        "frob": analyze.SkillMeta(
            "frob",
            'Use when user says "frobnicate the widget"',
            ("frobnicate the widget",),
        ),
    }
    sess = analyze.SessionData(
        session_id="s1",
        project_path="p",
        file_path="",
        message_count=10,
        earliest=None,
        latest=None,
        user_messages=(
            analyze.UserMessage("please frobnicate the widget now", 1, None),
        ),
        tool_calls=(),
        skill_invocations=(),
        compaction_lines=(),
    )
    _, _, findings = analyze.detect_unused_skills([sess], inventory)
    assert len(findings) == 1
    assert findings[0]["details"]["skill"] == "frob"


def test_skill_negative_followup_threshold() -> None:
    sess1 = analyze.SessionData(
        session_id="s1",
        project_path="p",
        file_path="",
        message_count=10,
        earliest=None,
        latest=None,
        user_messages=(
            analyze.UserMessage("no, that's wrong", 1, "myskill"),
            analyze.UserMessage("undo this", 2, "myskill"),
        ),
        tool_calls=(),
        skill_invocations=("myskill",),
        compaction_lines=(),
    )
    findings = analyze.detect_skill_negative_followup([sess1])
    assert len(findings) == 1
    assert findings[0]["details"]["skill"] == "myskill"
    assert findings[0]["frequency"] == 2


def test_token_heavy_threshold() -> None:
    def mk(sid: str, count: int) -> analyze.SessionData:
        return analyze.SessionData(
            session_id=sid,
            project_path="p",
            file_path="",
            message_count=count,
            earliest=None,
            latest=None,
            user_messages=(),
            tool_calls=(),
            skill_invocations=(),
            compaction_lines=(),
        )

    sessions = [mk(f"s{i}", 50) for i in range(5)] + [mk("big", 500)]
    findings = analyze.detect_token_heavy(sessions)
    assert len(findings) == 1
    assert findings[0]["sessions"] == ["big"]


def test_rejection_storm_requires_same_tool_repeated() -> None:
    """A storm = one tool rejected ≥3 times, not 3 different tools rejected once."""
    sess_storm = analyze.SessionData(
        session_id="storm",
        project_path="p",
        file_path="",
        message_count=20,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=(
            analyze.ToolCall("Bash", "", 1, True, None),
            analyze.ToolCall("Bash", "", 2, True, None),
            analyze.ToolCall("Bash", "", 3, True, None),
            analyze.ToolCall("Read", "", 4, False, None),
        ),
        skill_invocations=(),
        compaction_lines=(),
    )
    sess_noise = analyze.SessionData(
        session_id="noise",
        project_path="p",
        file_path="",
        message_count=20,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=(
            analyze.ToolCall("Bash", "", 1, True, None),
            analyze.ToolCall("Write", "", 2, True, None),
            analyze.ToolCall("Edit", "", 3, True, None),
        ),
        skill_invocations=(),
        compaction_lines=(),
    )
    findings = analyze.detect_rejection_storms([sess_storm, sess_noise])
    assert len(findings) == 1
    assert findings[0]["sessions"] == ["storm"]
    assert findings[0]["details"]["worst_tool"] == "Bash"
    assert findings[0]["frequency"] == 3


def test_token_heavy_finding_carries_evidence_anchor() -> None:
    def mk(sid: str, count: int) -> analyze.SessionData:
        return analyze.SessionData(
            session_id=sid,
            project_path="proj-x",
            file_path="",
            message_count=count,
            earliest=None,
            latest=None,
            user_messages=(),
            tool_calls=(),
            skill_invocations=(),
            compaction_lines=(),
        )

    sessions = [mk(f"s{i}", 50) for i in range(5)] + [mk("big", 500)]
    findings = analyze.detect_token_heavy(sessions)
    anchor = findings[0]["evidence"]
    assert anchor, "token_heavy finding must carry a concrete evidence anchor"
    assert anchor[0]["session"] == "big"
    assert anchor[0]["project"] == "proj-x"
    assert anchor[0]["message_count"] == 500


def test_compaction_early_threshold() -> None:
    sess = analyze.SessionData(
        session_id="s1",
        project_path="p",
        file_path="",
        message_count=90,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=(),
        skill_invocations=(),
        compaction_lines=(15,),
    )
    findings = analyze.detect_compaction_early([sess])
    assert len(findings) == 1


def test_compaction_early_finding_carries_evidence_anchor() -> None:
    sess = analyze.SessionData(
        session_id="s1",
        project_path="proj-y",
        file_path="",
        message_count=90,
        earliest=None,
        latest=None,
        user_messages=(),
        tool_calls=(),
        skill_invocations=(),
        compaction_lines=(15,),
    )
    findings = analyze.detect_compaction_early([sess])
    anchor = findings[0]["evidence"]
    assert anchor, "compaction_early finding must carry a concrete evidence anchor"
    assert anchor[0]["session"] == "s1"
    assert anchor[0]["project"] == "proj-y"
    assert anchor[0]["message_count"] == 90


# -----------------------------------------------------------------------------
# Discovery / lookback tests
# -----------------------------------------------------------------------------


def test_session_filter_lookback(tmp_path: Path) -> None:
    old = tmp_path / "proj/old.jsonl"
    new = tmp_path / "proj/new.jsonl"
    _write_jsonl(
        old,
        [_user_text(f"prompt {i}", ts=_ago_iso(60)) for i in range(15)],
    )
    _write_jsonl(
        new,
        [_user_text(f"prompt {i}", ts=_now_iso()) for i in range(15)],
    )
    sessions, _ = analyze.discover_sessions(tmp_path, days=30)
    ids = {s.session_id for s in sessions}
    assert "new" in ids
    assert "old" not in ids


def test_session_filter_short(tmp_path: Path) -> None:
    short = tmp_path / "proj/short.jsonl"
    _write_jsonl(short, [_user_text("hi", ts=_now_iso())])
    sessions, skipped = analyze.discover_sessions(tmp_path, days=30)
    assert skipped == 1
    assert sessions == []


# -----------------------------------------------------------------------------
# End-to-end test
# -----------------------------------------------------------------------------


def test_full_pipeline_minimal_fixture(tmp_path: Path) -> None:
    claude_dir = tmp_path / "claude"
    projects = claude_dir / "projects"
    skills_dir = claude_dir / "skills"

    skill_dir = skills_dir / "review-deps-prs"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\n'
        'name: review-deps-prs\n'
        'description: >-\n'
        '  Use when triaging "review deps" or "dependency prs".\n'
        '---\n'
        '\n'
        'body\n'
    )

    p = projects / "proj"
    sess_a = p / "a.jsonl"
    sess_b = p / "b.jsonl"

    common_entries = [
        _user_text("review the dependency PRs across all repos"),
        _assistant_tool_use("Bash", {"command": "grep -r foo /tmp"}, "tu1"),
        _user_tool_result("tu1", "...", is_error=False),
        _assistant_tool_use("Read", {"file_path": "/tmp/x"}, "tu2"),
        _user_tool_result("tu2", "...", is_error=False),
        _assistant_tool_use("Bash", {"command": "cat /tmp/foo"}, "tu3"),
        _user_tool_result("tu3", "...", is_error=False),
        _user_text("now also check repo two"),
        _assistant_tool_use("Read", {"file_path": "/tmp/y"}, "tu4"),
        _user_tool_result("tu4", "...", is_error=False),
        _user_text("review the dependency PRs across all repos"),
    ]
    _write_jsonl(sess_a, common_entries)
    _write_jsonl(sess_b, common_entries)

    result = analyze.analyze(claude_dir, projects, days=30)

    assert result["scanned"]["sessions_total"] == 2
    assert result["scanned"]["projects"] == 1

    assert "review-deps-prs" in result["skill_usage"]["never_invoked"]

    rule_titles = {
        f["title"] for f in result["findings"] if f["category"] == "rule_violation"
    }
    assert any("Grep tool" in t for t in rule_titles)
    assert any("Read tool" in t for t in rule_titles)

    unused = [f for f in result["findings"] if f["category"] == "skill_unused"]
    assert any(f["details"]["skill"] == "review-deps-prs" for f in unused)

    rep = [f for f in result["findings"] if f["category"] == "repeated_prompt"]
    assert rep
    assert rep[0]["frequency"] >= 3


def test_skill_negative_not_in_skill_usage_top_level(tmp_path: Path) -> None:
    """skill_usage must not expose a 'negative_followup' key (R1).

    The canonical negative-followup data must still reach findings as a
    'skill_negative' category entry when ≥2 correction messages follow a
    skill invocation.
    """
    claude_dir = tmp_path / "claude"
    projects = claude_dir / "projects"
    p = projects / "proj"

    # 14-message session: enough to pass the min-message discovery filter.
    # Structure: preamble → Skill invocation → ≥2 correction user messages →
    # filler to pad message count.
    entries = [
        _user_text("let us start", ts=_now_iso(-130)),
        _user_text("some context", ts=_now_iso(-120)),
        _user_text("more context", ts=_now_iso(-110)),
        _user_text("invoke the skill", ts=_now_iso(-100)),
        _assistant_tool_use("Skill", {"skill": "myskill"}, "tu_neg_1", ts=_now_iso(-90)),
        _user_tool_result("tu_neg_1", "skill output", ts=_now_iso(-80)),
        # Correction message 1
        _user_text("no, that's wrong", ts=_now_iso(-70)),
        # Correction message 2
        _user_text("undo this", ts=_now_iso(-60)),
        _user_text("filler a", ts=_now_iso(-50)),
        _user_text("filler b", ts=_now_iso(-40)),
        _user_text("filler c", ts=_now_iso(-30)),
        _user_text("filler d", ts=_now_iso(-20)),
        _user_text("filler e", ts=_now_iso(-10)),
        _user_text("filler f", ts=_now_iso(0)),
    ]
    _write_jsonl(p / "sess_neg.jsonl", entries)

    result = analyze.analyze(claude_dir, projects, days=30)

    # R1-a: negative_followup must NOT appear as a top-level skill_usage key.
    assert "negative_followup" not in result["skill_usage"]

    # R1-b: the data must still surface in findings under category skill_negative.
    skill_negative_findings = [
        f for f in result["findings"] if f["category"] == "skill_negative"
    ]
    assert skill_negative_findings, "expected at least one skill_negative finding"
