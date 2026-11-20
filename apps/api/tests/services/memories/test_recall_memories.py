# apps/api/tests/services/memories/test_recall_memories.py

"""Which memories come up in a turn by themselves, and how they're framed."""

import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pydantic_ai.messages import ModelRequest, TextContent, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_END, UNTRUSTED_CONTENT_START
from services.conversation_review import render_transcript
from services.memories.domain import MemoryProvenance
from services.memories.edit_memory import edit_memory
from services.memories.recall_memories import recall_memories, render_recalled_memories
from services.memories.save_memory import save_memory
from services.memories.schemas import MemoryUpdateRequest
from tests.factories.memories import build_memory
from tests.factories.users import build_user
from tests.factories.workspaces import build_workspace_membership
from tests.services.memories.conftest import MemoryContext, install_fake_embeddings
from tests.support.embeddings import FakeEmbeddingProvider

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "prompt_injection"
_QUERY = "When do invoices go out each month?"


def _install_search_embeddings(monkeypatch) -> None:
    provider = FakeEmbeddingProvider()

    async def fake_embed_texts(_db, texts, **_kwargs):
        return await provider.embed_texts(
            texts, model=settings.EMBEDDINGS_MODEL, dimensions=settings.EMBEDDINGS_DIMENSIONS
        )

    # The package re-exports the function under the module's name, so patch the module itself.
    monkeypatch.setattr(
        import_module("services.memories.search_memories"), "embed_texts", fake_embed_texts
    )


async def _save(db: AsyncSession, context: MemoryContext, *, title: str, content: str, **kwargs):
    result = await save_memory(
        db,
        workspace=context.workspace,
        agent=kwargs.pop("agent", context.agent),
        user=kwargs.pop("user", context.user),
        scope=kwargs.pop("scope", "agent"),
        memory_type="fact",
        title=title,
        content_md=content,
        provenance=kwargs.pop("provenance", context.provenance),
        save_as_new=True,
    )
    return result.memory


async def _recall(db: AsyncSession, context: MemoryContext, *, history=()):
    return await recall_memories(
        db,
        workspace=context.workspace,
        agent=context.agent,
        user=context.user,
        query=_QUERY,
        history=list(history),
    )


