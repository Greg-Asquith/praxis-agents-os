"""Knowledge-base hybrid search service tests."""

import importlib
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.embeddings.domain import EmbeddingProviderError
from services.kb import search_chunks
from services.retrieval import RerankItem
from tests.factories import build_kb_chunk, build_kb_document, build_user
from tests.services.kb.conftest import KBActors
from tests.support.embeddings import FakeEmbeddingProvider


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    """Provider stub for the explicit lexical degradation path."""

    async def embed_texts(self, texts, *, model, dimensions):
        raise EmbeddingProviderError("offline")


class ReverseReranker:
    """Deterministic reranker stub."""

    async def rerank(
        self,
        query: str,
        results: list[RerankItem],
    ) -> list[RerankItem]:
        return list(reversed(results))


async def _add_document(
    db: AsyncSession,
    *,
    actors: KBActors,
    title: str,
    content: str,
    private: bool = False,
    creator_id=None,
    embedded: bool = True,
):
    document = build_kb_document(
        workspace=actors.workspace,
        title=title,
        content_md=content,
        status="ready",
        is_private=private,
        created_by_user_id=creator_id or actors.user.id,
        chunk_count=1,
    )
    db.add(document)
    await db.flush()
    chunk = build_kb_chunk(document=document, content=content)
    if embedded:
        batch = await FakeEmbeddingProvider().embed_texts(
            [content],
            model=settings.EMBEDDINGS_MODEL,
            dimensions=1024,
        )
        chunk.embedding = batch.vectors[0]
        chunk.embedding_provider = batch.provider
        chunk.embedding_model = batch.model
        chunk.embedding_dims = batch.dimensions
    db.add(chunk)
    await db.flush()
    return document, chunk


async def test_hybrid_search_returns_typed_hit_and_collection_guard(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document, chunk = await _add_document(
        db_session,
        actors=kb_actors,
        title="VPN guide",
        content="Install WireGuard and connect to the company VPN.",
    )

    statements: list[str] = []
    original_execute = db_session.execute

    async def capture_execute(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", capture_execute)
    result = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="WireGuard VPN",
        provider=FakeEmbeddingProvider(),
    )

    assert result.mode == "hybrid"
    assert result.results[0].id == chunk.id
    assert result.results[0].document_id == document.id
    assert result.results[0].sources == ["lexical", "semantic"]
    assert result.results[0].pending_embedding is False
    assert result.results[0].is_private is False
    iterative_index = statements.index("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
    ef_search_index = next(
        index
        for index, statement in enumerate(statements)
        if statement.startswith("SET LOCAL hnsw") and "ef_search" in statement
    )
    search_index = next(
        index for index, statement in enumerate(statements) if statement.lstrip().startswith("WITH")
    )
    assert iterative_index < ef_search_index < search_index

    chunk.embedding_model = "older-model"
    await db_session.flush()
    guarded = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="WireGuard VPN",
        provider=FakeEmbeddingProvider(),
    )
    assert guarded.results[0].sources == ["lexical"]


async def test_lexical_fallback_finds_pending_embedding(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    _document, chunk = await _add_document(
        db_session,
        actors=kb_actors,
        title="Expense guide",
        content="Use code EXP-REIMBURSE-90 for travel claims.",
        embedded=False,
    )

    result = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="EXP-REIMBURSE-90",
        provider=FailingEmbeddingProvider(),
    )

    assert result.mode == "lexical_fallback"
    assert result.results[0].id == chunk.id
    assert result.results[0].pending_embedding is True
    assert result.results[0].sources == ["lexical"]


async def test_search_filters_and_privacy_apply_to_every_candidate_path(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    other_user = build_user(email=f"kb-private-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()
    own_private, _ = await _add_document(
        db_session,
        actors=kb_actors,
        title="Own private",
        content="shared retrieval phrase",
        private=True,
    )
    await _add_document(
        db_session,
        actors=kb_actors,
        title="Other private",
        content="shared retrieval phrase",
        private=True,
        creator_id=other_user.id,
    )
    public, _ = await _add_document(
        db_session,
        actors=kb_actors,
        title="Public",
        content="shared retrieval phrase",
    )

    private_result = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="shared retrieval phrase",
        private_only=True,
        provider=FakeEmbeddingProvider(),
    )
    assert {hit.document_id for hit in private_result.results} == {own_private.id}
    assert all(hit.is_private for hit in private_result.results)

    filtered = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="shared retrieval phrase",
        document_ids=[public.id],
        provider=FakeEmbeddingProvider(),
    )
    assert {hit.document_id for hit in filtered.results} == {public.id}


@pytest.mark.parametrize(
    ("query", "source_types"),
    [
        ("", None),
        ("x" * 1_001, None),
        ("valid", ["unknown"]),
    ],
)
async def test_search_validates_input(
    db_session: AsyncSession,
    kb_actors: KBActors,
    query: str,
    source_types: list[str] | None,
) -> None:
    with pytest.raises(AppValidationError):
        await search_chunks(
            db_session,
            workspace_id=kb_actors.workspace.id,
            user_id=kb_actors.user.id,
            query=query,
            source_types=source_types,
            provider=FakeEmbeddingProvider(),
        )


async def test_search_clamps_top_k_to_configured_bounds(
    db_session: AsyncSession,
    kb_actors: KBActors,
) -> None:
    for index in range(2):
        await _add_document(
            db_session,
            actors=kb_actors,
            title=f"Guide {index}",
            content=f"bounded result phrase {index}",
        )

    result = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="bounded result phrase",
        top_k=1_000,
        provider=FakeEmbeddingProvider(),
    )
    assert len(result.results) == 2

    for requested_limit in (-10, 0):
        minimum = await search_chunks(
            db_session,
            workspace_id=kb_actors.workspace.id,
            user_id=kb_actors.user.id,
            query="bounded result phrase",
            top_k=requested_limit,
            provider=FakeEmbeddingProvider(),
        )
        assert len(minimum.results) == 1


async def test_configured_reranker_reorders_the_fused_candidate_set(
    db_session: AsyncSession,
    kb_actors: KBActors,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for index in range(2):
        await _add_document(
            db_session,
            actors=kb_actors,
            title=f"Rerank guide {index}",
            content="same reranker candidate",
        )

    baseline = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="same reranker candidate",
        provider=FakeEmbeddingProvider(),
    )
    search_module = importlib.import_module("services.kb.search_chunks")
    monkeypatch.setattr(search_module, "get_reranker", lambda: ReverseReranker())

    reranked = await search_chunks(
        db_session,
        workspace_id=kb_actors.workspace.id,
        user_id=kb_actors.user.id,
        query="same reranker candidate",
        provider=FakeEmbeddingProvider(),
    )

    assert [hit.id for hit in reranked.results] == [hit.id for hit in reversed(baseline.results)]
