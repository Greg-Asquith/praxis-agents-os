# apps/api/services/memories/search_memories.py

"""Hybrid memory search with scope confinement and lexical degradation."""

import logging
from datetime import UTC, datetime

from sqlalchemy import Float, case, cast, func, literal, select, union_all, update
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.ai_usage.domain import PURPOSE_EMBEDDING_MEMORY_SEARCH
from services.embeddings import embed_texts
from services.embeddings.domain import (
    EmbeddingConfigurationError,
    EmbeddingProvider,
    EmbeddingProviderError,
)
from services.memories.domain import (
    MemoryKind,
    MemoryScope,
    MemorySearchHit,
    MemorySearchResult,
    MemoryType,
)
from services.memories.utils import (
    active_memory_filter,
    effective_confidence,
    scope_filter,
    visible_scope_filter,
)
from services.retrieval import RerankItem, get_reranker
from services.retrieval.domain import RRF_K
from services.retrieval.utils import configure_hnsw_search

logger = logging.getLogger(__name__)
_CTE_LIMIT = 100


async def search_memories(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
    query: str,
    scope: MemoryScope | None = None,
    kind: MemoryKind | None = None,
    memory_type: MemoryType | None = None,
    limit: int | None = None,
    provider: EmbeddingProvider | None = None,
) -> MemorySearchResult:
    """Search active visible memories using weighted reciprocal-rank fusion."""
    normalized_query = query.strip()
    if not normalized_query:
        raise AppValidationError("Memory search query is required", field="query")
    requested_limit = settings.MEMORY_SEARCH_DEFAULT_LIMIT if limit is None else limit
    if requested_limit < 1:
        raise AppValidationError("Memory search limit must be at least one", field="limit")
    result_limit = min(requested_limit, settings.MEMORY_SEARCH_MAX_LIMIT)

    visibility = (
        scope_filter(
            scope,
            workspace_id=workspace.id,
            agent_id=agent.id,
            user_id=user.id,
        )
        if scope is not None
        else visible_scope_filter(
            workspace_id=workspace.id,
            agent_id=agent.id,
            user_id=user.id,
        )
    )
    filters = [visibility, active_memory_filter()]
    if kind is not None:
        filters.append(AgentMemory.kind == kind)
    if memory_type is not None:
        filters.append(AgentMemory.memory_type == memory_type)

    query_vector = None
    embedding_provider = None
    embedding_model = None
    try:
        embedded = await embed_texts(
            db,
            [normalized_query],
            workspace_id=workspace.id,
            purpose=PURPOSE_EMBEDDING_MEMORY_SEARCH,
            agent_id=agent.id,
            user_id=user.id,
            provider=provider,
        )
        query_vector = embedded.vectors[0]
        embedding_provider = embedded.provider
        embedding_model = embedded.model
    except (EmbeddingConfigurationError, EmbeddingProviderError) as exc:
        logger.warning("Memory query embedding failed; using lexical fallback: %s", exc)

    await configure_hnsw_search(
        db,
        ef_search=settings.MEMORY_SEARCH_EF_SEARCH,
    )

    ts_query = func.websearch_to_tsquery("english", normalized_query)
    lexical_score = func.ts_rank_cd(AgentMemory.content_tsv, ts_query)
    lexical = (
        select(
            AgentMemory.id.label("id"),
            func.row_number().over(order_by=(lexical_score.desc(), AgentMemory.id)).label("rank"),
            literal("lexical").label("source"),
        )
        .where(*filters, AgentMemory.content_tsv.op("@@")(ts_query))
        .order_by(lexical_score.desc(), AgentMemory.id)
        .limit(_CTE_LIMIT)
        .cte("lexical")
    )
    ranked_selects = [select(lexical.c.id, lexical.c.rank, lexical.c.source)]
    if query_vector is not None:
        distance = AgentMemory.embedding.cosine_distance(query_vector)
        semantic = (
            select(
                AgentMemory.id.label("id"),
                func.row_number().over(order_by=(distance, AgentMemory.id)).label("rank"),
                literal("semantic").label("source"),
            )
            .where(
                *filters,
                AgentMemory.embedding.is_not(None),
                AgentMemory.embedding_dims == len(query_vector),
                AgentMemory.embedding_provider == embedding_provider,
                AgentMemory.embedding_model == embedding_model,
            )
            .order_by(distance, AgentMemory.id)
            .limit(_CTE_LIMIT)
            .cte("semantic")
        )
        ranked_selects.append(select(semantic.c.id, semantic.c.rank, semantic.c.source))

    ranked = union_all(*ranked_selects).cte("ranked")
    fused = (
        select(
            ranked.c.id,
            func.sum(1.0 / (RRF_K + cast(ranked.c.rank, Float))).label("score"),
            func.array_agg(aggregate_order_by(ranked.c.source, ranked.c.source)).label("sources"),
        )
        .group_by(ranked.c.id)
        .cte("fused")
    )
    age_days = func.greatest(
        0.0,
        func.extract(
            "epoch",
            func.now()
            - func.coalesce(
                AgentMemory.last_reinforced_at,
                AgentMemory.created_at,
            ),
        )
        / 86_400.0,
    )
    decay_rate = case(
        (
            AgentMemory.memory_type == "preference",
            settings.MEMORY_DECAY_RATE_PREFERENCE,
        ),
        (
            AgentMemory.memory_type == "episode",
            settings.MEMORY_DECAY_RATE_EPISODE,
        ),
        (
            AgentMemory.memory_type == "outcome",
            settings.MEMORY_DECAY_RATE_OUTCOME,
        ),
        else_=settings.MEMORY_DECAY_RATE_FACT,
    )
    sql_confidence = case(
        (AgentMemory.kind == "core", AgentMemory.confidence),
        else_=func.greatest(
            settings.MEMORY_CONFIDENCE_FLOOR,
            AgentMemory.confidence * func.exp(-decay_rate * age_days),
        ),
    )
    ranked_score = (fused.c.score * sql_confidence).label("score")
    rows = (
        await db.execute(
            select(AgentMemory, ranked_score, fused.c.sources)
            .join(fused, fused.c.id == AgentMemory.id)
            .order_by(ranked_score.desc(), AgentMemory.id)
            .limit(result_limit)
        )
    ).all()
    now = datetime.now(UTC)
    hits = [
        MemorySearchHit(
            memory=memory,
            score=float(score),
            sources=tuple(sources),
            effective_confidence=effective_confidence(memory, now=now),
        )
        for memory, score, sources in rows
    ]
    reranker = get_reranker()
    if reranker is not None and hits:
        reranked = await reranker.rerank(
            normalized_query,
            [
                RerankItem(
                    id=hit.memory.id,
                    content=hit.memory.content_md,
                    score=hit.score,
                )
                for hit in hits
            ],
        )
        hits_by_id = {hit.memory.id: hit for hit in hits}
        hits = [hits_by_id[item.id] for item in reranked if item.id in hits_by_id]

    if hits:
        await db.execute(
            update(AgentMemory)
            .where(AgentMemory.id.in_([hit.memory.id for hit in hits]))
            .values(
                access_count=AgentMemory.access_count + 1,
                last_accessed_at=now,
            )
        )
    return MemorySearchResult(
        query=normalized_query,
        results=hits,
        mode="hybrid" if query_vector is not None else "lexical_fallback",
    )
