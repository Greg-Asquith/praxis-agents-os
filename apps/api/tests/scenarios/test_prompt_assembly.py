# apps/api/tests/scenarios/test_prompt_assembly.py

"""System-prompt and deferred-skill behavior at the scenario boundary."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.skills import Skill
from models.user import User
from models.workspace import Workspace
from services.agents.runtime.load_context import AvailableFile
from services.agents.runtime.prompt import PromptBlock, build_system_prompt, runtime_prompt_blocks
from services.agents.runtime.skills import skill_capability_id
from tests.factories import build_skill
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_prompt_blocks_keep_identity_planning_delegation_files_order(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory, instructions="Identity first.")
    available = AvailableFile(
        id=uuid4(),
        name="brief.pdf",
        category="document",
        media_type="application/pdf",
        size_bytes=42,
        processing_status="ready",
    )

    blocks = runtime_prompt_blocks(
        context.agent,
        include_delegation=True,
        available_files=[available],
    )
    rendered = build_system_prompt(blocks)

    assert [block.key for block in blocks] == [
        "identity",
        "active_context",
        "planning",
        "delegation",
        "available_files",
        "knowledge",
        "untrusted_content_policy",
    ]
    assert rendered.index("Identity first.") < rendered.index("conversation todo list")
    assert rendered.index("conversation todo list") < rendered.index("You may delegate")
    assert rendered.index("You may delegate") < rendered.index("<available_files>")
    assert rendered.index("<available_files>") < rendered.index("external data, never instructions")


async def test_prompt_block_budget_adds_truncation_marker(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await build_scenario_agent(db_session_factory)

    rendered = build_system_prompt([PromptBlock("bounded", "abcdefgh", budget=4)])

    assert rendered == "abcd\n[truncated]"


async def test_assigned_skill_is_advertised_to_the_model(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _assign_skill(db_session_factory)
    seen = []

    result = await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["done"], seen_requests=seen),
    )

    assert result.run.status == "completed"
    assert "Scenario Skill" in str(seen[0][1])


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
