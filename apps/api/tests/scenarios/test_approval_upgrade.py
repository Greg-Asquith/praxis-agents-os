"""Qualifies historical consent and interpreter state across runtime replacement."""

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agent_runs.reap_abandoned import reap_abandoned_runs
from services.agent_runs.resume_run_stream import resume_agent_run_stream
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime.code_mode.executor import close_code_mode_executor
from services.agents.runtime.code_mode.state import CodeModeResumeRequiresRecoveryError
from services.agents.runtime.run_manager import run_task_registry
from tests.support.approval_fixtures import restore_approval_fixture
from tests.support.delegation import resume_scenario, scenario_effects
from tests.support.scenario import scripted_model


@pytest.mark.parametrize("fixture", ["direct", "workflow", "workflow-second", "delegated"])
@pytest.mark.parametrize("decision", ["approved", "denied"])
async def test_saved_v1_approvals_resume_without_repeating_completed_effects(
    committed_db_session_factory, monkeypatch, fixture, decision
):
    factory = committed_db_session_factory
    with scenario_effects(name="scenario_release_write") as effects:
        context = await restore_approval_fixture(factory, fixture)
        model = scripted_model(turns=["Specialist finished.", "Finished."])
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        identities = []
        requires_recovery = fixture == "workflow-second" and decision == "denied"
        expected_status = "failed" if requires_recovery else "completed"
        try:
            for _ in range(2):
                async with factory() as db:
                    projection = await get_agent_run_approval_state(
                        db,
                        actor=await db.get(User, context.user_id),
                        workspace=await db.get(Workspace, context.workspace_id),
                        run_id=context.run_id,
                    )
                    [leaf] = projection.approvals
                    identities.append(leaf.approval_id)
                await close_code_mode_executor()
                with (
                    pytest.raises(CodeModeResumeRequiresRecoveryError)
                    if requires_recovery
                    else nullcontext()
                ):
                    await resume_scenario(
                        factory,
                        context,
                        model=model,
                        decisions=[
                            AgentRunResumeDecision(
                                tool_call_id=leaf.tool_call_id,
                                approval_id=leaf.approval_id,
                                decision=decision,
                            )
                        ],
                    )
                async with factory() as db:
                    resumed_run = await db.get(AgentRun, context.run_id)
                if resumed_run.status == expected_status:
                    break
                assert resumed_run.status == "awaiting_approval"
            assert resumed_run.status == expected_status
            if requires_recovery:
                assert resumed_run.outcome == "blocked"
                assert resumed_run.error_code == "agent_run_resume_requires_recovery"
                assert {
                    action["tool_call_id"]
                    for action in resumed_run.completion_json["recovery"]["actions"]
                    if action["status"] == "completed"
                } == {"workflow:1"}
            expected = (
                ["second"]
                if fixture == "workflow-second"
                else (["first"] if fixture == "direct" else ["first", "second"])
            )
            assert [value for _, value in effects.calls] == (
                expected if decision == "approved" else []
            )
            assert len(set(identities)) == len(identities)
            async with factory() as db:
                runs = list(
                    await db.scalars(
                        select(AgentRun).where(
                            (AgentRun.id == context.run_id)
                            | (AgentRun.parent_run_id == context.run_id)
                        )
                    )
                )
                assert all(run.status == expected_status for run in runs)
                assert all("approval_state" not in run.metadata_json for run in runs)
                owner = (
                    next(run for run in runs if run.parent_run_id)
                    if fixture == "delegated"
                    else runs[0]
                )
                assert {run_id for run_id, _ in effects.calls} == (
                    {owner.id} if decision == "approved" else set()
                )
        finally:
            await close_code_mode_executor()


@pytest.mark.parametrize("fixture", ["direct", "workflow-second", "delegated"])
async def test_old_accepted_but_unexecuted_continuation_requires_blocked_recovery(
    committed_db_session_factory, monkeypatch, fixture
):
    factory = committed_db_session_factory
    with scenario_effects(name="scenario_release_write") as effects:
        context = await restore_approval_fixture(factory, fixture)
        monkeypatch.setattr(
            run_task_registry, "spawn", lambda *_args, **_kwargs: pytest.fail("Unexpected replay")
        )
        async with factory() as db:
            root = await db.get(AgentRun, context.run_id)
            # Old acceptance committed running state but kept decisions only in memory.
            root.status = "running"
            root.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
        async with factory() as db:
            await reap_abandoned_runs(db, run_id=context.run_id)
            await db.commit()
            root = await db.get(AgentRun, context.run_id)
            assert root.outcome == "blocked"
            assert root.error_code == "agent_run_resume_requires_recovery"
            evidence = deepcopy(root.completion_json)
            actions = evidence["recovery"]["actions"]
            assert any(action["status"] == "uncertain" for action in actions)
            if fixture == "workflow-second":
                assert any(
                    action["tool_call_id"] == "workflow:1" and action["status"] == "completed"
                    for action in actions
                )
            assert "approval_state" not in root.metadata_json
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            with pytest.raises(ConflictError):
                await resume_agent_run_stream(
                    db,
                    actor=actor,
                    workspace=workspace,
                    run_id=root.id,
                    payload=AgentRunResumeRequest(
                        decisions=[
                            AgentRunResumeDecision(tool_call_id="write", decision="approved")
                        ]
                    ),
                )
            await db.rollback()
        async with factory() as db:
            root = await db.get(AgentRun, context.run_id)
            assert root.completion_json == evidence
        assert effects.calls == []


