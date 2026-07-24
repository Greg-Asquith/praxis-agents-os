"""Workspace, privacy, and soft-delete security invariants."""

import pytest

from core.exceptions.general import NotFoundError
from services.kb import get_kb_document, search_chunks
from tests.integration.retrieval_eval.cases import CASES
from tests.integration.retrieval_eval.conftest import RetrievalCorpus
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_every_case_stays_inside_its_workspace(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    for case in CASES:
        primary = await search_chunks(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.creator.id,
            query=case.query,
            provider=FakeEmbeddingProvider(),
        )
        isolated = await search_chunks(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.isolation_workspace.id,
            user_id=retrieval_corpus.isolation_user.id,
            query=case.query,
            provider=FakeEmbeddingProvider(),
        )
        assert retrieval_corpus.isolation_document.id not in {
            hit.document_id for hit in primary.results
        }
        assert not (retrieval_corpus.document_ids & {hit.document_id for hit in isolated.results})

    beacon = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.isolation_workspace.id,
        user_id=retrieval_corpus.isolation_user.id,
        query="ISOLATED-WORKSPACE-BEACON",
        provider=FakeEmbeddingProvider(),
    )
    crossed = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="ISOLATED-WORKSPACE-BEACON",
        provider=FakeEmbeddingProvider(),
    )
    assert beacon.results[0].document_id == retrieval_corpus.isolation_document.id
    assert retrieval_corpus.isolation_document.id not in {
        hit.document_id for hit in crossed.results
    }


async def test_private_document_is_visible_only_to_its_creator(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    creator_result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="PRIVATE-CREATOR-CODE",
        private_only=True,
        provider=FakeEmbeddingProvider(),
    )
    other_result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.other_user.id,
        query="PRIVATE-CREATOR-CODE",
        private_only=True,
        provider=FakeEmbeddingProvider(),
    )

    assert {hit.document_id for hit in creator_result.results} == {
        retrieval_corpus.private_document.id
    }
    assert all(hit.is_private for hit in creator_result.results)
    assert other_result.results == []

    creator_document = await get_kb_document(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        document_id=retrieval_corpus.private_document.id,
    )
    assert creator_document.id == retrieval_corpus.private_document.id
    with pytest.raises(NotFoundError):
        await get_kb_document(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.other_user.id,
            document_id=retrieval_corpus.private_document.id,
        )


async def test_soft_delete_removes_chunks_before_retention_sweep(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    document = retrieval_corpus.documents["pricing_policy.md"]
    before = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="volume discount tiers",
        provider=FakeEmbeddingProvider(),
    )
    assert document.id in {hit.document_id for hit in before.results}

    document.soft_delete(deleted_by=retrieval_corpus.creator.id, cascade=False)
    await retrieval_corpus.db.flush()
    after = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="volume discount tiers",
        provider=FakeEmbeddingProvider(),
    )
    assert document.id not in {hit.document_id for hit in after.results}
