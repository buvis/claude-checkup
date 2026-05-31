"""Tests for the shared Finding model: validation, ordering, and location rendering."""

import dataclasses

import pytest

from findings import Finding, location, severity_rank, sort_findings, to_dict


def test_rejects_unknown_severity():
    with pytest.raises(ValueError):
        Finding(severity="URGENT", title="x")


def test_finding_is_immutable():
    f = Finding(severity="LOW", title="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.title = "y"


def test_sort_orders_by_severity_then_title():
    findings = [
        Finding(severity="LOW", title="b"),
        Finding(severity="CRITICAL", title="z"),
        Finding(severity="HIGH", title="a"),
        Finding(severity="CRITICAL", title="a"),
    ]
    ordered = [(f.severity, f.title) for f in sort_findings(findings)]
    assert ordered == [
        ("CRITICAL", "a"),
        ("CRITICAL", "z"),
        ("HIGH", "a"),
        ("LOW", "b"),
    ]


def test_severity_rank_is_monotonic():
    assert severity_rank("CRITICAL") < severity_rank("HIGH") < severity_rank("LOW")


def test_location_omits_none_line():
    # The historic scan.py bug rendered "settings.json:None". location() must not.
    assert location(Finding(severity="LOW", title="x", file="settings.json")) == "settings.json"
    assert location(Finding(severity="LOW", title="x")) == ""
    assert (
        location(Finding(severity="LOW", title="x", file="settings.json", line=12))
        == "settings.json:12"
    )


def test_to_dict_carries_all_fields():
    d = to_dict(Finding(severity="HIGH", title="t", fix="f", file="a.json", line=3, audit="config"))
    assert d == {
        "severity": "HIGH",
        "title": "t",
        "fix": "f",
        "file": "a.json",
        "line": 3,
        "audit": "config",
    }
