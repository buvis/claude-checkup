#!/usr/bin/env python3
"""Audit ~/.claude filesystem hygiene: plugin caches, project orphans, memory.

Walks the config tree once and emits a single JSON report of Findings. Replaces
the old audit-plugins/project-orphans/memory skills. Deterministic given a fixed
clock; the clock is the only non-pure input (passed as `now`).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap shared lib + sibling modules; fail loud if the shared lib is gone.
_SCRIPTS = Path(__file__).resolve().parent
_LIB = _SCRIPTS.parents[2] / "lib"
if not _LIB.is_dir():
    sys.exit(f"claude-checkup: shared lib not found at {_LIB}")
for _entry in (str(_LIB), str(_SCRIPTS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)


def run(config: Path, now: datetime) -> dict:
    from checks_memory import check_memory
    from checks_plugins import check_plugins
    from checks_projects import check_projects
    from findings import SEVERITIES, sort_findings, to_dict

    findings = check_plugins(config) + check_projects(config, now) + check_memory(config, now)
    ordered = sort_findings(findings)
    summary = {sev: sum(1 for f in ordered if f.severity == sev) for sev in SEVERITIES}
    return {
        "audit": "filesystem",
        "scanned": {"config_dir": str(config), "as_of": now.date().isoformat()},
        "findings": [to_dict(f) for f in ordered],
        "summary": summary,
    }


def main() -> int:
    from claude_paths import config_dir

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config-dir", type=Path, default=config_dir(),
                        help="Claude config dir (default: $CLAUDE_CONFIG_DIR or ~/.claude)")
    args = parser.parse_args()
    json.dump(run(args.config_dir, datetime.now(timezone.utc)), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
