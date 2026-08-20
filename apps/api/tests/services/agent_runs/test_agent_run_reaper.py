# apps/api/tests/services/agent_runs/test_agent_run_reaper.py

"""Tests for abandoned agent run reaping."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.jobs import Job
from services.agent_runs import create_agent_run, reap_abandoned_runs, start_agent_run
from services.agent_runs.await_approval import mark_run_awaiting_approval
from services.agent_runs.domain import RUN_STATUS_FAILED, RUN_STATUS_PENDING, RUN_STATUS_RUNNING
from services.agent_runs.reap_abandoned import RUN_ABANDONED_ERROR_CODE
from services.agent_runs.start_with_lease import start_agent_run_with_lease
from services.agents.runtime.approval_state import APPROVAL_STATE_METADATA_KEY
from services.jobs.handlers.sweep_expired_agent_run_approvals import (
    DELETE_STAGED_APPROVAL_CONTENT_KIND,
)
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class RunContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID


@pytest_asyncio.fixture
async def run_context(db_session: AsyncSession) -> RunContext:
    user = build_user(email=f"reaper-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"reaper-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    agent = Agent(
        name="Reaper Agent",
        slug=f"reaper-agent-{uuid4().hex[:8]}",
        instructions="Reply.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    return RunContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
    )


async def _create_run(db: AsyncSession, ctx: RunContext) -> AgentRun:
    return await create_agent_run(
        db,
        conversation_id=ctx.conversation_id,
        agent_id=ctx.agent_id,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        trigger="interactive",
    )


async def test_reap_abandoned_runs_fails_expired_running_lease(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    await start_agent_run(db_session, run)
    run.lease_expires_at = now - timedelta(seconds=1)
    await db_session.flush()

    result = await reap_abandoned_runs(db_session, run_id=run.id, now=now)

    assert result.failed_run_ids == [run.id]
    assert run.status == RUN_STATUS_FAILED
    assert run.error_code == RUN_ABANDONED_ERROR_CODE
    assert run.outcome == "error"
    assert run.completion_json == {"error_code": RUN_ABANDONED_ERROR_CODE}
    assert "lease expired" in (run.error_message or "")


async def test_reap_abandoned_runs_clears_suspended_approval_state(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    await start_agent_run(db_session, run)
    run.metadata_json = {
        "diagnostic": "keep",
        APPROVAL_STATE_METADATA_KEY: {"message_history": ["large state"]},
        "code_mode_state": {"snapshot_b64": "opaque"},
    }
    run.lease_expires_at = now - timedelta(seconds=1)
    await db_session.flush()

    await reap_abandoned_runs(db_session, run_id=run.id, now=now)

    assert run.metadata_json == {"diagnostic": "keep"}


async def test_reap_abandoned_resumed_run_queues_staged_content_cleanup(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    await start_agent_run(db_session, run)
    content_ref = (
        f"workspaces/{run.workspace_id}/agent-runs/{run.id}/staged-tool-inputs/"
        f"{'a' * 64}-{'b' * 64}.txt"
    )
    run.metadata_json = {
        APPROVAL_STATE_METADATA_KEY: {
            "deferred_tool_requests": {
                "approvals": [
                    {
                        "tool_name": "write_file",
                        "args": {"content_ref": content_ref},
                    }
                ]
            }
        }
    }
    run.lease_expires_at = now - timedelta(seconds=1)
    await db_session.flush()

    await reap_abandoned_runs(db_session, run_id=run.id, now=now)

    cleanup_job = await db_session.scalar(
        select(Job).where(
            Job.kind == DELETE_STAGED_APPROVAL_CONTENT_KIND,
            Job.subject_id == run.id,
        )
    )
    assert cleanup_job is not None
    assert cleanup_job.payload["content_refs"] == [content_ref]
    assert APPROVAL_STATE_METADATA_KEY not in (run.metadata_json or {})


async def test_reap_abandoned_runs_leaves_live_lease_running(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    await start_agent_run(db_session, run)
    run.lease_expires_at = now + timedelta(seconds=90)
    await db_session.flush()

    result = await reap_abandoned_runs(db_session, run_id=run.id, now=now)

    assert result.failed_run_ids == []
    assert run.status == RUN_STATUS_RUNNING


async def test_reap_abandoned_runs_leaves_queued_pending_run_with_live_lease(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    run.created_at = now - timedelta(minutes=2)
    run.lease_expires_at = now + timedelta(seconds=90)
    await db_session.flush()

    result = await reap_abandoned_runs(
        db_session,
        run_id=run.id,
        now=now,
        pending_grace_seconds=60,
    )

    assert result.failed_run_ids == []
    assert run.status == RUN_STATUS_PENDING


async def test_resumed_run_survives_original_start_deadline(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    await start_agent_run(db_session, run)
    run.started_at = now - timedelta(hours=2)
    await db_session.flush()
    await mark_run_awaiting_approval(db_session, run)

    await start_agent_run_with_lease(db_session, run, now=now, ttl_seconds=90)
    result = await reap_abandoned_runs(
        db_session,
        run_id=run.id,
        now=now,
        max_duration_seconds=1200,
    )

    assert result.failed_run_ids == []
    assert run.status == RUN_STATUS_RUNNING
    assert run.started_at is not None
    assert run.started_at >= now - timedelta(minutes=1)


async def test_reap_deadline_message_does_not_blame_live_lease(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    await start_agent_run(db_session, run)
    run.started_at = now - timedelta(hours=2)
    run.lease_expires_at = now + timedelta(seconds=90)
    await db_session.flush()

    result = await reap_abandoned_runs(
        db_session,
        run_id=run.id,
        now=now,
        max_duration_seconds=1200,
    )

    assert result.failed_run_ids == [run.id]
    assert run.error_message == "Agent run exceeded the allowed maximum duration"


async def test_reap_abandoned_runs_fails_stale_pending_without_lease(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    now = datetime.now(UTC)
    run = await _create_run(db_session, run_context)
    run.created_at = now - timedelta(seconds=120)
    await db_session.flush()

    result = await reap_abandoned_runs(
        db_session,
        conversation_id=run_context.conversation_id,
        now=now,
        pending_grace_seconds=60,
    )

    assert result.failed_run_ids == [run.id]
    assert run.status == RUN_STATUS_FAILED
    assert "pending" in (run.error_message or "")


async def test_pending_run_can_fail_for_recovery(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    run = await _create_run(db_session, run_context)
    assert run.status == RUN_STATUS_PENDING

    result = await reap_abandoned_runs(
        db_session,
        run_id=run.id,
        now=datetime.now(UTC) + timedelta(seconds=120),
        pending_grace_seconds=1,
    )

    assert result.failed_run_ids == [run.id]
    assert run.status == RUN_STATUS_FAILED
