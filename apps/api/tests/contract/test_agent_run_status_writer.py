# apps/api/tests/contract/test_agent_run_status_writer.py

"""Keeps transition_run_status the only writer of AgentRun.status."""

import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
# Packages that hold agent runs; other packages write their own models' status.
AGENT_RUN_PACKAGES = ("services/agent_runs", "services/agents", "services/conversations")
STATUS_WRITER = "services/agent_runs/utils.py"
STATUS_ASSIGNMENT = re.compile(r"\.status\s*=(?!=)")
BULK_STATUS_UPDATE = re.compile(r"update\(\s*AgentRun\s*\)[\s\S]{0,400}?\bstatus\s*=(?!=)")


def test_only_transition_run_status_writes_agent_run_status() -> None:
    offenders = []
    for path in sorted((API_ROOT / "services").rglob("*.py")):
        relative = path.relative_to(API_ROOT).as_posix()
        if relative == STATUS_WRITER:
            continue
        source = path.read_text(encoding="utf-8")
        direct = relative.startswith(AGENT_RUN_PACKAGES) and STATUS_ASSIGNMENT.search(source)
        if direct or BULK_STATUS_UPDATE.search(source):
            offenders.append(relative)
    assert offenders == []
