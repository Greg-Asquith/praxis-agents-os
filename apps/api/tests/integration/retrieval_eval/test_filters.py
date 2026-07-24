"""SQL-level source, document, private, and collection filters."""

import pytest
from sqlalchemy import select

from models.kb import KBChunk
from services.kb import search_chunks
from tests.integration.retrieval_eval.conftest import RetrievalCorpus
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_source_and_document_filters_restrict_both_candidate_lists(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    vpn = retrieval_corpus.documents["vpn_setup.md"]
    vpn.source_type = "url"
    vpn.external_url = "https://docs.example.com/vpn"
    await retrieval_corpus.db.flush()

    by_source = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="secure access internal services WireGuard",
        source_types=["url"],
        provider=FakeEmbeddingProvider(),
    )
    by_document = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="first week secure access",
        document_ids=[retrieval_corpus.documents["onboarding_guide.md"].id],
        provider=FakeEmbeddingProvider(),
    )

    assert by_source.results
    assert {hit.document_id for hit in by_source.results} == {vpn.id}
    assert all(hit.source_type == "url" for hit in by_source.results)
    assert {hit.document_id for hit in by_document.results} == {
        retrieval_corpus.documents["onboarding_guide.md"].id
    }


async def test_collection_stamp_mismatch_can_surface_only_lexically(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    document = retrieval_corpus.documents["travel_expense_policy.md"]
    chunks = (
        await retrieval_corpus.db.scalars(select(KBChunk).where(KBChunk.document_id == document.id))
    ).all()
    assert chunks
    for chunk in chunks:
        chunk.embedding_model = "outdated-collection-model"
    await retrieval_corpus.db.flush()

    result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="EXP-REIMBURSE-90",
        provider=FakeEmbeddingProvider(),
    )
    matching = [hit for hit in result.results if hit.document_id == document.id]

    assert matching
    assert all(hit.sources == ["lexical"] for hit in matching)
