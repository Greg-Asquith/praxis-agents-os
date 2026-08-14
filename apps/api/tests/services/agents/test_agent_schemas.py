# apps/api/tests/services/agents/test_agent_schemas.py

"""Schema regression tests for agent service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from models.agent import Agent
from services.agents.schemas import AgentCreateRequest, AgentRead, AgentUpdateRequest


def test_code_mode_is_disabled_by_default_and_rejects_null_updates() -> None:
    assert AgentCreateRequest(name="Agent", instructions="Work.").code_mode_enabled is False

    with pytest.raises(ValidationError):
        AgentUpdateRequest.model_validate({"code_mode_enabled": None})


def test_agent_read_validates_metadata_from_orm_attribute() -> None:
    """The public metadata alias must not read SQLAlchemy's MetaData registry."""
    now = datetime.now(UTC)
    agent = Agent(
        id=uuid4(),
        name="Research Agent",
        slug="research-agent",
        instructions="Answer carefully.",
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=["test_runtime_context"],
        tool_policies={"test_runtime_context": "approval"},
        skill_ids=[],
        allowed_agent_ids=[],
        model_provider="openai",
        model="gpt-5.4-mini",
        is_active=True,
        is_favorite=False,
        code_mode_enabled=False,
        metadata_json={"accent": "green"},
        created_at=now,
        updated_at=now,
        deleted=False,
    )

    read_model = AgentRead.from_agent(agent)

    assert read_model.metadata_json == {"accent": "green"}
    assert read_model.code_mode_enabled is False
    assert read_model.model_dump(by_alias=True)["metadata"] == {"accent": "green"}
