"""Weighted recency fusion remains a tie-breaker over relevant candidates."""

from datetime import UTC, datetime

import pytest

from services.kb import search_chunks
from tests.integration.retrieval_eval.conftest import (
    RetrievalCorpus,
    _seed_document,
)
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_fresh_near_duplicate_outranks_stale_eligible_source(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    content = (
        "# Service ownership\n\n"
        "The analytics export owner is the data platform team. Escalate delayed exports "
        "through the data operations channel."
    )
    first = await _seed_document(
        retrieval_corpus.db,
        workspace=retrieval_corpus.workspace,
        creator=retrieval_corpus.creator,
        title="First service ownership",
        content=content,
    )
    second = await _seed_document(
        retrieval_corpus.db,
        workspace=retrieval_corpus.workspace,
        creator=retrieval_corpus.creator,
        title="Second service ownership",
        content=content,
    )
    baseline = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="who owns delayed analytics exports",
        provider=FakeEmbeddingProvider(),
    )
    pair_ids = {first.id, second.id}
    baseline_pair = [hit for hit in baseline.results if hit.document_id in pair_ids]
    assert len(baseline_pair) == 2
    fresh_id, stale_id = (hit.document_id for hit in baseline_pair)
    by_id = {first.id: first, second.id: second}
    fresh = by_id[fresh_id]
    stale = by_id[stale_id]
    baseline_fresh_score = baseline_pair[0].score

    stale.source_type = "url"
    stale.external_url = "https://docs.example.com/stale-ownership"
    stale.source_updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    fresh.source_type = "url"
    fresh.external_url = "https://docs.example.com/fresh-ownership"
    fresh.source_updated_at = datetime(2026, 7, 1, tzinfo=UTC)
    await retrieval_corpus.db.flush()

    result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="who owns delayed analytics exports",
        provider=FakeEmbeddingProvider(),
    )
    document_order = [hit.document_id for hit in result.results]

    assert document_order.index(fresh.id) < document_order.index(stale.id)
    fresh_hit = next(hit for hit in result.results if hit.document_id == fresh.id)
    assert "recency" in fresh_hit.sources
    assert fresh_hit.score > baseline_fresh_score


async def test_manual_sources_never_receive_recency_provenance(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="error 4032 meaning",
        provider=FakeEmbeddingProvider(),
    )
    expected_id = retrieval_corpus.documents["api_error_codes.md"].id
    hits = [hit for hit in result.results if hit.document_id == expected_id]

    assert hits
    assert all("recency" not in hit.sources for hit in hits)
