# apps/api/services/kb/search_chunks.py

"""Hybrid knowledge-base chunk search."""

# ruff: noqa: S608

import logging
from collections.abc import Sequence
from uuid import UUID

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import ARRAY, String, bindparam, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.ai_usage.domain import PURPOSE_EMBEDDING_KB_SEARCH
from services.embeddings import embed_texts
from services.embeddings.domain import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
)
from services.kb.domain import ANNOTATION_DEFAULTS, KB_COLLECTION_DIMS
from services.kb.schemas import KBSearchHit, KBSearchResult
from services.retrieval import RerankItem, get_reranker
from services.retrieval.domain import RRF_K
from services.retrieval.utils import configure_hnsw_search

logger = logging.getLogger(__name__)

_VISIBILITY_FILTERS = """
      AND c.workspace_id = :workspace_id
      AND d.deleted_at IS NULL
      AND (NOT d.is_private OR d.created_by_user_id = :user_id)
      AND (NOT :private_only OR d.is_private)
      AND (:source_types IS NULL OR d.source_type = ANY(:source_types))
      AND (:document_ids IS NULL OR c.document_id = ANY(:document_ids))
"""

_LEXICAL_CTE = f"""
lexical AS (
    SELECT c.id, row_number() OVER (
               ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', :query)) DESC,
                        c.id
           ) AS rank
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE c.tsv @@ websearch_to_tsquery('english', :query)
{_VISIBILITY_FILTERS}
    ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', :query)) DESC, c.id
    LIMIT :cte_limit
)
"""

_SEMANTIC_CTE = f"""
semantic AS (
    SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> :qvec, c.id) AS rank
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE c.embedding IS NOT NULL
      AND c.embedding_dims = :dims
      AND c.embedding_model = :model
{_VISIBILITY_FILTERS}
    ORDER BY c.embedding <=> :qvec, c.id
    LIMIT :cte_limit
)
"""

_FINAL_SELECT = """
SELECT c.id, c.document_id, c.chunk_index, c.content, c.context_line,
       c.char_start, c.char_end, c.meta, c.embedding IS NULL AS pending_embedding,
       d.title, d.source_type, d.external_url, d.is_private,
       f.score, f.sources
FROM fused f
JOIN kb_chunks c ON c.id = f.id
JOIN kb_documents d ON d.id = c.document_id
ORDER BY f.score DESC, c.id
LIMIT :top_k
"""


def _build_search_sql(*, semantic: bool) -> str:
    source_ctes = f"{_LEXICAL_CTE},\n{_SEMANTIC_CTE}" if semantic else _LEXICAL_CTE
    candidate_query = (
        "SELECT id FROM lexical UNION SELECT id FROM semantic"
        if semantic
        else ("SELECT id FROM lexical")
    )
    semantic_row = (
        "\n        UNION ALL\n"
        "        SELECT id, rank, 1.0 AS weight, 'semantic' AS source FROM semantic"
        if semantic
        else ""
    )
    return f"""
WITH {source_ctes},
recency AS (
    SELECT c.id, row_number() OVER (
               ORDER BY coalesce(d.source_updated_at, d.created_at) DESC, c.id
           ) AS rank
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE c.id IN ({candidate_query})
      AND d.source_type = ANY(:recency_source_types)
),
fused AS (
    SELECT id, sum(weight / (:rrf_k + rank)) AS score,
           array_agg(source ORDER BY source) AS sources
    FROM (
        SELECT id, rank, 1.0 AS weight, 'lexical' AS source FROM lexical{semantic_row}
        UNION ALL
        SELECT id, rank, CAST(:recency_weight AS float) AS weight,
               'recency' AS source FROM recency
    ) ranked
    GROUP BY id
)
{_FINAL_SELECT}
"""


_HYBRID_SEARCH_SQL = _build_search_sql(semantic=True)
_LEXICAL_SEARCH_SQL = _build_search_sql(semantic=False)


