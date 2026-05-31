"""Tests for audit-filesystem checks: plugins, project orphans, memory."""

import json
import os
from datetime import datetime, timezone

import audit_filesystem
from checks_memory import check_memory, parse_index, parse_type
from checks_plugins import check_plugins
from checks_projects import check_projects
from disk import human_size

NOW = datetime(2026, 5, 31, tzinfo=timezone.utc)


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _set_age_days(path, days):
    ts = NOW.timestamp() - days * 86400
    os.utime(path, (ts, ts))


# --- plugins ---


def test_check_plugins_flags_stale_and_orphan(tmp_path):
    cache = tmp_path / "plugins" / "cache"
    (cache / "official" / "superpowers" / "5.0.6").mkdir(parents=True)
    (cache / "official" / "superpowers" / "5.1.0").mkdir(parents=True)
    (cache / "official" / "ghost" / "1.0.0").mkdir(parents=True)
    _write(tmp_path / "plugins" / "installed_plugins.json", json.dumps(
        {"plugins": {"superpowers@official": [{"version": "5.1.0"}]}}))

    titles = [f.title for f in check_plugins(tmp_path)]
    assert any("stale cached version superpowers 5.0.6" in t for t in titles)
    assert any("orphaned plugin cache 'ghost'" in t for t in titles)


# --- projects ---


def test_check_projects_orphan_dormant_and_unresolved(tmp_path):
    projects = tmp_path / "projects"
    _write(projects / "-orphan" / "sessions-index.json",
           json.dumps({"entries": [{"projectPath": "/definitely/not/here/xyz"}]}))
    _write(projects / "-dorm" / "sessions-index.json",
           json.dumps({"entries": [{"projectPath": str(tmp_path), "modified": "2026-01-01T00:00:00Z"}]}))
    (projects / "-zzz-nonexistent-xyz").mkdir(parents=True)

    findings = check_projects(tmp_path, NOW)
    assert any(f.severity == "LOW" and "orphan project config" in f.title for f in findings)
    assert any(f.severity == "INFO" and "dormant project" in f.title for f in findings)
    assert any(f.severity == "INFO" and "could not be resolved" in f.title for f in findings)
    # unresolved dir must never produce a guessed deletion command
    assert not any("rm -rf" in (f.fix or "") and "nonexistent" in (f.fix or "") for f in findings)


# --- memory ---


def test_parse_index_and_type():
    assert parse_index("- [Title](auth.md) — hook\n- [x](./sub/note.md)\nnot a list") == {"auth.md", "note.md"}
    assert parse_type("---\nname: x\nmetadata:\n  type: feedback\n---\nbody") == "feedback"
    assert parse_type("no frontmatter") is None


def test_check_memory_index_and_type(tmp_path):
    mem = tmp_path / "projects" / "-proj" / "memory"
    _write(mem / "MEMORY.md", "- [A](a.md) — x\n- [Gone](gone.md) — y\n")
    _write(mem / "a.md", "---\nname: a\nmetadata:\n  type: reference\n---\nbody")
    _write(mem / "b.md", "no frontmatter here")

    titles = [f.title for f in check_memory(tmp_path, NOW)]
    assert any("orphan index entry in -proj" in t and "gone.md" in t for t in titles)
    assert any("missing index entry in -proj" in t and "b.md" in t for t in titles)
    assert any("b.md: missing or unknown memory type" in t for t in titles)


def test_check_memory_stale_project_memory(tmp_path):
    mem = tmp_path / "projects" / "-proj" / "memory"
    _write(mem / "MEMORY.md", "- [Old](old.md) — x\n")
    old = mem / "old.md"
    _write(old, "---\nname: old\nmetadata:\n  type: project\n---\nbody")
    _set_age_days(old, 60)  # > 30d project window
    assert any("project memory is 60d old" in f.title for f in check_memory(tmp_path, NOW))


def test_check_memory_staleness_runs_without_index(tmp_path):
    # regression: a memory dir with no MEMORY.md still gets type/staleness checks
    mem = tmp_path / "projects" / "-proj" / "memory"
    old = mem / "old.md"
    _write(old, "---\nname: old\nmetadata:\n  type: project\n---\nbody")
    _set_age_days(old, 60)
    assert any("project memory is 60d old" in f.title for f in check_memory(tmp_path, NOW))


# --- integration ---


def test_run_reports_and_is_ordered(tmp_path):
    (tmp_path / "plugins" / "cache" / "official" / "ghost" / "1.0.0").mkdir(parents=True)
    _write(tmp_path / "plugins" / "installed_plugins.json", json.dumps({"plugins": {}}))
    result = audit_filesystem.run(tmp_path, NOW)
    assert result["audit"] == "filesystem"
    assert result["scanned"]["as_of"] == "2026-05-31"
    assert result["summary"]["LOW"] >= 1


def test_human_size_reads_cleanly():
    assert human_size(0) == "0B"
    assert human_size(2048) == "2.0KB"
