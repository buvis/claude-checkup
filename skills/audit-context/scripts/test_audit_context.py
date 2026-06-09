"""Tests for audit_context.run(): classification, totals, settings exclusion."""

import json
from pathlib import Path

import audit_context


def _skill(skills_dir: Path, name: str, desc_words: int, body_words: int) -> None:
    fm = f"---\nname: {name}\ndescription: {' '.join(['w'] * desc_words)}\n---\n"
    body = " ".join(["b"] * body_words)
    path = skills_dir / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(fm + body)


def test_run_classifies_totals_and_excludes_settings(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("alpha beta gamma")
    (tmp_path / "settings.json").write_text('{"x": "' + "y" * 5000 + '"}')  # must be ignored
    _skill(tmp_path / "skills", "foo", desc_words=4, body_words=100)

    res = audit_context.run(tmp_path, mcp_tools=10, window=100_000)

    labels = [c["label"] for c in res["components"]]
    assert not any("settings.json" in label for label in labels)  # not context overhead

    mcp = next(c for c in res["components"] if c["kind"] == "mcp")
    assert mcp["tokens"] == 500 and mcp["classification"] == "always_loaded"

    body = next(c for c in res["components"] if c["label"] == "skill:foo (body)")
    assert body["classification"] == "on_demand"

    snippet = next(c for c in res["components"] if c["label"] == "skill:foo")
    assert snippet["classification"] == "always_loaded"

    assert res["totals"]["always_loaded"] >= 500
    assert res["pct_of_window"] == round(
        100 * res["totals"]["loaded_overhead"] / 100_000, 1)


def test_plugin_agent_description_is_hidden_tax(tmp_path):
    cache = tmp_path / "plugins" / "cache" / "official" / "p" / "1.0.0"
    (cache / "agents").mkdir(parents=True)
    (cache / "agents" / "a.md").write_text("---\nname: a\ndescription: d d d\n---\nbody body")
    (tmp_path / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"p@official": [{"version": "1.0.0"}]}}))

    res = audit_context.run(tmp_path, mcp_tools=0, window=200_000)
    agent = next(c for c in res["components"] if c["label"] == "p:a")
    assert agent["classification"] == "hidden_tax"


def test_run_scans_project_memory_and_plugin_command(tmp_path):
    proj = tmp_path / "projects" / "-proj"
    (proj).mkdir(parents=True)
    (proj / "CLAUDE.md").write_text("project memory words here")
    (proj / "memory").mkdir()
    (proj / "memory" / "note.md").write_text("some memory content")
    cache = tmp_path / "plugins" / "cache" / "mp" / "pl" / "1.0.0"
    (cache / "commands").mkdir(parents=True)
    (cache / "commands" / "do.md").write_text("---\nname: do\ndescription: d\n---\nbody words")
    (cache / "skills" / "s").mkdir(parents=True)
    (cache / "skills" / "s" / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody")
    (tmp_path / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"pl@mp": [{"version": "1.0.0"}]}}))

    labels = [c["label"] for c in audit_context.run(tmp_path, 0, 200_000)["components"]]
    assert any("-proj/CLAUDE.md" in label for label in labels)
    assert any("-proj/memory/note.md" in label for label in labels)
    assert "pl:do" in labels  # plugin command snippet
    assert "pl:s" in labels  # plugin skill snippet


def test_empty_config_is_clean(tmp_path):
    res = audit_context.run(tmp_path, mcp_tools=0, window=200_000)
    assert res["components"] == []
    assert res["totals"]["loaded_overhead"] == 0
    assert res["pct_of_window"] == 0.0


def test_unclosed_fence_counts_words_as_frontmatter_not_zero(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text("---\nname: foo\ndescription: a b c d\n")  # no closing ---

    frontmatter_words, body_words = audit_context._split_frontmatter(p)

    assert frontmatter_words > 0, (
        "malformed (unclosed-fence) file must not be silently zeroed; "
        "its words must count toward always-loaded budget"
    )
    assert body_words == 0, (
        "unclosed fence absorbs entire file as frontmatter; body must be zero"
    )
    assert frontmatter_words == len(p.read_text().split()), (
        "no words must be dropped: every word in the file counts toward always-loaded overhead"
    )


def test_closed_fence_splits_frontmatter_from_body(tmp_path):
    # control for the over-count fix: a well-formed file must still split so the
    # body is not folded into frontmatter (kills an all-frontmatter shortcut).
    good = tmp_path / "good.md"
    good.write_text("---\nname: foo\ndescription: a b c\n---\nbody word one two three\n")
    fm, body = audit_context._split_frontmatter(good)
    assert fm > 0
    assert body > 0
