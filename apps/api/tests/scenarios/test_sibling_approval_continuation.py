# apps/api/tests/scenarios/test_sibling_approval_continuation.py

"""Persisted sibling workflow decisions stay within each owning SDK history."""

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import select

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import ConversationMessage
from models.user import User
from models.workspace import Workspace
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.schemas import AgentRunResumeDecision
from services.agents.runtime.code_mode.executor import close_code_mode_executor
from services.agents.runtime.entity_references.domain import AgentReference
from services.agents.runtime.tools.contract import ToolFieldPresentation, ToolPresentation
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from tests.support.delegation import ScenarioEffects, resume_scenario, scenario_effects
from tests.support.scenario import add_scenario_delegate, build_scenario_agent, run_scenario


@pytest.fixture
def effects() -> Iterator[ScenarioEffects]:
    with scenario_effects() as probe:
        RUNTIME_TOOL_CATALOG[probe.name] = replace(
            RUNTIME_TOOL_CATALOG[probe.name],
            presentation=ToolPresentation(
                arg_fields=(ToolFieldPresentation(key="value", label="Value", editable=True),)
            ),
        )
        yield probe


@pytest.fixture
async def executor_cleanup() -> AsyncIterator[None]:
    try:
        yield
    finally:
        await close_code_mode_executor()


def sibling_model(
    child_ids: list[str], write_tool: str, *, workflow_code: str | None = None
) -> FunctionModel:
    async def stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        returns = {
            part.tool_name
            for message in messages
            for part in message.parts
            if part.part_kind == "tool-return"
        }
        if "list_delegate_agents" not in {tool.name for tool in info.function_tools}:
            if "run_workflow" not in returns:
                yield {
                    0: DeltaToolCall(
                        name="run_workflow",
                        json_args=json.dumps(
                            {
                                "code": workflow_code
                                or f"await {write_tool}(value='first')\n"
                                f"try:\n    await {write_tool}(value='second')\n"
                                "except PermissionError as exc:\n    print(str(exc))\n"
                                "'child workflow finished'"
                            }
                        ),
                        tool_call_id="shared-workflow",
                    )
                }
            else:
                yield "child result"
            return
        if "list_delegate_agents" not in returns:
            yield {
                0: DeltaToolCall(
                    name="list_delegate_agents", json_args="{}", tool_call_id="list-delegates"
                )
            }
        elif "delegate_to_agent" not in returns:
            yield {
                index: DeltaToolCall(
                    name="delegate_to_agent",
                    json_args=json.dumps(
                        {
                            "agent_id": AgentReference(
                                entity_id=child_id, label=f"Specialist {index}"
                            ).model_dump(mode="json"),
                            "task": "Run the workflow.",
                        }
                    ),
                    tool_call_id=f"delegate-{index}",
                )
                for index, child_id in enumerate(child_ids)
            }
        else:
            yield "parent final"

    return FunctionModel(stream_function=stream, model_name="sibling-workflow-scenario")


async def reload_approvals(session_factory, context):
    async with session_factory() as db:
        return await get_agent_run_approval_state(
            db,
            actor=await db.get(User, context.user_id),
            workspace=await db.get(Workspace, context.workspace_id),
            run_id=context.run_id,
        )


def assert_stream_matches_reload(result, projection):
    events = [event.data for event in result.events if event.event == "tool.approval_required"]
    assert {event["approval_id"] for event in events} == {
        str(leaf.approval_id) for leaf in projection.approvals
    }
    assert {event["owner_run_id"] for event in events} == {
        str(leaf.owner_run_id) for leaf in projection.approvals
    }
    assert {event["approval_revision"] for event in events} == {projection.approval_revision}
    assert [event.data["status"] for event in result.events if event.event == "done"] == [
        "awaiting_approval"
    ]


