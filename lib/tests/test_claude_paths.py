"""Tests for path resolution: config dir, the lossy project-dir decoder, telemetry."""

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_paths import (
    STALENESS_DAYS,
    any_usage_telemetry,
    config_dir,
    decode_project_dir,
    iter_jsonl,
    last_session_date,
    resolve_project_path,
    telemetry_sources,
)


def test_config_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path


def test_config_dir_defaults_to_home_dotclaude(monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert config_dir() == Path.home() / ".claude"


def test_decode_simple_path():
    assert decode_project_dir("-Users-bob-git") == "/Users/bob/git"


def test_decode_keeps_double_slash_for_dot_segments():
    # `/.` encodes to `--`, decoding naively yields `//` which the resolver corrects.
    assert decode_project_dir("-Users-bob--claude") == "/Users/bob//claude"


def test_resolve_prefers_sessions_index(tmp_path):
    pdir = tmp_path / "-whatever"
    pdir.mkdir()
    (pdir / "sessions-index.json").write_text(
        json.dumps({"entries": [{"projectPath": "/real/path", "modified": "2026-05-01T00:00:00Z"}]})
    )
    got = resolve_project_path(pdir, exists=lambda _p: False)
    assert got.status == "RESOLVED"
    assert got.path == "/real/path"


def test_resolve_decodes_and_verifies(tmp_path):
    pdir = tmp_path / "-x-y"
    pdir.mkdir()
    got = resolve_project_path(pdir, exists=lambda p: p == "/x/y")
    assert got.status == "RESOLVED"
    assert got.path == "/x/y"


def test_resolve_applies_dot_prefix_correction(tmp_path):
    pdir = tmp_path / "-x--y"
    pdir.mkdir()
    got = resolve_project_path(pdir, exists=lambda p: p == "/x/.y")
    assert got.status == "RESOLVED"
    assert got.path == "/x/.y"


def test_resolve_never_returns_a_guessed_path(tmp_path):
    # The deletion-safety invariant: if nothing verifies, return UNRESOLVED, not a guess.
    pdir = tmp_path / "-x--y"
    pdir.mkdir()
    got = resolve_project_path(pdir, exists=lambda _p: False)
    assert got.status == "UNRESOLVED"
    assert got.path is None


def test_last_session_date_from_index(tmp_path):
    pdir = tmp_path / "-p"
    pdir.mkdir()
    (pdir / "sessions-index.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"modified": "2026-03-01T10:00:00Z"},
                    {"modified": "2026-05-20T10:00:00Z"},
                ]
            }
        )
    )
    got = last_session_date(pdir)
    assert got == datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc)


def test_iter_jsonl_skips_malformed_lines(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text('{"a": 1}\nnot json\n{"b": 2}\n')
    rows = list(iter_jsonl(f))
    assert rows == [{"a": 1}, {"b": 2}]


def test_telemetry_presence_detects_sources(tmp_path):
    assert any_usage_telemetry(tmp_path) is False
    (tmp_path / "instincts").mkdir()
    (tmp_path / "instincts" / "projects.json").write_text("{}")
    sources = telemetry_sources(tmp_path)
    assert sources["instincts"] is True
    assert sources["warden_audit"] is False
    assert any_usage_telemetry(tmp_path) is True


def test_decode_non_anchored_name():
    # A name without a leading dash is decoded relative (rare, but must not crash).
    assert decode_project_dir("x-y") == "x/y"


def test_resolve_falls_back_to_jsonl_cwd(tmp_path):
    pdir = tmp_path / "-unresolvable"
    pdir.mkdir()
    (pdir / "a.jsonl").write_text(json.dumps({"cwd": "/from/jsonl"}) + "\n")
    got = resolve_project_path(pdir, exists=lambda _p: False)
    assert got.status == "RESOLVED"
    assert got.path == "/from/jsonl"


def test_malformed_index_is_ignored(tmp_path):
    pdir = tmp_path / "-x-y"
    pdir.mkdir()
    (pdir / "sessions-index.json").write_text("{ not json")
    # Falls through to a verified decode rather than crashing on bad JSON.
    got = resolve_project_path(pdir, exists=lambda p: p == "/x/y")
    assert got.status == "RESOLVED"
    assert got.path == "/x/y"


def test_last_session_date_falls_back_to_jsonl_mtime(tmp_path):
    pdir = tmp_path / "-p"
    pdir.mkdir()
    (pdir / "s.jsonl").write_text("{}\n")
    got = last_session_date(pdir)
    assert got is not None
    assert got.tzinfo is timezone.utc


def test_last_session_date_unknown_when_empty(tmp_path):
    pdir = tmp_path / "-empty"
    pdir.mkdir()
    assert last_session_date(pdir) is None


def test_staleness_windows_documented():
    assert STALENESS_DAYS["permission"] == 30
    assert STALENESS_DAYS["project_orphan"] == 90
    assert STALENESS_DAYS["memory_project"] == 30
    assert STALENESS_DAYS["memory_user"] == 180
