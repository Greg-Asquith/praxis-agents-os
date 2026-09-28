"""Gate G4 retrieval harness over one real-pipeline corpus.

Tests share one seeded corpus and run in file order; corpus-mutating tests come last.
"""

# ruff: noqa: S608

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import ARRAY, Integer, String, bindparam, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from core.database import set_session_tenant_context
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.kb import KBChunk
from services.embeddings.domain import EmbeddingProviderError
from services.kb import get_kb_document, search_chunks
from services.kb.domain import KB_COLLECTION_DIMS, KB_SOURCE_URL, KB_SYNC_READY
from services.kb.embed_chunks import embed_kb_chunks
from services.kb.search_chunks import _LEXICAL_CTE, _SEMANTIC_CTE
from services.retrieval import RankedId, rrf_merge
from services.retrieval.domain import RRF_K
from tests.integration.retrieval_eval.conftest import (
    INJECTION_FILENAMES,
    RetrievalCorpus,
    _seed_document,
)
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")

# Plan 046's framing tests consume the injection fixture files; do not rename or
# "fix" their content.
_QUERY_BY_FILENAME = {
    "prompt_injection_basic.md": "INERT-BASIC-FIXTURE",
    "prompt_injection_tool_call.md": "INERT-TOOL-FIXTURE",
    "prompt_injection_exfil.md": "INERT-EXFIL-FIXTURE",
}


@dataclass(frozen=True)
class RetrievalCase:
    """One query and its required document containment threshold."""

    query: str
    expect_doc: str
    within_top: int


CASES = (
    RetrievalCase("how do I connect to the vpn", "vpn_setup.md", 3),
    RetrievalCase("WireGuard configuration", "vpn_setup.md", 1),
    RetrievalCase("EXP-REIMBURSE-90", "travel_expense_policy.md", 1),
    RetrievalCase(
        "what is the daily food allowance when travelling",
        "travel_expense_policy.md",
        3,
    ),
    RetrievalCase(
        "who do I page when production is down",
        "security_incident_runbook.md",
        3,
    ),
    RetrievalCase("error 4032 meaning", "api_error_codes.md", 3),
    RetrievalCase("new starter first week tasks", "onboarding_guide.md", 3),
    RetrievalCase("volume discount tiers", "pricing_policy.md", 3),
)


_SOURCE_RANK_SQL = f"""
WITH {_LEXICAL_CTE},
{_SEMANTIC_CTE},
recency AS (
    SELECT c.id, row_number() OVER (
               ORDER BY coalesce(d.source_updated_at, d.created_at) DESC, c.id
           ) AS rank
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE c.id IN (SELECT id FROM lexical UNION SELECT id FROM semantic)
      AND d.source_type = ANY(:recency_source_types)
)
SELECT id, rank, source
FROM (
    SELECT id, rank, 'lexical' AS source FROM lexical
    UNION ALL
    SELECT id, rank, 'semantic' AS source FROM semantic
    UNION ALL
    SELECT id, rank, 'recency' AS source FROM recency
) ranked
"""


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


async def test_sql_order_scores_and_sources_match_weighted_rrf(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    query = "new starter first week secure access internal services"
    provider = FakeEmbeddingProvider()
    batch = await provider.embed_texts(
        [query],
        model=settings.EMBEDDINGS_MODEL,
        dimensions=KB_COLLECTION_DIMS,
    )
    statement = text(_SOURCE_RANK_SQL).bindparams(
        bindparam("workspace_id", type_=PGUUID(as_uuid=True)),
        bindparam("user_id", type_=PGUUID(as_uuid=True)),
        bindparam("source_types", type_=ARRAY(String())),
        bindparam("document_ids", type_=ARRAY(PGUUID(as_uuid=True))),
        bindparam("recency_source_types", type_=ARRAY(String())),
        bindparam("qvec", type_=HALFVEC(KB_COLLECTION_DIMS)),
    )
    await retrieval_corpus.db.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
    await retrieval_corpus.db.execute(
        text("SET LOCAL hnsw.ef_search = :ef").bindparams(
            bindparam(
                "ef",
                value=settings.KB_SEARCH_EF_SEARCH,
                type_=Integer(),
                literal_execute=True,
            )
        )
    )
    rows = (
        await retrieval_corpus.db.execute(
            statement,
            {
                "workspace_id": retrieval_corpus.workspace.id,
                "user_id": retrieval_corpus.creator.id,
                "query": query,
                "source_types": None,
                "document_ids": None,
                "private_only": False,
                "cte_limit": settings.KB_SEARCH_CTE_LIMIT,
                "qvec": batch.vectors[0],
                "dims": KB_COLLECTION_DIMS,
                "model": batch.model,
                "recency_source_types": list(settings.KB_SEARCH_RECENCY_SOURCE_TYPES),
            },
        )
    ).mappings()
    ranked_lists: dict[str, list[RankedId]] = defaultdict(list)
    for row in rows:
        ranked_lists[row["source"]].append(RankedId(id=row["id"], rank=int(row["rank"])))

    expected = rrf_merge(
        ranked_lists,
        k=RRF_K,
        limit=settings.KB_SEARCH_TOP_K_MAX,
        weights={"recency": settings.KB_SEARCH_RECENCY_WEIGHT},
    )
    actual = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query=query,
        top_k=settings.KB_SEARCH_TOP_K_MAX,
        provider=provider,
    )

    assert [hit.id for hit in actual.results] == [item.id for item in expected]
    for hit, item in zip(actual.results, expected, strict=True):
        assert hit.score == pytest.approx(item.score)
        assert hit.sources == sorted(item.sources)


