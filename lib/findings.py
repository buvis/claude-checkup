"""Shared finding model used by every scripted audit.

A Finding is an immutable record an audit emits. The orchestrator aggregates
findings from all audits into one severity-ranked report, so the shape and the
severity vocabulary live here once rather than in each skill's prose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
_SEV_RANK = {sev: i for i, sev in enumerate(SEVERITIES)}


@dataclass(frozen=True)
class Finding:
    severity: str
    title: str
    fix: str = ""
    file: str | None = None
    line: int | None = None
    audit: str = ""

    def __post_init__(self) -> None:
        if self.severity not in _SEV_RANK:
            raise ValueError(
                f"invalid severity {self.severity!r}; expected one of {SEVERITIES}"
            )


def severity_rank(severity: str) -> int:
    """Lower rank = more urgent. CRITICAL is 0."""
    return _SEV_RANK[severity]


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Most urgent first, then alphabetical by title for stable output."""
    return sorted(findings, key=lambda f: (severity_rank(f.severity), f.title))


def location(finding: Finding) -> str:
    """Render `file:line`, `file`, or `` -- never the historic `file:None`."""
    if finding.file and finding.line is not None:
        return f"{finding.file}:{finding.line}"
    if finding.file:
        return finding.file
    return ""


def to_dict(finding: Finding) -> dict:
    return asdict(finding)
