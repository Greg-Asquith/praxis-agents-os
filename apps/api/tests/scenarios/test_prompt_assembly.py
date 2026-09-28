# apps/api/tests/scenarios/test_prompt_assembly.py

"""System-prompt and deferred-skill behavior at the scenario boundary."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_memories import AgentMemory
from models.skills import Skill
from models.user import User
from models.workspace import Workspace
from services.agents.runtime.skills import skill_capability_id
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


async def test_loaded_skill_instructions_are_injected_after_load_capability(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _assign_skill(db_session_factory)
    async with db_session_factory() as db:
        skill = await db.get(Skill, context.agent.skill_ids[0])
        assert skill is not None
    seen = []
    model = scripted_model(
        turns=[
            ToolTurn(
                (ToolCall("load_capability", {"id": skill_capability_id(skill)}, "load-skill"),)
            ),
            "done",
        ],
        seen_requests=seen,
    )

    result = await run_scenario(db_session_factory, context, model=model)

    assert result.run.status == "completed"
    assert len(seen) == 2
    assert "Follow the scenario workflow." in str(seen[1][0])


async def _assign_skill(
    session_factory: async_sessionmaker[AsyncSession],
):
    context = await build_scenario_agent(session_factory)
    async with session_factory() as db:
        agent = await db.get(type(context.agent), context.agent_id)
        workspace = await db.get(Workspace, context.workspace_id)
        user = await db.get(User, context.user_id)
        assert agent is not None
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
        await db.flush()
        agent.skill_ids = [str(skill.id)]
        await db.commit()
        context.agent.skill_ids = [str(skill.id)]
    return context


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