async def test_recall_keeps_relevant_memories_and_skips_the_rest(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    _install_search_embeddings(monkeypatch)
    relevant = await _save(
        db_session,
        memory_context,
        title="Invoice day",
        content="Invoices go out on the last Friday of each month.",
    )
    await _save(
        db_session,
        memory_context,
        title="Logo usage",
        content="Use the dark logo on light backgrounds.",
    )
    held_back = await _save(
        db_session,
        memory_context,
        title="Invoice reminders",
        content="Invoices go out with a reminder each month.",
    )
    held_back.recall_disabled_at = datetime.now(UTC)
    await db_session.flush()

    recalled = await _recall(db_session, memory_context)

    assert recalled is not None
    assert recalled.metadata == {"recalled_memory_ids": [str(relevant.id)]}
    assert "last Friday of each month" in recalled.content
    assert "dark logo" not in recalled.content
    assert "with a reminder" not in recalled.content


async def test_a_later_turn_skips_memories_the_conversation_was_shown(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    _install_search_embeddings(monkeypatch)
    await _save(
        db_session,
        memory_context,
        title="Invoice day",
        content="Invoices go out on the last Friday of each month.",
    )
    first = await _recall(db_session, memory_context)
    assert first is not None
    history = [ModelRequest(parts=[UserPromptPart([_QUERY, first])])]

    assert await _recall(db_session, memory_context, history=history) is None


async def test_recall_is_off_when_the_workspace_turns_it_off(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    _install_search_embeddings(monkeypatch)
    await _save(
        db_session,
        memory_context,
        title="Invoice day",
        content="Invoices go out on the last Friday of each month.",
    )
    memory_context.workspace.memory_recall_enabled = False

    assert await _recall(db_session, memory_context) is None


async def test_recall_never_shows_another_persons_or_agents_memories(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    _install_search_embeddings(monkeypatch)
    other_user = build_user(email="recall-other@example.com")
    db_session.add(other_user)
    await db_session.flush()
    db_session.add(
        build_workspace_membership(workspace_id=memory_context.workspace.id, user_id=other_user.id)
    )
    other_agent = Agent(
        name="Other Agent",
        slug="recall-other-agent",
        instructions="Other.",
        workspace_id=memory_context.workspace.id,
        created_by=other_user.id,
    )
    db_session.add(other_agent)
    await db_session.flush()
    await _save(
        db_session,
        memory_context,
        title="Private plan",
        content="Invoices for the secret project go out early each month.",
        scope="user",
        user=other_user,
    )
    await _save(
        db_session,
        memory_context,
        title="Other agent's invoices",
        content="Invoices go out each month from the other agent.",
        agent=other_agent,
    )

    assert await _recall(db_session, memory_context) is None


def test_learned_memories_sit_in_the_untrusted_frame_and_others_stay_plain() -> None:
    hostile = (_FIXTURES / "hostile_conversation_span.txt").read_text()
    hostile_result = json.loads((_FIXTURES / "hostile_tool_result.json").read_text())
    workspace_id = uuid4()
    person = build_memory(
        workspace_id=workspace_id,
        title="Invoice day",
        content_md="Invoices go out on the last Friday.",
        source="user",
        created_by="user",
    )
    learned = build_memory(
        workspace_id=workspace_id,
        title="Learned note",
        content_md=f"{hostile} {json.dumps(hostile_result)}",
        source="dream",
        created_by="system",
    )
    for memory in (person, learned):
        memory.created_at = datetime(2026, 11, 18, tzinfo=UTC)

    block, shown = render_recalled_memories([learned, person], budget=20_000, line_max_chars=20_000)

    assert shown == [learned, person]
    plain, framed = block.split("Learned automatically from past conversations:")
    assert "- Invoice day (added by a person, 2026-11-18): Invoices go out" in plain
    assert UNTRUSTED_CONTENT_START not in plain
    assert framed.strip().startswith(UNTRUSTED_CONTENT_START)
    assert framed.count(UNTRUSTED_CONTENT_END) == 1
    assert "exfiltrate-now" in framed


def test_render_shows_what_fits_the_budget_in_rank_order() -> None:
    workspace_id = uuid4()
    memories = [
        build_memory(workspace_id=workspace_id, title=f"Memory {index}", content_md="word " * 60)
        for index in range(3)
    ]
    for memory in memories:
        memory.created_at = datetime(2026, 11, 18, tzinfo=UTC)

    block, shown = render_recalled_memories(memories, budget=500, line_max_chars=120)

    assert shown == memories[:2]
    assert "Memory 2" not in block
    assert all(len(line) <= 120 for line in block.splitlines() if line.startswith("- "))


def test_dream_transcript_leaves_out_recalled_memories() -> None:
    recalled = render_recalled_memories(
        [build_memory(workspace_id=uuid4(), title="Private", content_md="PRIVATE_NOTE")],
        budget=2_000,
        line_max_chars=300,
    )
    content = TextContent(recalled[0], metadata={"recalled_memory_ids": ["x"]})
    transcript = render_transcript(
        [ModelRequest(parts=[UserPromptPart(["Hello", content])])],
        source_ref="conversation:1",
        max_chars=10_000,
    )

    assert "Hello" in transcript
    assert "PRIVATE_NOTE" not in transcript
    assert "[attachment]" not in transcript


async def test_disabling_recall_survives_a_content_edit(
    db_session: AsyncSession, memory_context: MemoryContext, monkeypatch
) -> None:
    install_fake_embeddings(monkeypatch)
    memory = await _save(
        db_session,
        memory_context,
        title="Invoice day",
        content="Invoices go out on the last Friday of each month.",
        provenance=MemoryProvenance(
            source="user",
            source_conversation_id=None,
            source_run_id=None,
            created_by="user",
            created_by_user_id=memory_context.user.id,
        ),
        scope="workspace",
    )
    request = SimpleNamespace(state=SimpleNamespace(request_id="test"))
    disabled = await edit_memory(
        db_session,
        request=request,
        actor=memory_context.user,
        workspace=memory_context.workspace,
        membership=memory_context.membership,
        memory_id=memory.id,
        payload=MemoryUpdateRequest(recall_disabled=True),
    )
    edited = await edit_memory(
        db_session,
        request=request,
        actor=memory_context.user,
        workspace=memory_context.workspace,
        membership=memory_context.membership,
        memory_id=disabled.id,
        payload=MemoryUpdateRequest(content_md="Invoices go out on the first Monday."),
    )

    assert disabled.recall_disabled_at is not None
    assert edited.id != disabled.id
    assert edited.recall_disabled_at == disabled.recall_disabled_at