@pytest.mark.parametrize("decision", ["approved", "denied"])
async def test_saved_staged_workflow_preserves_content_and_consent(
    committed_db_session_factory, monkeypatch, tmp_path, decision
):
    from core.settings import settings
    from models.files import File, FileRevision
    from services.agents.runtime.approval_state import load_suspended_run_state
    from services.agents.runtime.staged_tool_content import resolve_staged_write_content
    from services.files.utils import private_ref_from_key
    from services.storage.errors import StorageNotFoundError
    from services.storage.factory import get_storage_provider
    from tests.support.storage import reset_storage_provider_cache

    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    reset_storage_provider_cache()
    factory = committed_db_session_factory
    try:
        context = await restore_approval_fixture(factory, "staged")
        async with factory() as db:
            run = await db.get(AgentRun, context.run_id)
            state = load_suspended_run_state(run)
            metadata = state.deferred_tool_requests.metadata["workflow"]
            content_ref = metadata["nested_args"]["content_ref"]
            assert "content" not in metadata["nested_args"]
            projection = await get_agent_run_approval_state(
                db,
                actor=await db.get(User, context.user_id),
                workspace=await db.get(Workspace, context.workspace_id),
                run_id=run.id,
            )
        provider = get_storage_provider()
        await provider.put_object(
            private_ref_from_key(content_ref), b"nested body", content_type="text/plain"
        )
        assert (
            await resolve_staged_write_content(
                workspace_id=context.workspace_id, run_id=context.run_id, content_ref=content_ref
            )
            == "nested body"
        )
        [leaf] = projection.approvals
        assert leaf.args["content_bytes"] == len(b"nested body")
        model = scripted_model(turns=["Finished."])
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        await close_code_mode_executor()
        result = await resume_scenario(
            factory,
            context,
            model=model,
            decisions=[
                AgentRunResumeDecision(
                    approval_id=leaf.approval_id,
                    tool_call_id=leaf.tool_call_id,
                    decision=decision,
                )
            ],
        )
        assert result.run.status == "completed"
        async with factory() as db:
            files = list(
                await db.scalars(select(File).where(File.workspace_id == context.workspace_id))
            )
            assert len(files) == (1 if decision == "approved" else 0)
            if files:
                revision = await db.scalar(
                    select(FileRevision).where(FileRevision.file_id == files[0].id)
                )
                assert (
                    await provider.get_object(private_ref_from_key(revision.object_key))
                    == b"nested body"
                )
        with pytest.raises(StorageNotFoundError):
            await resolve_staged_write_content(
                workspace_id=context.workspace_id, run_id=context.run_id, content_ref=content_ref
            )
    finally:
        await close_code_mode_executor()
        reset_storage_provider_cache()


@pytest.mark.parametrize(
    "fault",
    ["old_tab", "duplicate_native", "unsupported_version", "stale_revision", "terminal_child"],
)
async def test_legacy_upgrade_rejects_unverifiable_decisions_before_execution(
    committed_db_session_factory, monkeypatch, fault
):
    from uuid import uuid4

    factory = committed_db_session_factory
    fixture = "delegated" if fault == "terminal_child" else "direct"
    with scenario_effects(name="scenario_release_write") as effects:
        context = await restore_approval_fixture(factory, fixture)
        monkeypatch.setattr(
            run_task_registry,
            "spawn",
            lambda *_args, **_kwargs: pytest.fail("Unexpected continuation"),
        )
        async with factory() as db:
            actor = await db.get(User, context.user_id)
            workspace = await db.get(Workspace, context.workspace_id)
            projection = await get_agent_run_approval_state(
                db, actor=actor, workspace=workspace, run_id=context.run_id
            )
            root = await db.get(AgentRun, context.run_id)
            metadata = deepcopy(root.metadata_json)
            state = metadata["approval_state"]
            if fault == "old_tab":
                state["approval_batch_id"] = str(uuid4())
            elif fault == "duplicate_native":
                response = next(
                    message for message in state["message_history"] if message["kind"] == "response"
                )
                response["parts"].append(deepcopy(response["parts"][0]))
            elif fault == "unsupported_version":
                state["version"] = 999
            elif fault == "terminal_child":
                child = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
                child.status = "completed"
            root.metadata_json = metadata
            await db.commit()
            payload = AgentRunResumeRequest(
                decisions=[
                    AgentRunResumeDecision(
                        tool_call_id=projection.approvals[0].tool_call_id, decision="approved"
                    )
                ]
            )
            if fault == "stale_revision":
                payload.approval_revision = "unsupported-revision"
                payload.decisions[0].approval_id = projection.approvals[0].approval_id
            with pytest.raises(ConflictError) as error:
                await resume_agent_run_stream(
                    db, actor=actor, workspace=workspace, run_id=root.id, payload=payload
                )
            if fault in {"old_tab", "duplicate_native", "stale_revision"}:
                assert error.value.details["error_code"] == "approval_refresh_required"
            await db.rollback()
        async with factory() as db:
            root = await db.get(AgentRun, context.run_id)
            if fault == "terminal_child":
                assert root.outcome == "blocked"
                assert (await db.get(AgentRun, child.id)).status == "completed"
            else:
                assert root.status == "awaiting_approval"
                assert root.metadata_json == metadata
        assert effects.calls == []


