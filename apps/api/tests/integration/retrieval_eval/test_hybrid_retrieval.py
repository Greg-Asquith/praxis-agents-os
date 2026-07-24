"""Gate G4 relevance containment assertions at the written search defaults."""

import pytest

from services.kb import search_chunks
from tests.integration.retrieval_eval.cases import CASES
from tests.integration.retrieval_eval.conftest import RetrievalCorpus
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_pinned_retrieval_cases_meet_the_gate_g4_scoreboard(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    actual_ranks: dict[str, int | None] = {}

    for case in CASES:
        result = await search_chunks(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.creator.id,
            query=case.query,
            top_k=max(case.within_top, 10),
            provider=FakeEmbeddingProvider(),
        )
        expected_id = retrieval_corpus.documents[case.expect_doc].id
        rank = next(
            (
                index
                for index, hit in enumerate(result.results, start=1)
                if hit.document_id == expected_id
            ),
            None,
        )
        actual_ranks[case.query] = rank
        assert result.mode == "hybrid"
        assert rank is not None and rank <= case.within_top, actual_ranks

    assert actual_ranks["WireGuard configuration"] == 1
    assert actual_ranks["EXP-REIMBURSE-90"] == 1


async def test_overlap_query_wins_with_both_relevance_lists(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="new starter first week secure access internal services",
        provider=FakeEmbeddingProvider(),
    )

    expected = retrieval_corpus.documents["onboarding_guide.md"]
    assert result.results[0].document_id == expected.id
    assert {"lexical", "semantic"}.issubset(result.results[0].sources)
