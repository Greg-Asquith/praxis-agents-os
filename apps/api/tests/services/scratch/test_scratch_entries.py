# apps/api/tests/services/scratch/test_scratch_entries.py

"""Service tests for agent scratch entries."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent import Agent
from models.conversation import Conversation
from models.scratch import ScratchEntry
from services.agent_runs import create_agent_run
from services.scratch import (
    delete_scratch_entry,
    list_scratch_entries,
    purge_expired_scratch,
    read_scratch_entry,
    upsert_scratch_entry,
)
from services.scratch.domain import ScratchScope
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class ScratchTestContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID


async def test_scratch_upsert_read_list_and_delete(db_session: AsyncSession) -> None:
    context = await _scratch_context(db_session)
    scope = ScratchScope(conversation_id=context.conversation_id)

    entry = await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name=" draft ",
        content="first draft",
        created_by_run_id=context.run_id,
    )
    entry.expires_at = datetime.now(UTC) + timedelta(minutes=5)
    await db_session.flush()
    previous_expiry = entry.expires_at

    read_entry = await read_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="draft",
    )
    summaries = await list_scratch_entries(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
    )
    deleted = await delete_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="draft",
    )

    assert read_entry is not None
    assert read_entry.name == "draft"
    assert read_entry.content == "first draft"
    assert read_entry.created_by_run_id == context.run_id
    assert read_entry.expires_at > previous_expiry
    assert [summary.name for summary in summaries] == ["draft"]
    assert summaries[0].content_bytes == len("first draft")
    assert not hasattr(summaries[0], "content")
    assert deleted is True
    assert (
        await read_scratch_entry(
            db_session,
            workspace_id=context.workspace_id,
            scope=scope,
            name="draft",
        )
        is None
    )


async def test_scratch_updates_existing_entry_without_consuming_capacity(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCRATCH_MAX_ENTRIES_PER_SCOPE", 1)
    context = await _scratch_context(db_session)
    scope = ScratchScope(conversation_id=context.conversation_id)

    await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="draft",
        content="first",
        created_by_run_id=context.run_id,
    )
    updated = await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="draft",
        content="second",
        created_by_run_id=context.run_id,
    )

    assert updated.content == "second"
    with pytest.raises(AppValidationError):
        await upsert_scratch_entry(
            db_session,
            workspace_id=context.workspace_id,
            scope=scope,
            name="other",
            content="blocked",
            created_by_run_id=context.run_id,
        )


async def test_expired_scratch_entries_are_not_read_listed_or_counted(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SCRATCH_MAX_ENTRIES_PER_SCOPE", 1)
    context = await _scratch_context(db_session)
    scope = ScratchScope(conversation_id=context.conversation_id)
    expired = await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="expired",
        content="old",
        created_by_run_id=context.run_id,
    )
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    read_entry = await read_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="expired",
    )
    summaries = await list_scratch_entries(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
    )
    replacement = await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="fresh",
        content="new",
        created_by_run_id=context.run_id,
    )

    assert read_entry is None
    assert summaries == []
    assert replacement.name == "fresh"


async def test_scratch_scopes_do_not_leak_between_conversations(
    db_session: AsyncSession,
) -> None:
    context = await _scratch_context(db_session)
    other_context = await _second_conversation_context(db_session, context)

    await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=ScratchScope(conversation_id=context.conversation_id),
        name="draft",
        content="visible",
        created_by_run_id=context.run_id,
    )

    assert (
        await read_scratch_entry(
            db_session,
            workspace_id=other_context.workspace_id,
            scope=ScratchScope(conversation_id=other_context.conversation_id),
            name="draft",
        )
        is None
    )


async def test_purge_expired_scratch_deletes_only_expired_rows(
    db_session: AsyncSession,
) -> None:
    context = await _scratch_context(db_session)
    scope = ScratchScope(conversation_id=context.conversation_id)
    expired = await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="expired",
        content="old",
        created_by_run_id=context.run_id,
    )
    fresh = await upsert_scratch_entry(
        db_session,
        workspace_id=context.workspace_id,
        scope=scope,
        name="fresh",
        content="new",
        created_by_run_id=context.run_id,
    )
    expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    purged_count = await purge_expired_scratch(db_session)

    assert purged_count == 1
    remaining_names = (
        await db_session.scalars(
            select(ScratchEntry.name).where(
                ScratchEntry.id.in_([expired.id, fresh.id]),
            )
        )
    ).all()
    assert set(remaining_names) == {"fresh"}


async def _scratch_context(db: AsyncSession) -> ScratchTestContext:
    user = build_user(email=f"scratch-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"scratch-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    agent = Agent(
        name="Scratch Agent",
        slug=f"scratch-agent-{uuid4().hex[:8]}",
        instructions="Use scratch.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
        tool_names=[],
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
        trigger="interactive",
    )
    return ScratchTestContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def _second_conversation_context(
    db: AsyncSession,
    context: ScratchTestContext,
) -> ScratchTestContext:
    conversation = Conversation(
        user_id=context.user_id,
        workspace_id=context.workspace_id,
        created_by=context.user_id,
        active_agent_id=context.agent_id,
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
    return ScratchTestContext(
        user_id=context.user_id,
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        conversation_id=conversation.id,
        run_id=run.id,
    )
