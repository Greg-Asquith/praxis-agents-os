# apps/api/services/agents/runtime/entity_references/internal.py

"""Authorized resolvers for workspace-owned runtime entities."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select

from models.agent import Agent
from models.agent_memories import AgentMemory
from models.artifacts import Artifact
from models.files import File
from models.kb import KBDocument
from services.agents.runtime.delegation.list_visible_delegate_agents import (
    list_visible_delegate_agents,
)
from services.agents.runtime.entity_references.domain import (
    AgentReference,
    ArtifactReference,
    EntityChoice,
    EntityResolverPage,
    FileReference,
    KnowledgeDocumentReference,
    MemoryReference,
)
from services.agents.runtime.entity_references.registry import (
    EntityResolverDefinition,
    register_entity_resolver,
)
from services.memories.authorisation import visible_memory_filter


def register_internal_entity_resolvers() -> None:
    definitions = (
        EntityResolverDefinition(
            entity_kind="agent",
            reference_type=AgentReference,
            search=_search_agents,
            resolve=_resolve_agents,
        ),
        EntityResolverDefinition(
            entity_kind="memory",
            reference_type=MemoryReference,
            search=_search_memories,
            resolve=_resolve_memories,
        ),
        EntityResolverDefinition(
            entity_kind="artifact",
            reference_type=ArtifactReference,
            search=_search_artifacts,
            resolve=_resolve_artifacts,
        ),
        EntityResolverDefinition(
            entity_kind="knowledge_document",
            reference_type=KnowledgeDocumentReference,
            search=_search_documents,
            resolve=_resolve_documents,
        ),
        EntityResolverDefinition(
            entity_kind="file",
            reference_type=FileReference,
            search=_search_files,
            resolve=_resolve_files,
        ),
    )
    for definition in definitions:
        register_entity_resolver(definition)


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return max(value, 0)


def _pattern(search: str) -> str | None:
    normalized = search.strip()
    if not normalized:
        return None
    escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _ids(values: Sequence[Any], *, kind: str) -> set[UUID]:
    resolved: set[UUID] = set()
    for value in values:
        raw = value.get("entity_id") if isinstance(value, Mapping) else value
        try:
            reference_id = UUID(str(raw))
        except (TypeError, ValueError):
            continue
        if isinstance(value, Mapping) and value.get("entity_kind") not in {None, kind}:
            continue
        resolved.add(reference_id)
    return resolved


def _page(choices: list[EntityChoice], *, offset: int, page_size: int) -> EntityResolverPage:
    has_more = len(choices) > page_size
    return EntityResolverPage(
        choices=tuple(choices[:page_size]),
        next_cursor=str(offset + page_size) if has_more else None,
    )


async def _search_agents(ctx, search, _dependent_args, page_size, cursor):
    offset = _offset(cursor)
    agents = await list_visible_delegate_agents(
        ctx.db,
        caller=ctx.agent,
        workspace=ctx.workspace,
    )
    pattern = search.strip().casefold()
    filtered = [
        agent
        for agent in agents
        if not pattern
        or pattern in agent.name.casefold()
        or pattern in (agent.description or "").casefold()
    ]
    selected = filtered[offset : offset + page_size + 1]
    return _page([_agent_choice(agent) for agent in selected], offset=offset, page_size=page_size)


async def _resolve_agents(ctx, values, _dependent_args):
    wanted = _ids(values, kind="agent")
    if not wanted:
        return ()
    visible = await list_visible_delegate_agents(ctx.db, caller=ctx.agent, workspace=ctx.workspace)
    by_id = {agent.id: agent for agent in visible}
    return tuple(
        _agent_choice(by_id[reference_id]) for reference_id in wanted if reference_id in by_id
    )


def _agent_choice(agent: Agent) -> EntityChoice:
    return EntityChoice.from_reference(
        AgentReference(
            entity_id=agent.id,
            label=agent.name,
            description=(agent.description or "Delegate agent")[:1000],
        ),
        icon="bot",
    )


async def _search_memories(ctx, search, _dependent_args, page_size, cursor):
    offset = _offset(cursor)
    filters = [
        visible_memory_filter(workspace_id=ctx.workspace.id, user_id=ctx.actor.id),
        AgentMemory.status == "active",
    ]
    pattern = _pattern(search)
    if pattern:
        filters.append(
            or_(
                AgentMemory.title.ilike(pattern, escape="\\"),
                AgentMemory.content_md.ilike(pattern, escape="\\"),
            )
        )
    rows = list(
        await ctx.db.scalars(
            select(AgentMemory)
            .where(*filters)
            .order_by(AgentMemory.updated_at.desc(), AgentMemory.id.desc())
            .limit(page_size + 1)
            .offset(offset)
        )
    )
    return _page([_memory_choice(row) for row in rows], offset=offset, page_size=page_size)


async def _resolve_memories(ctx, values, _dependent_args):
    wanted = _ids(values, kind="memory")
    if not wanted:
        return ()
    rows = list(
        await ctx.db.scalars(
            select(AgentMemory).where(
                AgentMemory.id.in_(wanted),
                visible_memory_filter(workspace_id=ctx.workspace.id, user_id=ctx.actor.id),
                AgentMemory.status == "active",
            )
        )
    )
    return tuple(_memory_choice(row) for row in rows)


def _memory_choice(memory: AgentMemory) -> EntityChoice:
    return EntityChoice.from_reference(
        MemoryReference(
            entity_id=memory.id,
            label=memory.title,
            description=f"{memory.memory_type.title()} · {memory.scope.title()} memory",
        ),
        icon="book",
    )


async def _search_artifacts(ctx, search, _dependent_args, page_size, cursor):
    offset = _offset(cursor)
    filters = [Artifact.workspace_id == ctx.workspace.id, Artifact.deleted.is_(False)]
    pattern = _pattern(search)
    if pattern:
        filters.append(Artifact.title.ilike(pattern, escape="\\"))
    rows = list(
        await ctx.db.scalars(
            select(Artifact)
            .where(*filters)
            .order_by(Artifact.updated_at.desc(), Artifact.id.desc())
            .limit(page_size + 1)
            .offset(offset)
        )
    )
    return _page([_artifact_choice(row) for row in rows], offset=offset, page_size=page_size)


async def _resolve_artifacts(ctx, values, _dependent_args):
    wanted = _ids(values, kind="artifact")
    rows = (
        list(
            await ctx.db.scalars(
                select(Artifact).where(
                    Artifact.id.in_(wanted),
                    Artifact.workspace_id == ctx.workspace.id,
                    Artifact.deleted.is_(False),
                )
            )
        )
        if wanted
        else []
    )
    return tuple(_artifact_choice(row) for row in rows)


def _artifact_choice(artifact: Artifact) -> EntityChoice:
    return EntityChoice.from_reference(
        ArtifactReference(
            entity_id=artifact.id,
            label=artifact.title,
            description=f"{artifact.artifact_type.title()} artifact",
        ),
        icon="file",
    )


async def _search_documents(ctx, search, _dependent_args, page_size, cursor):
    offset = _offset(cursor)
    filters = [
        KBDocument.workspace_id == ctx.workspace.id,
        KBDocument.deleted.is_(False),
        or_(KBDocument.is_private.is_(False), KBDocument.created_by_user_id == ctx.actor.id),
    ]
    pattern = _pattern(search)
    if pattern:
        filters.append(
            or_(
                KBDocument.title.ilike(pattern, escape="\\"),
                KBDocument.summary.ilike(pattern, escape="\\"),
            )
        )
    rows = list(
        await ctx.db.scalars(
            select(KBDocument)
            .where(*filters)
            .order_by(KBDocument.updated_at.desc(), KBDocument.id.desc())
            .limit(page_size + 1)
            .offset(offset)
        )
    )
    return _page([_document_choice(row) for row in rows], offset=offset, page_size=page_size)


async def _resolve_documents(ctx, values, _dependent_args):
    wanted = _ids(values, kind="knowledge_document")
    rows = (
        list(
            await ctx.db.scalars(
                select(KBDocument).where(
                    KBDocument.id.in_(wanted),
                    KBDocument.workspace_id == ctx.workspace.id,
                    KBDocument.deleted.is_(False),
                    or_(
                        KBDocument.is_private.is_(False),
                        KBDocument.created_by_user_id == ctx.actor.id,
                    ),
                )
            )
        )
        if wanted
        else []
    )
    return tuple(_document_choice(row) for row in rows)


def _document_choice(document: KBDocument) -> EntityChoice:
    privacy = "Private" if document.is_private else "Workspace"
    return EntityChoice.from_reference(
        KnowledgeDocumentReference(
            entity_id=document.id,
            label=document.title,
            description=f"{privacy} · {document.source_type.title()} · {document.status.title()}",
        ),
        icon="book",
    )


async def _search_files(ctx, search, _dependent_args, page_size, cursor):
    offset = _offset(cursor)
    filters = [File.workspace_id == ctx.workspace.id, File.deleted.is_(False)]
    pattern = _pattern(search)
    if pattern:
        filters.append(File.name.ilike(pattern, escape="\\"))
    rows = list(
        await ctx.db.scalars(
            select(File)
            .where(*filters)
            .order_by(File.updated_at.desc(), File.id.desc())
            .limit(page_size + 1)
            .offset(offset)
        )
    )
    return _page([_file_choice(row) for row in rows], offset=offset, page_size=page_size)


async def _resolve_files(ctx, values, _dependent_args):
    wanted = _ids(values, kind="file")
    rows = (
        list(
            await ctx.db.scalars(
                select(File).where(
                    File.id.in_(wanted),
                    File.workspace_id == ctx.workspace.id,
                    File.deleted.is_(False),
                )
            )
        )
        if wanted
        else []
    )
    return tuple(_file_choice(row) for row in rows)


def _file_choice(file: File) -> EntityChoice:
    return EntityChoice.from_reference(
        FileReference(
            entity_id=file.id,
            label=file.name,
            description=f"{file.category.title()} · {file.size_bytes:,} bytes",
        ),
        icon="file",
    )