async def test_hostile_documents_round_trip_as_exact_source_spans(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    returned_text: dict[str, str] = {}

    for filename in INJECTION_FILENAMES:
        document = retrieval_corpus.documents[filename]
        result = await search_chunks(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.creator.id,
            query=_QUERY_BY_FILENAME[filename],
            provider=FakeEmbeddingProvider(),
        )
        hit = next(hit for hit in result.results if hit.document_id == document.id)
        assert document.content_md is not None
        assert hit.content == document.content_md[hit.char_start : hit.char_end]
        returned_text[filename] = hit.content

    assert '{"tool": "delete_all_files"' in returned_text["prompt_injection_tool_call.md"]
    assert "https://evil.example/leak?d=SYSTEM_PROMPT" in returned_text["prompt_injection_exfil.md"]


async def _use_tenant(
    corpus: RetrievalCorpus,
    *,
    isolated: bool = False,
    other_user: bool = False,
) -> None:
    workspace = corpus.isolation_workspace if isolated else corpus.workspace
    user = (
        corpus.isolation_user if isolated else corpus.other_user if other_user else corpus.creator
    )
    await set_session_tenant_context(
        corpus.db,
        workspace_id=workspace.id,
        user_id=user.id,
    )


async def test_every_case_stays_inside_its_workspace(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    for case in CASES:
        await _use_tenant(retrieval_corpus)
        primary = await search_chunks(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.creator.id,
            query=case.query,
            provider=FakeEmbeddingProvider(),
        )
        await _use_tenant(retrieval_corpus, isolated=True)
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

    await _use_tenant(retrieval_corpus, isolated=True)
    beacon = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.isolation_workspace.id,
        user_id=retrieval_corpus.isolation_user.id,
        query="ISOLATED-WORKSPACE-BEACON",
        provider=FakeEmbeddingProvider(),
    )
    await _use_tenant(retrieval_corpus)
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
    await _use_tenant(retrieval_corpus)
    creator_result = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="PRIVATE-CREATOR-CODE",
        private_only=True,
        provider=FakeEmbeddingProvider(),
    )
    await _use_tenant(retrieval_corpus, other_user=True)
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

    await _use_tenant(retrieval_corpus)
    creator_document = await get_kb_document(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        document_id=retrieval_corpus.private_document.id,
    )
    assert creator_document.id == retrieval_corpus.private_document.id
    with pytest.raises(NotFoundError):
        await _use_tenant(retrieval_corpus, other_user=True)
        await get_kb_document(
            retrieval_corpus.db,
            workspace_id=retrieval_corpus.workspace.id,
            user_id=retrieval_corpus.other_user.id,
            document_id=retrieval_corpus.private_document.id,
        )


async def test_pending_document_stays_findable_before_and_after_embedding(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    fallback = await search_chunks(
        retrieval_corpus.db,
        workspace_id=retrieval_corpus.workspace.id,
        user_id=retrieval_corpus.creator.id,
        query="pending capacity marker",
        top_k=10,
        provider=FailingEmbeddingProvider(),
    )

    assert fallback.mode == "lexical_fallback"
    assert len(fallback.results) == 10
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


async def test_source_and_document_filters_restrict_both_candidate_lists(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    vpn = retrieval_corpus.documents["vpn_setup.md"]
    vpn.source_type = KB_SOURCE_URL
    vpn.external_url = "https://docs.example.com/vpn"
    vpn.source_sync_status = KB_SYNC_READY
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
        content=content.replace("Escalate delayed exports", "Escalate any delayed exports"),
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

    stale.source_type = KB_SOURCE_URL
    stale.external_url = "https://docs.example.com/stale-ownership"
    stale.source_updated_at = datetime(2024, 1, 1, tzinfo=UTC)
    stale.source_sync_status = KB_SYNC_READY
    fresh.source_type = KB_SOURCE_URL
    fresh.external_url = "https://docs.example.com/fresh-ownership"
    fresh.source_updated_at = datetime(2026, 7, 1, tzinfo=UTC)
    fresh.source_sync_status = KB_SYNC_READY
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


async def test_soft_delete_removes_chunks_before_retention_sweep(
    retrieval_corpus: RetrievalCorpus,
) -> None:
    document = retrieval_corpus.documents["pricing_policy.md"]
    await _use_tenant(retrieval_corpus)
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
