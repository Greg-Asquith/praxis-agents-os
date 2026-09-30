# apps/api/tests/scenarios/test_subagents.py

"""Sub-agent runs: parent-bounded tools and policies, approval bubbling, and resume."""

import json
from collections.abc import AsyncIterator, Iterator

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent import Agent
from models.agent_run import AgentRun
from services.agent_runs.continuation_state import AgentRunResumeRequiresRecoveryError
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.delegation.tool_names import DELEGATE_TO_AGENT_TOOL_NAME
from services.agents.runtime.subagents.constants import (
    RUN_SUBAGENT_TOOL_NAME,
    SUBAGENT_BLOCKED_TOOL_NAMES,
)
from tests.support.approvals import ScenarioDecision
from tests.support.delegation import ScenarioEffects, resume_scenario, scenario_effects
from tests.support.scenario import (
    add_scenario_delegate,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

ROLE = "Search term researcher"


@pytest.fixture
def effects() -> Iterator[ScenarioEffects]:
    with scenario_effects() as probe:
        yield probe


@pytest.mark.parametrize("revocation", [None, "disabled", "downgraded"])
async def test_subagent_approval_suspends_and_resumes_same_spec(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    effects: ScenarioEffects,
    revocation: str | None,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[effects.name],
        tool_policies={effects.name: "approval"},
        subagents_enabled=True,
    )
    await add_scenario_delegate(committed_db_session_factory, context)
    parent_tools: list[set[str]] = []
    child_tools: list[set[str]] = []
    child_prompts: list[str] = []
    model = _subagent_model(
        write_tool=effects.name,
        parent_tools=parent_tools,
        child_tools=child_tools,
        child_prompts=child_prompts,
    )
    resolved_models: list[str] = []

    def build(resolved):
        resolved_models.append(resolved.qualified_id)
        return model

    monkeypatch.setattr("services.agents.runtime.loop.build_model", build)

    result = await run_scenario(committed_db_session_factory, context, model=model)

    assert result.run.status == RUN_STATUS_AWAITING_APPROVAL
    [approval] = [event.data for event in result.events if event.event == "tool.approval_required"]
    assert (approval["tool_call_id"], approval["name"]) == ("child-write", effects.name)
    assert approval["delegation"]["child_agent_name"] == ROLE
    assert effects.calls == []
    # The parent's approval override holds, and the child has only the parent's tools, less the blocked ones.
    blocked = {RUN_SUBAGENT_TOOL_NAME, *SUBAGENT_BLOCKED_TOOL_NAMES}
    assert blocked <= parent_tools[0]
    assert effects.name in child_tools[0]
    assert child_tools[0] <= parent_tools[0] - blocked
    assert DELEGATE_TO_AGENT_TOOL_NAME in parent_tools[0]
    assert DELEGATE_TO_AGENT_TOOL_NAME not in child_tools[0]
    assert "Research search terms" in child_prompts[0]
    assert "You are a sub-agent" in child_prompts[0]
    # Only the child builds its model here; a powerful tier above the standard parent falls back.
    assert resolved_models == ["openai:gpt-6-luna"]
    async with committed_db_session_factory() as db:
        [child_run] = list(
            await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == context.run_id))
        )
        assert child_run.agent_id == context.agent_id
        assert child_run.metadata_json["subagent"]["role"] == ROLE
        assert child_run.metadata_json["subagent"]["model"] == "gpt-6-luna"

    if revocation is not None:
        async with committed_db_session_factory() as db:
            parent = await db.get(Agent, context.agent_id)
            if revocation == "disabled":
                parent.subagents_enabled = False
            else:
                # The saved standard-tier child now ranks above its light-tier parent.
                parent.model_provider, parent.model = "anthropic", "claude-haiku-4-5"
            await db.commit()
        with pytest.raises(AgentRunResumeRequiresRecoveryError):
            await resume_scenario(
                committed_db_session_factory,
                context,
                model=model,
                decisions=[ScenarioDecision(tool_call_id="child-write", decision="approved")],
            )
        assert effects.calls == []
        assert resolved_models == ["openai:gpt-6-luna"]
        async with committed_db_session_factory() as db:
            assert (await db.get(AgentRun, child_run.id)).status == "failed"
        return

    resumed = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[ScenarioDecision(tool_call_id="child-write", decision="approved")],
    )

    assert resumed.run.status == "completed"
    assert resumed.output == "parent final"
    assert effects.calls == [(child_run.id, "external")]
    [returned] = resumed.tool_returns(RUN_SUBAGENT_TOOL_NAME)
    assert "sub-agent result" in str(returned["content"])
    # The resumed child is rebuilt from the saved spec with the same tools and model.
    assert child_tools[-1] == child_tools[0]
    assert resolved_models == ["openai:gpt-6-luna", "openai:gpt-6-luna"]


async def test_agent_without_subagents_has_no_run_subagent_tool(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await build_scenario_agent(committed_db_session_factory)
    seen: list[tuple[list[ModelMessage], AgentInfo]] = []
    model = scripted_model(turns=["done"], seen_requests=seen)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)

    await run_scenario(committed_db_session_factory, context, model=model)

    [(_messages, info)] = seen
    assert RUN_SUBAGENT_TOOL_NAME not in {tool.name for tool in info.function_tools}


def _subagent_model(
    *,
    write_tool: str,
    parent_tools: list[set[str]],
    child_tools: list[set[str]],
    child_prompts: list[str],
) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        names = {tool.name for tool in info.function_tools}
        if RUN_SUBAGENT_TOOL_NAME not in names:
            child_tools.append(names)
            child_prompts.append(str(info.instructions))
            if not _has_return(messages, write_tool):
                yield {
                    0: DeltaToolCall(
                        name=write_tool,
                        json_args=json.dumps({"value": "external"}),
                        tool_call_id="child-write",
                    )
                }
                return
            yield "sub-agent result"
            return
        parent_tools.append(names)
        if not _has_return(messages, RUN_SUBAGENT_TOOL_NAME):
            yield {
                0: DeltaToolCall(
                    name=RUN_SUBAGENT_TOOL_NAME,
                    json_args=json.dumps(
                        {
                            "role": ROLE,
                            "instructions": "Research search terms. Answer concisely.",
                            "task": "Find three search terms.",
                            "model_tier": "powerful",
                        }
                    ),
                    tool_call_id="spawn-subagent",
                )
            }
            return
        yield "parent final"

    return FunctionModel(stream_function=stream, model_name="scenario-subagent")


def _has_return(messages: list[ModelMessage], tool_name: str) -> bool:
    return any(
        getattr(part, "part_kind", None) == "tool-return"
        and getattr(part, "tool_name", None) == tool_name
        for message in messages
        for part in message.parts
    )
