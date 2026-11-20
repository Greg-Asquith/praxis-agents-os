# apps/api/tests/services/memories/test_dream_apply.py

"""Server-side guards on the operations a dream returns."""

from datetime import UTC, datetime

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_memories import AgentMemory
from models.audit_event import AuditEvent
from models.memory_dream_run import MemoryDreamRun
from services.memories import edit_memory, forget_memory, save_memory
from services.memories.dream import apply_dream_operations
from services.memories.dream.domain import (
    DreamOperation,
    DreamScopeRequest,
    DreamScopeTarget,
)
from services.memories.schemas import MemoryUpdateRequest
from tests.factories.conversations import build_conversation
from tests.services.memories.conftest import MemoryContext, install_fake_embeddings
from tests.support.requests import build_test_request

_OPERATIONS = TypeAdapter(list[DreamOperation])


async def _run(db: AsyncSession, context: MemoryContext) -> MemoryDreamRun:
    run = MemoryDreamRun(
        workspace_id=context.workspace.id, status="applying", window_end=datetime.now(UTC)
    )
    db.add(run)
    await db.flush()
    return run


async def _note(db: AsyncSession, context: MemoryContext, *, title: str, content: str):
    result = await save_memory(
        db,
        workspace=context.workspace,
        agent=context.agent,
        user=context.user,
        scope="workspace",
        memory_type="fact",
        title=title,
        content_md=content,
        provenance=context.provenance,
    )
    return result.memory


def _request(context: MemoryContext, memories=None, conversations=None) -> DreamScopeRequest:
    return DreamScopeRequest(
        target=DreamScopeTarget(
            workspace=context.workspace, scope="workspace", agent=context.agent, user=context.user
        ),
        memories=memories or {},
        conversations=conversations or {},
    )


async def _apply(db: AsyncSession, run: MemoryDreamRun, request, operations: list[dict]):
    return await apply_dream_operations(
        db,
        run=run,
        request=request,
        operations=_OPERATIONS.validate_python(operations),
        max_operations=10,
    )


async def _active_titles(db: AsyncSession, context: MemoryContext) -> set[str]:
    rows = await db.scalars(
        select(AgentMemory.title).where(
            AgentMemory.workspace_id == context.workspace.id, AgentMemory.status == "active"
        )
    )
    return set(rows)


async def test_unsupplied_reference_rejects_the_whole_response(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    run = await _run(db_session, memory_context)
    result = await _apply(
        db_session,
        run,
        _request(memory_context),
        [
            {
                "op": "create",
                "title": "Billing day",
                "content_md": "Invoices go out on the 1st.",
                "memory_type": "fact",
            },
            {"op": "retire", "memory": "m9"},
        ],
    )
    assert result.rejected == "unknown_reference"
    assert await _active_titles(db_session, memory_context) == set()


async def test_dream_leaves_a_memory_a_person_edited(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    memory = await _note(
        db_session, memory_context, title="Report cadence", content="Reports go out weekly."
    )
    # Title-only edits change the row in place, so created_by stays "agent".
    await edit_memory(
        db_session,
        request=build_test_request(),
        actor=memory_context.user,
        workspace=memory_context.workspace,
        membership=memory_context.membership,
        memory_id=memory.id,
        payload=MemoryUpdateRequest(title="Weekly report cadence"),
    )
    run = await _run(db_session, memory_context)
    result = await _apply(
        db_session,
        run,
        _request(memory_context, memories={"m1": memory.id}),
        [{"op": "revise", "memory": "m1", "content_md": "Reports go out monthly."}],
    )
    await db_session.refresh(memory)
    assert result.skipped["protected"] == 1
    assert memory.status == "active"
    assert memory.content_md == "Reports go out weekly."


async def test_dream_does_not_recreate_a_forgotten_memory(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    memory = await _note(
        db_session, memory_context, title="Office move", content="The team moves office in May."
    )
    await forget_memory(
        db_session,
        workspace=memory_context.workspace,
        agent=memory_context.agent,
        user=memory_context.user,
        memory_id=memory.id,
    )
    run = await _run(db_session, memory_context)
    result = await _apply(
        db_session,
        run,
        _request(memory_context),
        [
            {
                "op": "create",
                "title": "Office move",
                "content_md": "The team moves office in May.",
                "memory_type": "fact",
            }
        ],
    )
    assert result.skipped["removed_by_person"] == 1
    assert await _active_titles(db_session, memory_context) == set()


async def test_merge_supersedes_every_source_once(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    first = await _note(
        db_session, memory_context, title="Client tone", content="Acme likes short emails."
    )
    second = await _note(
        db_session, memory_context, title="Acme email style", content="Keep Acme replies brief."
    )
    run = await _run(db_session, memory_context)
    request = _request(memory_context, memories={"m1": first.id, "m2": second.id})
    operations = [
        {
            "op": "merge",
            "memories": ["m1", "m2"],
            "title": "Acme emails",
            "content_md": "Acme prefers brief, short emails.",
        }
    ]
    result = await _apply(db_session, run, request, operations)
    repeat = await _apply(db_session, run, request, operations)

    survivors = list(
        await db_session.scalars(
            select(AgentMemory).where(
                AgentMemory.workspace_id == memory_context.workspace.id,
                AgentMemory.source == "dream",
            )
        )
    )
    assert result.applied["merge"] == 1
    assert repeat.already_applied
    assert len(survivors) == 1
    assert survivors[0].created_by == "system"
    for source in (first, second):
        await db_session.refresh(source)
        assert source.status == "superseded"
        assert source.superseded_by_id == survivors[0].id
    events = await db_session.scalars(
        select(AuditEvent.details["event"].astext).where(
            AuditEvent.resource_id.in_([str(first.id), str(second.id)]),
            AuditEvent.actor_type == "service",
        )
    )
    assert list(events) == ["superseded", "superseded"]


async def test_workspace_scope_refuses_what_came_from_a_private_chat(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    conversation = build_conversation(
        user=memory_context.user, workspace=memory_context.workspace, visibility="private"
    )
    db_session.add(conversation)
    await db_session.flush()
    run = await _run(db_session, memory_context)
    result = await _apply(
        db_session,
        run,
        _request(memory_context, conversations={"c1": conversation.id}),
        [
            {
                "op": "create",
                "title": "Salary",
                "content_md": "Sam is negotiating a raise.",
                "memory_type": "fact",
                "conversation": "c1",
            }
        ],
    )
    assert result.rejected == "scope_mismatch"
    assert await _active_titles(db_session, memory_context) == set()
