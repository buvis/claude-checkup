"""Integration tests for audit_config.run(): aggregation, ordering, determinism."""

import json

import audit_config


def test_run_aggregates_sorts_and_is_deterministic(tmp_path):
    config = tmp_path / "claude"
    config.mkdir()
    (config / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(*)"]}}))
    project = tmp_path / "repo"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text(json.dumps({"typo_key": 1}))

    result = audit_config.run(config, project)

    assert result["audit"] == "config"
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    sevs = [f["severity"] for f in result["findings"]]
    assert sevs == sorted(sevs, key=order.index)  # most urgent first
    assert result["summary"]["CRITICAL"] >= 1
    assert any(f["severity"] == "INFO" for f in result["findings"])  # telemetry-absent note
    assert audit_config.run(config, project) == result  # same input -> same output


def test_run_with_nothing_to_scan_is_empty(tmp_path):
    result = audit_config.run(tmp_path / "absent", tmp_path / "absent")
    assert result["findings"] == []
    assert result["summary"]["CRITICAL"] == 0
