# apps/api/tests/scenarios/test_prompt_assembly.py

"""Prompt, memory recall, and skill-loading behaviour at the scenario boundary."""

from dataclasses import replace
from uuid import uuid4

from pydantic_ai.messages import ModelRequest, TextContent, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.agents.runtime.persistence import load_message_history
from tests.factories import build_skill
from tests.factories.conversations import build_conversation
from tests.support.scenario import (
    ScenarioContext,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
    run_scenario,
    scripted_model,
)


async def test_a_saved_memory_comes_up_in_the_next_conversation_when_relevant(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    save = ToolCall(
        "save_memory",
        {"title": "Invoice day", "content": "Invoices go out on the last Friday of each month."},
        "save-invoice-day",
    )
    first = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=[ToolTurn((save,)), "Saved."]),
        prompt="Remember that invoices go out on the last Friday of each month.",
    )
    assert first.run.status == "completed"
    async with db_session_factory() as db:
        db.add(_scenario_memory(context, title="Logo usage"))
        await db.commit()
    second_context = await _next_conversation(db_session_factory, context)
    seen = []

    second = await run_scenario(
        db_session_factory,
        second_context,
        model=scripted_model(turns=["The last Friday."], seen_requests=seen),
        prompt="When do invoices go out each month?",
    )

    assert second.run.status == "completed"
    sent = _last_prompt(seen[0][0])
    assert "last Friday" not in str(seen[0][1].instructions)
    recalled = [item for item in sent.content if isinstance(item, TextContent)]
    assert len(recalled) == 1
    assert "last Friday of each month" in recalled[0].content
    assert "Logo usage" not in recalled[0].content
    # The stored turn is the request the model saw, so a replay sends the same bytes.
    async with db_session_factory() as db:
        history = await load_message_history(db, conversation_id=second_context.conversation_id)
    assert _last_prompt(history[:1]).content == sent.content

    follow_up = await next_scenario_run(db_session_factory, second_context)
    later_seen = []
    await run_scenario(
        db_session_factory,
        follow_up,
        model=scripted_model(turns=["Still Friday."], seen_requests=later_seen),
        prompt="And when do invoices go out in December?",
    )

    assert _last_prompt(later_seen[0][0][:1]).content == sent.content
    assert _last_prompt(later_seen[0][0]).content == "And when do invoices go out in December?"


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


def _scenario_memory(context, *, title: str) -> AgentMemory:
    return AgentMemory(
        workspace_id=context.workspace_id,
        scope="agent",
        agent_id=context.agent_id,
        memory_type="preference",
        title=title,
        content_md="Use the dark logo on light backgrounds.",
        importance=4,
        confidence=0.9,
        status="active",
        source="interactive",
        created_by="agent",
        created_by_user_id=context.user_id,
    )


async def _next_conversation(
    session_factory: async_sessionmaker[AsyncSession], context
) -> ScenarioContext:
    async with session_factory() as db:
        user = await db.get(User, context.user_id)
        workspace = await db.get(Workspace, context.workspace_id)
        conversation = build_conversation(
            user=user, workspace=workspace, active_agent_id=context.agent_id
        )
        db.add(conversation)
        await db.flush()
        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=context.agent_id,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            trigger="interactive",
        )
        await db.commit()
    return replace(context, conversation_id=conversation.id, run_id=run.id)


def _last_prompt(messages) -> UserPromptPart:
    request = next(m for m in reversed(messages) if isinstance(m, ModelRequest))
    return next(part for part in request.parts if isinstance(part, UserPromptPart))