def _statement(*, semantic: bool):
    statement = text(_HYBRID_SEARCH_SQL if semantic else _LEXICAL_SEARCH_SQL).bindparams(
        bindparam("source_types", type_=ARRAY(String())),
        bindparam("document_ids", type_=ARRAY(PGUUID(as_uuid=True))),
        bindparam("recency_source_types", type_=ARRAY(String())),
    )
    if semantic:
        statement = statement.bindparams(
            bindparam("qvec", type_=HALFVEC(KB_COLLECTION_DIMS)),
        )
    return statement


async def search_chunks(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    agent_id: UUID | None = None,
    query: str,
    top_k: int | None = None,
    source_types: Sequence[str] | None = None,
    document_ids: Sequence[UUID] | None = None,
    private_only: bool = False,
    provider: EmbeddingProvider | None = None,
) -> KBSearchResult:
    """Search visible chunks with weighted hybrid RRF and lexical degradation."""
    normalized_query = query.strip()
    if not normalized_query:
        raise AppValidationError("Search query is required", field="query")
    if len(normalized_query) > 1_000:
        raise AppValidationError(
            "Search query exceeds the character limit",
            field="query",
            details={"max_characters": 1_000},
        )

    normalized_sources = list(dict.fromkeys(source_types or [])) or None
    invalid_sources = sorted(set(normalized_sources or ()) - ANNOTATION_DEFAULTS.keys())
    if invalid_sources:
        raise AppValidationError(
            "Knowledge-base source type is invalid",
            field="source_types",
            details={"invalid_source_types": invalid_sources},
        )
    normalized_document_ids = list(dict.fromkeys(document_ids or [])) or None
    requested_limit = settings.KB_SEARCH_TOP_K_DEFAULT if top_k is None else top_k
    result_limit = max(
        1,
        min(requested_limit, settings.KB_SEARCH_TOP_K_MAX),
    )

    query_vector: list[float] | None
    embedding_model: str | None
    try:
        embedded = await embed_texts(
            db,
            [normalized_query],
            workspace_id=workspace_id,
            purpose=PURPOSE_EMBEDDING_KB_SEARCH,
            agent_id=agent_id,
            user_id=user_id,
            provider=provider,
        )
        query_vector = embedded.vectors[0]
        embedding_model = embedded.model
    except (EmbeddingConfigurationError, EmbeddingProviderError) as exc:
        logger.warning(
            "Knowledge-base query embedding failed; using lexical fallback: %s",
            exc,
        )
        query_vector = None
        embedding_model = None

    await configure_hnsw_search(
        db,
        ef_search=settings.KB_SEARCH_EF_SEARCH,
    )

    params = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "query": normalized_query,
        "source_types": normalized_sources,
        "document_ids": normalized_document_ids,
        "private_only": private_only,
        "cte_limit": settings.KB_SEARCH_CTE_LIMIT,
        "rrf_k": RRF_K,
        "top_k": result_limit,
        "recency_weight": settings.KB_SEARCH_RECENCY_WEIGHT,
        "recency_source_types": list(settings.KB_SEARCH_RECENCY_SOURCE_TYPES),
    }
    if query_vector is not None:
        params.update(
            {
                "qvec": query_vector,
                "dims": KB_COLLECTION_DIMS,
                "model": embedding_model,
            }
        )

    rows = (
        await db.execute(
            _statement(semantic=query_vector is not None),
            params,
        )
    ).mappings()
    hits = [KBSearchHit.model_validate(dict(row)) for row in rows]

    reranker = get_reranker()
    if reranker is not None and hits:
        reranked = await reranker.rerank(
            normalized_query,
            [RerankItem(id=hit.id, content=hit.content, score=hit.score) for hit in hits],
        )
        hits_by_id = {hit.id: hit for hit in hits}
        hits = [hits_by_id[item.id] for item in reranked if item.id in hits_by_id]

    return KBSearchResult(
        results=hits,
        mode="hybrid" if query_vector is not None else "lexical_fallback",
        query=normalized_query,
    )
