"""Memory tools inherit dispatch audit and enforce conditional core approval."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai import ApprovalRequired, ModelRetry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_memories import AgentMemory
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation
from services.agents.runtime.dispatch import dispatch_tool_execution
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.tools.memory import forget_memory, save_memory, update_memory
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from tests.services.memories.conftest import MemoryContext, install_fake_embeddings


async def _runtime_context(
    db: AsyncSession,
    context: MemoryContext,
    *,
    approved: bool,
    side_effect_policy: str = "allow",
):
    conversation = Conversation(
        user_id=context.user.id,
        workspace_id=context.workspace.id,
        created_by=context.user.id,
        active_agent_id=context.agent.id,
    )
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        conversation_id=conversation.id,
        agent_id=context.agent.id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        trigger="interactive",
        status="running",
    )
    db.add(run)
    await db.flush()
    deps = SimpleNamespace(
        db=db,
        user=context.user,
        workspace=context.workspace,
        membership=context.membership,
        conversation=conversation,
        agent=context.agent,
        run=run,
        envelope=RunEnvelope(
            principal="interactive",
            side_effect_policy=side_effect_policy,
        ),
    )
    return SimpleNamespace(deps=deps, tool_call_approved=approved)


async def _dispatch_save(ctx, *, kind: str, title: str) -> dict[str, object]:
    args = {
        "title": title,
        "content": "A durable account fact.",
        "scope": "agent",
        "kind": kind,
        "memory_type": "fact",
        "importance": 3,
        "expires_in_days": None,
        "duplicate_of": None,
        "save_as_new": False,
    }

    async def handler(values):
        return await save_memory(ctx, **values)

    return await dispatch_tool_execution(
        ctx,
        call=SimpleNamespace(
            tool_name="save_memory",
            tool_call_id=f"save-memory-{uuid4().hex}",
        ),
        tool_def=None,
        args=args,
        handler=handler,
    )


async def _dispatch_update(
    ctx,
    *,
    memory_id: str,
    title: str,
) -> dict[str, object]:
    args = {
        "memory_id": memory_id,
        "title": title,
        "content": None,
        "importance": None,
        "expires_in_days": None,
    }

    async def handler(values):
        return await update_memory(ctx, **values)

    return await dispatch_tool_execution(
        ctx,
        call=SimpleNamespace(
            tool_name="update_memory",
            tool_call_id=f"update-memory-{uuid4().hex}",
        ),
        tool_def=None,
        args=args,
        handler=handler,
    )


async def _dispatch_forget(
    ctx,
    *,
    memory_id: str,
) -> dict[str, object]:
    args = {
        "memory_id": memory_id,
        "reason": "No longer relevant.",
    }

    async def handler(values):
        return await forget_memory(ctx, **values)

    return await dispatch_tool_execution(
        ctx,
        call=SimpleNamespace(
            tool_name="forget_memory",
            tool_call_id=f"forget-memory-{uuid4().hex}",
        ),
        tool_def=None,
        args=args,
        handler=handler,
    )


async def test_note_runs_automatically_and_core_requires_then_accepts_approval(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    automatic = await _runtime_context(db_session, memory_context, approved=False)
    result = await _dispatch_save(automatic, kind="note", title="Automatic note")
    assert result["status"] == "created"

    pending = await _runtime_context(db_session, memory_context, approved=False)
    with pytest.raises(ApprovalRequired):
        await _dispatch_save(pending, kind="core", title="Core identity")

    approved = await _runtime_context(db_session, memory_context, approved=True)
    result = await _dispatch_save(approved, kind="core", title="Approved identity")
    assert result["status"] == "created"
    assert await db_session.scalar(
        select(AgentMemory).where(
            AgentMemory.kind == "core",
            AgentMemory.title == "Approved identity",
        )
    )
    audits = list(
        await db_session.scalars(select(AuditEvent).where(AuditEvent.tool_name == "save_memory"))
    )
    assert {"completed", "approval_requested"}.issubset(
        {event.details["outcome"] for event in audits}
    )


async def test_write_is_denied_by_run_envelope_before_handler(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    denied = await _runtime_context(
        db_session,
        memory_context,
        approved=False,
        side_effect_policy="deny",
    )
    with pytest.raises(ModelRetry):
        await _dispatch_save(denied, kind="note", title="Denied note")
    assert (
        await db_session.scalar(select(AgentMemory).where(AgentMemory.title == "Denied note"))
        is None
    )
    assert RUNTIME_TOOL_CATALOG["save_memory"].effect_scope == "internal"


async def test_core_update_requires_approval_and_succeeds_on_approved_replay(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    creator = await _runtime_context(db_session, memory_context, approved=True)
    created = await _dispatch_save(creator, kind="core", title="Original identity")
    memory_id = created["memory"]["id"]

    pending = await _runtime_context(db_session, memory_context, approved=False)
    with pytest.raises(ApprovalRequired):
        await _dispatch_update(
            pending,
            memory_id=memory_id,
            title="Unapproved identity",
        )
    memory = await db_session.get(AgentMemory, memory_id)
    assert memory.title == "Original identity"

    approved = await _runtime_context(db_session, memory_context, approved=True)
    result = await _dispatch_update(
        approved,
        memory_id=memory_id,
        title="Approved identity",
    )
    assert result["status"] == "updated"
    await db_session.refresh(memory)
    assert memory.title == "Approved identity"
    audits = list(
        await db_session.scalars(select(AuditEvent).where(AuditEvent.tool_name == "update_memory"))
    )
    assert {"completed", "approval_requested"}.issubset(
        {event.details["outcome"] for event in audits}
    )


async def test_core_forget_requires_approval_while_note_forget_remains_automatic(
    db_session: AsyncSession,
    memory_context: MemoryContext,
    monkeypatch,
) -> None:
    install_fake_embeddings(monkeypatch)
    creator = await _runtime_context(db_session, memory_context, approved=True)
    core = await _dispatch_save(creator, kind="core", title="Protected identity")
    note = await _dispatch_save(creator, kind="note", title="Temporary note")

    automatic = await _runtime_context(db_session, memory_context, approved=False)
    note_result = await _dispatch_forget(
        automatic,
        memory_id=note["memory"]["id"],
    )
    assert note_result["status"] == "archived"

    pending = await _runtime_context(db_session, memory_context, approved=False)
    with pytest.raises(ApprovalRequired):
        await _dispatch_forget(
            pending,
            memory_id=core["memory"]["id"],
        )
    core_memory = await db_session.get(AgentMemory, core["memory"]["id"])
    assert core_memory.status == "active"

    approved = await _runtime_context(db_session, memory_context, approved=True)
    core_result = await _dispatch_forget(
        approved,
        memory_id=core["memory"]["id"],
    )
    assert core_result["status"] == "archived"
    await db_session.refresh(core_memory)
    assert core_memory.status == "archived"

    audits = list(
        await db_session.scalars(select(AuditEvent).where(AuditEvent.tool_name == "forget_memory"))
    )
    assert {"completed", "approval_requested"}.issubset(
        {event.details["outcome"] for event in audits}
    )
