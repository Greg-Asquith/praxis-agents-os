# apps/api/services/agents/runtime/tools/kb.py

"""Audited knowledge-base search and document-reading tools."""

from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext

from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.entity_references.domain import (
    KnowledgeDocumentReference,
    internal_entity_id,
)
from services.agents.runtime.tools import (
    TOOL_EFFECT_READ,
    TOOL_POLICY_AUTO,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import runtime_tool
from services.kb.get_document import get_kb_document
from services.kb.search_chunks import search_chunks

KB_AGENT_SEARCH_DEFAULT_LIMIT = 5


class KnowledgeSearchFilters(BaseModel):
    """Optional visibility-preserving filters for knowledge search."""

    source_types: list[str] | None = None
    private_only: bool = False
    document_ids: list[UUID] | None = None


class ReadRange(BaseModel):
    """A half-open character range in canonical document markdown."""

    start: int = Field(default=0, ge=0)
    end: int | None = Field(default=None, ge=0)


class KnowledgeChunkResult(BaseModel):
    """One model-visible knowledge search hit."""

    document_id: str
    reference: KnowledgeDocumentReference
    document_title: str
    source_type: str
    is_private: bool
    content: str


class SearchKnowledgeOutput(BaseModel):
    """Bounded knowledge search results and degradation state."""

    query: str
    results: list[KnowledgeChunkResult]
    total: int
    used_lexical_fallback: bool
    next_step: str


class ReadDocumentOutput(BaseModel):
    """A bounded character window from one knowledge document."""

    document_id: str
    title: str
    source_type: str
    is_private: bool
    start: int
    end: int
    total_chars: int
    content: str


@runtime_tool(
    name="search_knowledge",
    provider="kb",
    label="Search Knowledge",
    description=(
        "Search this workspace's knowledge base. Returns short snippets ranked "
        "by relevance; call read_document with a result's document_id to read "
        "the full document."
    ),
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=30,
    configurable=False,
    auto_mount=True,
    output_model=SearchKnowledgeOutput,
    presentation=ToolPresentation(
        icon="search",
        running_label="Searching Knowledge for {query}",
        completed_label="Searched Knowledge for {query}",
        failed_label="Couldn't Search Knowledge",
        arg_fields=(
            ToolFieldPresentation(
                key="query",
                label="Search",
                editable=True,
            ),
            ToolFieldPresentation(
                key="limit",
                label="Maximum Matches",
                format="number",
                editable=True,
                secondary=True,
            ),
        ),
        result_fields=(ToolFieldPresentation(key="results", label="Matches", format="list"),),
    ),
)
async def search_knowledge(
    ctx: RunContext[RuntimeDeps],
    query: Annotated[str, Field(description="Terms to search for in workspace knowledge.")],
    filters: KnowledgeSearchFilters | None = None,
    limit: Annotated[
        int,
        Field(
            description=(
                "Maximum matches to return. Values above the configured maximum are safely capped."
            )
        ),
    ] = KB_AGENT_SEARCH_DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Search visible workspace knowledge through the shared hybrid service."""
    normalized_query = query.strip()
    if not normalized_query:
        raise ModelRetry("search_knowledge requires a non-empty query.")
    if limit < 1:
        raise ModelRetry("search_knowledge limit must be at least 1.")

    normalized_limit = min(limit, settings.KB_SEARCH_TOP_K_MAX)
    search_filters = filters or KnowledgeSearchFilters()
    try:
        result = await search_chunks(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            user_id=ctx.deps.user.id,
            query=normalized_query,
            top_k=normalized_limit,
            source_types=search_filters.source_types,
            document_ids=search_filters.document_ids,
            private_only=search_filters.private_only,
        )
    except AppValidationError as exc:
        raise ModelRetry(exc.message) from exc

    hits = [
        {
            "document_id": str(hit.document_id),
            "reference": KnowledgeDocumentReference(
                entity_id=hit.document_id,
                label=hit.title,
                description=(
                    f"{'Private' if hit.is_private else 'Workspace'} · {hit.source_type.title()}"
                ),
            ),
            "document_title": hit.title,
            "source_type": hit.source_type,
            "is_private": hit.is_private,
            "content": hit.content,
        }
        for hit in result.results
    ]
    return {
        "query": result.query,
        "results": hits,
        "total": len(hits),
        "used_lexical_fallback": result.mode == "lexical_fallback",
        "next_step": (
            "Results are snippets: call read_document with a document_id for full context."
            if hits
            else "No matches: retry search_knowledge with different terms or answer without it."
        ),
    }


@runtime_tool(
    name="read_document",
    provider="kb",
    label="Read Knowledge Document",
    description=(
        "Read a knowledge document's canonical markdown by id, optionally using "
        "a character range for long documents."
    ),
    effect=TOOL_EFFECT_READ,
    default_policy=TOOL_POLICY_AUTO,
    takes_ctx=True,
    timeout=15,
    configurable=False,
    auto_mount=True,
    output_model=ReadDocumentOutput,
    presentation=ToolPresentation(
        icon="book",
        running_label="Reading a Knowledge Document",
        completed_label="Read a Knowledge Document",
        failed_label="Couldn't Read the Knowledge Document",
        arg_fields=(
            ToolFieldPresentation(
                key="document_id",
                label="Document",
                format="entity",
                editable=True,
                entity_kind="knowledge_document",
            ),
            ToolFieldPresentation(key="range", label="Character Range", secondary=True),
        ),
        result_fields=(ToolFieldPresentation(key="content", label="Content", format="markdown"),),
    ),
)
async def read_document(
    ctx: RunContext[RuntimeDeps],
    document_id: Annotated[
        KnowledgeDocumentReference,
        Field(description="Knowledge document reference to read."),
    ],
    range: ReadRange | None = None,
) -> dict[str, Any]:
    """Read a bounded window from one visible workspace knowledge document."""
    try:
        document = await get_kb_document(
            ctx.deps.db,
            workspace_id=ctx.deps.workspace.id,
            user_id=ctx.deps.user.id,
            document_id=internal_entity_id(document_id),
        )
    except NotFoundError as exc:
        raise ModelRetry(exc.message) from exc

    content = document.content_md
    if content is None:
        raise ModelRetry(
            "The knowledge document has no readable content yet. "
            "Try again after processing completes."
        )

    requested_range = range or ReadRange()
    total_chars = len(content)
    if requested_range.start >= total_chars:
        raise ModelRetry(
            f"read_document start must be less than the document length ({total_chars})."
        )
    requested_end = requested_range.end if requested_range.end is not None else total_chars
    if requested_end <= requested_range.start:
        raise ModelRetry("read_document range end must be greater than start.")
    end = min(
        requested_end,
        total_chars,
        requested_range.start + settings.KB_READ_DOCUMENT_MAX_CHARS,
    )
    window = content[requested_range.start : end]
    return {
        "document_id": str(document.id),
        "title": document.title,
        "source_type": document.source_type,
        "is_private": document.is_private,
        "start": requested_range.start,
        "end": end,
        "total_chars": total_chars,
        "content": window,
    }
