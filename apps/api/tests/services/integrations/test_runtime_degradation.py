"""Disabled integration tools degrade saved agents without bricking runs."""

import logging
from uuid import uuid4

from models.agent import Agent
from models.agent_run import AgentRun
from services.agents.runtime.execute.setup import _record_skipped_runtime_tools
from services.agents.runtime.tools.registry import build_runtime_tools


def test_missing_saved_tool_is_skipped_and_logged(caplog, monkeypatch) -> None:
    runtime_logger = logging.getLogger("services.agents.runtime.tools.registry")
    monkeypatch.setattr(runtime_logger, "disabled", False)
    agent = Agent(
        id=uuid4(),
        name="Degraded agent",
        slug="degraded-agent",
        description="",
        instructions="Test",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=["gmail_removed_tool"],
        tool_policies={},
        skill_ids=[],
        allowed_agent_ids=[],
    )
    with caplog.at_level(
        logging.WARNING,
        logger="services.agents.runtime.tools.registry",
    ):
        skipped_tool_names = []
        tools = build_runtime_tools(agent, skipped_tool_names=skipped_tool_names)
    assert all(tool.name != "gmail_removed_tool" for tool in tools)
    assert skipped_tool_names == ["gmail_removed_tool"]
    assert "Skipping unavailable saved runtime tool gmail_removed_tool" in caplog.text


def test_skipped_tool_names_are_merged_into_run_metadata() -> None:
    run = AgentRun(metadata_json={"source": "test", "skipped_tool_names": ["old_tool"]})
    _record_skipped_runtime_tools(run, ["gmail_removed_tool", "old_tool"])
    assert run.metadata_json == {
        "source": "test",
        "skipped_tool_names": ["gmail_removed_tool", "old_tool"],
    }