async def test_sibling_workflows_with_identical_native_ids_resume_exact_owner_decisions(
    committed_db_session_factory, monkeypatch, effects, executor_cleanup
):
    context = await build_scenario_agent(
        committed_db_session_factory,
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "require_approval"}},
    )
    children = [
        await add_scenario_delegate(
            committed_db_session_factory, context, tool_names=[effects.name]
        )
        for _ in range(2)
    ]
    async with committed_db_session_factory() as db:
        for child in children:
            saved = await db.get(Agent, child.id)
            saved.code_mode_enabled = True
        await db.commit()
    model = sibling_model([str(child.id) for child in children], effects.name)
    monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
    first = await run_scenario(committed_db_session_factory, context, model=model)
    assert first.run.status == "awaiting_approval"
    assert effects.calls == []
    projection = await reload_approvals(committed_db_session_factory, context)
    assert len(projection.workflows) == len(projection.approvals) == 2
    assert {leaf.tool_call_id for leaf in projection.approvals} == {"shared-workflow:1"}
    assert len({leaf.approval_id for leaf in projection.approvals}) == 2
    assert_stream_matches_reload(first, projection)
    owners = sorted((leaf.owner_run_id for leaf in projection.approvals), key=str)
    edited = {owner: f"edited first {index}" for index, owner in enumerate(owners)}
    await close_code_mode_executor()
    second = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(
                approval_id=leaf.approval_id,
                tool_call_id=leaf.tool_call_id,
                decision="approved",
                override_args={"value": edited[leaf.owner_run_id]},
            )
            for leaf in reversed(projection.approvals)
        ],
    )
    assert second.run.status == "awaiting_approval"
    assert sorted(effects.calls, key=lambda call: str(call[0])) == list(edited.items())
    first_effects = list(effects.calls)
    next_projection = await reload_approvals(committed_db_session_factory, context)
    assert len(next_projection.workflows) == len(next_projection.approvals) == 2
    assert {leaf.tool_call_id for leaf in next_projection.approvals} == {"shared-workflow:2"}
    assert next_projection.approval_revision != projection.approval_revision
    assert {leaf.approval_id for leaf in next_projection.approvals}.isdisjoint(
        leaf.approval_id for leaf in projection.approvals
    )
    assert_stream_matches_reload(second, next_projection)
    await close_code_mode_executor()
    completed = await resume_scenario(
        committed_db_session_factory,
        context,
        model=model,
        decisions=[
            AgentRunResumeDecision(
                approval_id=leaf.approval_id,
                tool_call_id=leaf.tool_call_id,
                decision="approved" if leaf.owner_run_id == owners[0] else "denied",
                override_args={"value": "edited second"}
                if leaf.owner_run_id == owners[0]
                else None,
                message="Skip this specialist's second action"
                if leaf.owner_run_id == owners[1]
                else None,
            )
            for leaf in reversed(next_projection.approvals)
        ],
    )
    assert completed.run.status == "completed"
    assert completed.output == "parent final"
    assert effects.calls == [*first_effects, (owners[0], "edited second")]
    assert len(completed.tool_returns("delegate_to_agent")) == 2
    assert [event.data["status"] for event in completed.events if event.event == "done"] == [
        "completed"
    ]
    async with committed_db_session_factory() as db:
        child_runs = list(
            await db.scalars(select(AgentRun).where(AgentRun.parent_run_id == context.run_id))
        )
        assert {run.id for run in child_runs} == set(owners)
        for run in child_runs:
            assert run.status == "completed"
            assert "code_mode_state" not in (run.metadata_json or {})
            assert "approval_state" not in (run.metadata_json or {})
            messages = await db.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == run.conversation_id
                )
            )
            transcript = json.dumps([message.parts for message in messages])
            assert "child workflow finished" in transcript
            if run.id == owners[1]:
                assert "Skip this specialist's second action" in transcript


