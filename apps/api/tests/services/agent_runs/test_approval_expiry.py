"""Tests for parked agent-run approval expiry."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ModelResponse, ToolCallPart
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs import (
    create_agent_run,
    list_pending_agent_run_approvals,
    mark_run_awaiting_approval,
    start_agent_run,
)
from services.agent_runs.resume_run_stream import resume_agent_run_stream
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agent_schedules.reconcile_schedule_run_execution import (
    reconcile_schedule_run_execution,
)
from services.agents.runtime.approval_state import (
    APPROVAL_STATE_METADATA_KEY,
    build_suspended_run_metadata,
)
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.staged_tool_content import (
    WRITE_FILE_CONTENT_REF_ARG,
    resolve_staged_write_content,
    stage_write_file_approval_content,
)
from services.conversations.active_run import get_conversation_active_run
from services.jobs.handlers.sweep_expired_agent_run_approvals import (
    APPROVAL_EXPIRED_ERROR_CODE,
    DELETE_STAGED_APPROVAL_CONTENT_KIND,
    SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND,
    ensure_agent_run_approval_sweep_job,
    handle_delete_staged_approval_content,
    sweep_expired_agent_run_approvals,
)
from services.storage.errors import StorageNotFoundError
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.storage import reset_storage_provider_cache

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class ApprovalContext:
    user: User
    workspace: Workspace
    agent: Agent
    conversation: Conversation
    run: AgentRun
    tool_call_id: str
    content_ref: str | None = None


@pytest.fixture
def local_storage_settings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "STORAGE_PROVIDER", "local_fs")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "APP_BASE_URL", "http://testserver")
    reset_storage_provider_cache()
    try:
        yield
    finally:
        reset_storage_provider_cache()


async def _park_approval(
    db: AsyncSession,
    *,
    now: datetime,
    age_days: int,
    stage_write: bool = False,
    trigger: str = "interactive",
    user: User | None = None,
    workspace: Workspace | None = None,
    agent: Agent | None = None,
) -> ApprovalContext:
    token = uuid4().hex
    if user is None or workspace is None:
        user = build_user(email=f"approval-expiry-{token}@example.com")
        workspace = build_workspace(slug=f"approval-expiry-{token[:8]}")
        membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
        db.add_all([user, workspace, membership])
        await db.flush()
    if agent is None:
        agent = Agent(
            name="Approval expiry agent",
            slug=f"approval-expiry-agent-{token[:8]}",
            instructions="Use tools when helpful.",
            workspace_id=workspace.id,
            created_by=user.id,
        )
        db.add(agent)
        await db.flush()
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger=trigger,
    )
    await start_agent_run(db, run)

    tool_call_id = f"approval-{token}"
    call = ToolCallPart(
        tool_name="write_file" if stage_write else "test_add_numbers",
        tool_call_id=tool_call_id,
        args=(
            {"name": "weekend-note.md", "content": "private staged content"}
            if stage_write
            else {"a": 1, "b": 2}
        ),
    )
    messages = [ModelResponse(parts=[call])]
    deferred_requests = DeferredToolRequests(approvals=[call])
    content_ref = None
    if stage_write:
        staged = await stage_write_file_approval_content(
            workspace_id=workspace.id,
            run_id=run.id,
            new_messages=messages,
            all_messages=messages,
            deferred_tool_requests=deferred_requests,
        )
        messages = staged.all_messages
        deferred_requests = staged.deferred_tool_requests
        approval_args = deferred_requests.approvals[0].args
        assert isinstance(approval_args, dict)
        content_ref = approval_args[WRITE_FILE_CONTENT_REF_ARG]
        assert isinstance(content_ref, str)

    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=conversation,
        message_history=messages,
        deferred_tool_requests=deferred_requests,
    )
    await mark_run_awaiting_approval(db, run)
    run.updated_at = now - timedelta(days=age_days)
    await db.flush()
    return ApprovalContext(
        user=user,
        workspace=workspace,
        agent=agent,
        conversation=conversation,
        run=run,
        tool_call_id=tool_call_id,
        content_ref=content_ref,
    )


async def test_sweep_expires_old_approval_and_unblocks_conversation(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    expired = await _park_approval(db_session, now=now, age_days=8)
    expired.run.metadata_json = {
        **(expired.run.metadata_json or {}),
        "code_mode_state": {"snapshot_b64": "opaque"},
    }
    surviving = await _park_approval(
        db_session,
        now=now,
        age_days=6,
        user=expired.user,
        workspace=expired.workspace,
        agent=expired.agent,
    )
    expired.run.updated_at = now - timedelta(days=8)
    await db_session.flush()

    result = await sweep_expired_agent_run_approvals(
        db_session,
        now=now,
        expiry_days=7,
    )

    assert result.expired_run_ids == [expired.run.id]
    await db_session.refresh(expired.run)
    await db_session.refresh(surviving.run)
    assert expired.run.status == "failed"
    assert expired.run.error_code == APPROVAL_EXPIRED_ERROR_CODE
    assert expired.run.outcome == "blocked"
    assert expired.run.completion_json == {"error_code": APPROVAL_EXPIRED_ERROR_CODE}
    assert "after 7 days" in (expired.run.error_message or "")
    assert APPROVAL_STATE_METADATA_KEY not in (expired.run.metadata_json or {})
    assert "code_mode_state" not in (expired.run.metadata_json or {})
    assert surviving.run.status == "awaiting_approval"
    pending = await list_pending_agent_run_approvals(
        db_session,
        actor=expired.user,
        workspace=expired.workspace,
    )
    assert [item.run_id for item in pending.items] == [surviving.run.id]

    replacement = await create_agent_run(
        db_session,
        conversation_id=expired.conversation.id,
        agent_id=expired.agent.id,
        workspace_id=expired.workspace.id,
        user_id=expired.user.id,
        trigger="interactive",
    )
    assert replacement.status == "pending"

    active_run_response = await get_conversation_active_run(
        db_session,
        actor=expired.user,
        workspace=expired.workspace,
        conversation_id=expired.conversation.id,
    )
    assert active_run_response.active_run is not None
    assert active_run_response.active_run.id == replacement.id
    assert active_run_response.latest_run is not None
    assert active_run_response.latest_run.id == replacement.id
    assert active_run_response.approval_expires_at is None

    repeated = await sweep_expired_agent_run_approvals(
        db_session,
        now=now,
        expiry_days=7,
    )
    assert repeated.expired_run_ids == []

    with pytest.raises(ConflictError, match="not awaiting approval"):
        await resume_agent_run_stream(
            db_session,
            actor=expired.user,
            workspace=expired.workspace,
            run_id=expired.run.id,
            payload=AgentRunResumeRequest(
                decisions=[
                    AgentRunResumeDecision(
                        tool_call_id=expired.tool_call_id,
                        decision="approved",
                    )
                ]
            ),
        )


async def test_sweep_disabled_at_zero_and_does_not_enqueue(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    parked = await _park_approval(db_session, now=now, age_days=30)

    result = await sweep_expired_agent_run_approvals(
        db_session,
        now=now,
        expiry_days=0,
    )
    monkeypatch.setattr(settings, "AGENT_RUN_APPROVAL_EXPIRY_DAYS", 0)
    ensured = await ensure_agent_run_approval_sweep_job(db_session)

    assert result.expired_run_ids == []
    assert parked.run.status == "awaiting_approval"
    assert ensured is None
    assert (
        await db_session.scalar(
            select(Job).where(Job.kind == SWEEP_EXPIRED_AGENT_RUN_APPROVALS_KIND)
        )
        is None
    )


async def test_ensure_approval_sweep_job_is_idempotent(
    db_session: AsyncSession,
) -> None:
    first = await ensure_agent_run_approval_sweep_job(db_session)
    second = await ensure_agent_run_approval_sweep_job(db_session)

    assert first is not None
    assert second is not None
    assert first.id == second.id


async def test_sweep_deletes_staged_write_content(
    db_session: AsyncSession,
    local_storage_settings: None,
) -> None:
    now = datetime.now(UTC)
    parked = await _park_approval(
        db_session,
        now=now,
        age_days=8,
        stage_write=True,
    )
    assert parked.content_ref is not None
    assert (
        await resolve_staged_write_content(
            workspace_id=parked.workspace.id,
            run_id=parked.run.id,
            content_ref=parked.content_ref,
        )
        == "private staged content"
    )

    await sweep_expired_agent_run_approvals(db_session, now=now, expiry_days=7)

    cleanup_job = await db_session.scalar(
        select(Job).where(
            Job.kind == DELETE_STAGED_APPROVAL_CONTENT_KIND,
            Job.subject_id == parked.run.id,
        )
    )
    assert cleanup_job is not None
    assert cleanup_job.payload["content_refs"] == [parked.content_ref]
    assert (
        await resolve_staged_write_content(
            workspace_id=parked.workspace.id,
            run_id=parked.run.id,
            content_ref=parked.content_ref,
        )
        == "private staged content"
    )

    await handle_delete_staged_approval_content(db_session, cleanup_job)

    with pytest.raises(StorageNotFoundError):
        await resolve_staged_write_content(
            workspace_id=parked.workspace.id,
            run_id=parked.run.id,
            content_ref=parked.content_ref,
        )

    await handle_delete_staged_approval_content(db_session, cleanup_job)


async def test_cleanup_enqueue_failure_rolls_back_expiry_without_deleting_content(
    db_session: AsyncSession,
    local_storage_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    parked = await _park_approval(
        db_session,
        now=now,
        age_days=8,
        stage_write=True,
    )
    assert parked.content_ref is not None
    workspace_id = parked.workspace.id
    run_id = parked.run.id
    await db_session.commit()

    async def fail_cleanup_enqueue(*_args, **_kwargs):
        raise RuntimeError("cleanup enqueue unavailable")

    monkeypatch.setattr(
        "services.jobs.handlers.sweep_expired_agent_run_approvals.enqueue_staged_approval_content_cleanup",
        fail_cleanup_enqueue,
    )

    with pytest.raises(RuntimeError, match="cleanup enqueue unavailable"):
        await sweep_expired_agent_run_approvals(db_session, now=now, expiry_days=7)
    await db_session.rollback()
    await db_session.refresh(parked.run)

    assert parked.run.status == "awaiting_approval"
    assert APPROVAL_STATE_METADATA_KEY in (parked.run.metadata_json or {})
    assert (
        await resolve_staged_write_content(
            workspace_id=workspace_id,
            run_id=run_id,
            content_ref=parked.content_ref,
        )
        == "private staged content"
    )


async def test_existing_reconcile_finalizes_expired_scheduled_approval(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    parked = await _park_approval(
        db_session,
        now=now,
        age_days=8,
        trigger="scheduled",
    )
    schedule = AgentSchedule(
        agent_id=parked.agent.id,
        user_id=parked.user.id,
        workspace_id=parked.workspace.id,
        schedule_type="once",
        run_once_at=now,
    )
    db_session.add(schedule)
    await db_session.flush()
    schedule_run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=parked.workspace.id,
        user_id=parked.user.id,
        agent_id=parked.agent.id,
        scheduled_for=now,
        status="awaiting_approval",
        conversation_id=parked.conversation.id,
        agent_run_id=parked.run.id,
    )
    db_session.add(schedule_run)
    await db_session.flush()

    await sweep_expired_agent_run_approvals(db_session, now=now, expiry_days=7)
    assert await reconcile_schedule_run_execution(db_session, now=now) == 1

    assert schedule_run.status == "terminal_failed"
    assert schedule_run.last_error_code == APPROVAL_EXPIRED_ERROR_CODE
    assert schedule.is_active is False


async def test_resume_reservation_rejects_second_request_before_streaming(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_db_session_factory() as setup_db:
        parked = await _park_approval(
            setup_db,
            now=datetime.now(UTC),
            age_days=1,
        )
        await setup_db.commit()

    spawned = []

    def capture_spawn(_run_id, coroutine) -> None:
        spawned.append(coroutine)

    monkeypatch.setattr(run_task_registry, "spawn", capture_spawn)
    payload = AgentRunResumeRequest(
        decisions=[
            AgentRunResumeDecision(
                tool_call_id=parked.tool_call_id,
                decision="approved",
            )
        ]
    )
    start_barrier = asyncio.Barrier(2)

    async def resume_concurrently() -> str:
        await start_barrier.wait()
        async with committed_db_session_factory() as db:
            try:
                await resume_agent_run_stream(
                    db,
                    actor=parked.user,
                    workspace=parked.workspace,
                    run_id=parked.run.id,
                    payload=payload,
                )
            except ConflictError:
                await db.rollback()
                return "conflict"
        return "stream"

    try:
        results = await asyncio.gather(resume_concurrently(), resume_concurrently())
        assert sorted(results) == ["conflict", "stream"]

        async with committed_db_session_factory() as verify_db:
            stored = await verify_db.get(AgentRun, parked.run.id)
            assert stored is not None
            assert stored.status == "running"
    finally:
        for coroutine in spawned:
            coroutine.close()
        async with committed_db_session_factory() as cleanup_db:
            await cleanup_db.execute(delete(AgentRun).where(AgentRun.id == parked.run.id))
            await cleanup_db.execute(
                delete(Conversation).where(Conversation.id == parked.conversation.id)
            )
            await cleanup_db.execute(delete(Agent).where(Agent.id == parked.agent.id))
            await cleanup_db.execute(
                delete(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == parked.workspace.id
                )
            )
            await cleanup_db.execute(delete(Workspace).where(Workspace.id == parked.workspace.id))
            await cleanup_db.execute(delete(User).where(User.id == parked.user.id))
            await cleanup_db.commit()
