"""Pending-vector and provider-outage degradation assertions."""

from collections.abc import Sequence

import pytest

from core.settings import settings
from services.embeddings.domain import EmbeddingProviderError
from services.kb import search_chunks
from services.kb.embed_chunks import embed_kb_chunks
from tests.integration.retrieval_eval.conftest import RetrievalCorpus
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")


class FailingEmbeddingProvider(FakeEmbeddingProvider):
    """Deterministic query-provider outage."""

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        model: str,
        dimensions: int,
    ):
        raise EmbeddingProviderError("retrieval eval provider outage")


async def test_pending_document_stays_findable_before_and_after_embedding(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    fallback = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="pending capacity marker",
        top_k=settings.KB_SEARCH_TOP_K_MAX,
        provider=FailingEmbeddingProvider(),
    )

    assert fallback.mode == "lexical_fallback"
    assert len(fallback.results) == settings.KB_SEARCH_TOP_K_MAX
    assert {hit.document_id for hit in fallback.results} == {retrieval_corpus.pending_document.id}
    assert all(hit.pending_embedding for hit in fallback.results)
    assert all(hit.is_private is False for hit in fallback.results)

    await embed_kb_chunks(
        retrieval_corpus.db,
        document_id=retrieval_corpus.pending_document.id,
        workspace_id=retrieval_corpus.workspace.id,
        provider=FakeEmbeddingProvider(),
    )
    hybrid = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="pending capacity marker",
        provider=FakeEmbeddingProvider(),
    )

    assert hybrid.mode == "hybrid"
    assert hybrid.results
    assert all(hit.pending_embedding is False for hit in hybrid.results)


async def test_provider_failure_returns_nonempty_lexical_results(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="WireGuard",
        provider=FailingEmbeddingProvider(),
    )

    assert result.mode == "lexical_fallback"
    assert result.results
    assert result.results[0].document_id == retrieval_corpus.documents["vpn_setup.md"].id
    assert result.results[0].sources == ["lexical"]