@pytest.mark.parametrize("decision", ["approved", "denied"])
async def test_delegated_workflow_staged_content_and_taint_use_child_owner(
    committed_db_session_factory, monkeypatch, tmp_path, executor_cleanup, decision
):
    from core.exceptions.general import AppValidationError
    from core.settings import settings
    from models.files import File, FileRevision
    from services.agents.runtime.approval_state import load_suspended_run_state
    from services.agents.runtime.staged_tool_content import resolve_staged_write_content
    from services.agents.runtime.tools.contract import RuntimeToolDefinition
    from services.agents.runtime.untrusted import UntrustedContent
    from services.files.utils import private_ref_from_key
    from services.storage.errors import StorageNotFoundError
    from services.storage.factory import get_storage_provider
    from tests.support.storage import reset_storage_provider_cache

    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()

    async def read_content() -> UntrustedContent:
        return UntrustedContent(
            source_kind="scenario", source_ref="specialist-source", content="child file body"
        )

    tool = RuntimeToolDefinition(
        name="scenario_child_read_content",
        function=read_content,
        provider="test",
        description="Read untrusted scenario file content.",
        code_eligible=True,
        configurable=False,
    )
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, tool.name, tool)
    try:
        context = await build_scenario_agent(
            committed_db_session_factory,
            trigger="scheduled",
            metadata={"envelope": {"side_effect_policy": "allow"}},
        )
        child = await add_scenario_delegate(
            committed_db_session_factory, context, tool_names=[tool.name, "write_file"]
        )
        async with committed_db_session_factory() as db:
            saved = await db.get(Agent, child.id)
            saved.code_mode_enabled = True
            await db.commit()
        model = sibling_model(
            [str(child.id)],
            "write_file",
            workflow_code=f"item = await {tool.name}()\n"
            "try:\n"
            "    await write_file(name='specialist.md', content=item['content'])\n"
            "except PermissionError:\n    pass\n"
            "'child file workflow finished'",
        )
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        suspended = await run_scenario(committed_db_session_factory, context, model=model)
        assert suspended.run.status == "awaiting_approval"
        projection = await reload_approvals(committed_db_session_factory, context)
        assert_stream_matches_reload(suspended, projection)
        [leaf] = projection.approvals
        assert leaf.owner_run_id != context.run_id
        assert leaf.derived_from_untrusted is True
        assert leaf.taint_sources[0]["source_ref"] == "specialist-source"
        [event] = [
            event.data for event in suspended.events if event.event == "tool.approval_required"
        ]
        assert event["derived_from_untrusted"] is True
        assert event["taint_sources"] == leaf.taint_sources
        assert event["args"] == leaf.args
        assert leaf.args["content_bytes"] == len("child file body")
        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, leaf.owner_run_id)
            state = load_suspended_run_state(run)
            nested = state.deferred_tool_requests.metadata["shared-workflow"]["nested_args"]
            assert "content" not in nested
            content_ref = nested["content_ref"]
        assert (
            await resolve_staged_write_content(
                workspace_id=context.workspace_id,
                run_id=leaf.owner_run_id,
                content_ref=content_ref,
            )
            == "child file body"
        )
        with pytest.raises(AppValidationError):
            await resolve_staged_write_content(
                workspace_id=context.workspace_id,
                run_id=context.run_id,
                content_ref=content_ref,
            )
        await close_code_mode_executor()
        completed = await resume_scenario(
            committed_db_session_factory,
            context,
            model=model,
            decisions=[
                AgentRunResumeDecision(
                    approval_id=leaf.approval_id,
                    tool_call_id=leaf.tool_call_id,
                    decision=decision,
                    message="Skip the specialist file" if decision == "denied" else None,
                )
            ],
        )
        assert completed.run.status == "completed"
        with pytest.raises(StorageNotFoundError):
            await resolve_staged_write_content(
                workspace_id=context.workspace_id,
                run_id=leaf.owner_run_id,
                content_ref=content_ref,
            )
        async with committed_db_session_factory() as db:
            files = list(
                await db.scalars(select(File).where(File.workspace_id == context.workspace_id))
            )
            if decision == "approved":
                [stored] = files
                assert stored.name == "specialist.md"
                revision = await db.get(FileRevision, stored.current_revision_id)
                assert (
                    await get_storage_provider().get_object(
                        private_ref_from_key(revision.object_key)
                    )
                    == b"child file body"
                )
            else:
                assert files == []
            child_run = await db.get(AgentRun, leaf.owner_run_id)
            assert child_run.status == "completed"
            assert "code_mode_state" not in (child_run.metadata_json or {})
    finally:
        reset_storage_provider_cache()
