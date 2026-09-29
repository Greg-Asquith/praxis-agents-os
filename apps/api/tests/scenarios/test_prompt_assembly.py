# apps/api/tests/scenarios/test_prompt_assembly.py

"""System-prompt and skill-loading behavior at the scenario boundary."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from tests.factories import build_skill
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_core_memory_is_injected_but_notes_are_not(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    async with db_session_factory() as db:
        db.add_all(
            [
                _scenario_memory(
                    context,
                    title="Core preference",
                    kind="core",
                ),
                _scenario_memory(
                    context,
                    title="Search-only note",
                    kind="note",
                ),
            ]
        )
        await db.commit()
    seen = []

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["done"], seen_requests=seen),
    )

    assert result.run.status == "completed"
    request_text = str(seen[0][1])
    assert "Core preference" in request_text
    assert "Search-only note" not in request_text


async def test_unassigned_workspace_skill_loads_by_name_into_history(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    skill_name = await _add_workspace_skill(db_session_factory, context)
    seen = []
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("load_skill", {"name": skill_name}, "load-skill"),)),
            "done",
        ],
        seen_requests=seen,
    )

    result = await run_scenario(db_session_factory, context, model=model)

    assert result.run.status == "completed"
    assert len(seen) == 2
    assert "Follow the scenario workflow." in str(seen[1][0])


async def _add_workspace_skill(
    session_factory: async_sessionmaker[AsyncSession],
    context,
) -> str:
    async with session_factory() as db:
        workspace = await db.get(Workspace, context.workspace_id)
        user = await db.get(User, context.user_id)
        assert workspace is not None
        assert user is not None
        skill = build_skill(
            workspace=workspace,
            created_by=user,
            name=f"scenario-{uuid4().hex[:8]}",
            human_name="Scenario Skill",
            description="Scenario-specific guidance.",
            instructions="Follow the scenario workflow.",
        )
        db.add(skill)
        await db.commit()
        return skill.name


def _scenario_memory(context, *, title: str, kind: str) -> AgentMemory:
    return AgentMemory(
        workspace_id=context.workspace_id,
        scope="agent",
        agent_id=context.agent_id,
        kind=kind,
        memory_type="preference",
        title=title,
        content_md="Prefer concise operational answers.",
        importance=4,
        confidence=0.9,
        status="active",
        source="interactive",
        created_by="agent",
        created_by_user_id=context.user_id,
    )
