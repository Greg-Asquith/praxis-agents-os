# apps/api/tests/services/agents/test_agent_schemas.py

"""Schema regression tests for agent service contracts."""

from datetime import UTC, datetime
from uuid import uuid4

from models.agent import Agent
from services.agents.schemas import AgentRead


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
        tool_names=["get_runtime_context"],
        tool_policies={"get_runtime_context": "approval"},
        skill_ids=[],
        allowed_agent_ids=[],
        model_provider="openai",
        model="gpt-5.4-mini",
        is_active=True,
        is_favorite=False,
        metadata_json={"accent": "green"},
        created_at=now,
        updated_at=now,
        deleted=False,
    )

    read_model = AgentRead.from_agent(agent)

    assert read_model.metadata_json == {"accent": "green"}
    assert read_model.model_dump(by_alias=True)["metadata"] == {"accent": "green"}
