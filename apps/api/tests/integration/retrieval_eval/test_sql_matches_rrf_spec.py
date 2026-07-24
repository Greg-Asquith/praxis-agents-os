"""Production SQL fusion agrees with the pure weighted RRF specification."""

# ruff: noqa: S608

from collections import defaultdict

import pytest
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import ARRAY, Integer, String, bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from core.settings import settings
from services.kb import search_chunks
from services.kb.domain import KB_COLLECTION_DIMS
from services.kb.search_chunks import _LEXICAL_CTE, _SEMANTIC_CTE
from services.retrieval import RankedId, rrf_merge
from services.retrieval.domain import RRF_K
from tests.integration.retrieval_eval.conftest import RetrievalCorpus
from tests.support.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.asyncio(loop_scope="module")

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