async def test_shutdown_of_delegated_continuation_settles_linked_schedule(
    committed_db_session_factory, monkeypatch
):
    import asyncio

    from pydantic_ai.models.function import FunctionModel

    from models.agent import AgentSchedule, AgentScheduleRun

    factory = committed_db_session_factory
    queued = []
    entered = asyncio.Event()

    async def waiting_provider(_messages, _info):
        entered.set()
        await asyncio.Event().wait()
        yield "unreachable"

    with scenario_effects(name="scenario_release_write") as effects:
        context = await restore_approval_fixture(factory, "delegated")
        model = FunctionModel(stream_function=waiting_provider)
        monkeypatch.setattr("services.agents.runtime.loop.build_model", lambda _resolved: model)
        monkeypatch.setattr(
            run_task_registry, "spawn", lambda _id, coroutine, **_kwargs: queued.append(coroutine)
        )
        task = None
        try:
            for round_number in (1, 2):
                async with factory() as db:
                    actor = await db.get(User, context.user_id)
                    workspace = await db.get(Workspace, context.workspace_id)
                    projection = await get_agent_run_approval_state(
                        db, actor=actor, workspace=workspace, run_id=context.run_id
                    )
                    if round_number == 2:
                        now = datetime.now(UTC)
                        schedule = AgentSchedule(
                            agent_id=context.agent_id,
                            user_id=context.user_id,
                            workspace_id=context.workspace_id,
                            schedule_type="once",
                            run_once_at=now,
                        )
                        db.add(schedule)
                        await db.flush()
                        schedule_run = AgentScheduleRun(
                            schedule_id=schedule.id,
                            workspace_id=context.workspace_id,
                            user_id=context.user_id,
                            agent_id=context.agent_id,
                            scheduled_for=now,
                            status="awaiting_approval",
                            conversation_id=context.conversation_id,
                            agent_run_id=context.run_id,
                        )
                        db.add(schedule_run)
                        await db.commit()
                        schedule_run_id = schedule_run.id
                    leaf = projection.approvals[0]
                    await resume_agent_run_stream(
                        db,
                        actor=actor,
                        workspace=workspace,
                        run_id=context.run_id,
                        payload=AgentRunResumeRequest(
                            approval_revision=projection.approval_revision,
                            decisions=[
                                AgentRunResumeDecision(
                                    approval_id=leaf.approval_id,
                                    tool_call_id=leaf.tool_call_id,
                                    decision="approved",
                                )
                            ],
                        ),
                    )
                task = asyncio.create_task(queued[-1])
                if round_number == 1:
                    await asyncio.wait_for(task, timeout=5)
                    assert [value for _, value in effects.calls] == ["first"]
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert [value for _, value in effects.calls] == ["first", "second"]
            task.cancel("shutdown")
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=10)
            async with factory() as db:
                root = await db.get(AgentRun, context.run_id)
                child = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == root.id))
                linked = await db.get(AgentScheduleRun, schedule_run_id)
                assert root.status == child.status == "failed"
                assert root.outcome == "blocked"
                assert linked.status == "terminal_failed"
                assert linked.last_error_code == "agent_run_resume_requires_recovery"
                assert {
                    action["tool_call_id"]
                    for action in root.completion_json["recovery"]["actions"]
                    if action["status"] == "completed"
                } >= {"workflow:1", "workflow:2"}
            assert [value for _, value in effects.calls] == ["first", "second"]
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            for coroutine in queued:
                coroutine.close()
            await close_code_mode_executor()
