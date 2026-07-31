# apps/api/services/agents/runtime/entity_references/service.py

"""Authorize tool fields and dispatch entity-reference lookups."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agents.runtime.entity_references.domain import EntityChoice
from services.agents.runtime.entity_references.registry import (
    EntityResolverDefinition,
    get_entity_resolver,
)
from services.agents.runtime.entity_references.schemas import (
    EntityReferenceLookupRequest,
    EntityReferenceLookupResponse,
)
from services.agents.runtime.tools.registry import (
    build_runtime_tools,
    get_runtime_tool_definition,
)
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_independent_operation_audit_event,
)
from services.conversations.utils import get_conversation_for_actor
from services.integrations.context import resolve_active_context
from services.integrations.context.domain import EMPTY_ACTIVE_CONTEXT, ResolvedActiveContext
from services.tools import get_disabled_tools


@dataclass(frozen=True)
class EntityResolverContext:
    db: AsyncSession
    actor: User
    workspace: Workspace
    membership: WorkspaceMembership
    conversation: Conversation
    agent: Agent
    run: AgentRun | None
    active_context: ResolvedActiveContext


@dataclass(frozen=True)
class AuthorizedEntityField:
    context: EntityResolverContext
    resolver: EntityResolverDefinition
    field_key: str
    entity_kind: str
    depends_on: tuple[str, ...]


async def lookup_entity_references(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    conversation_id: UUID,
    payload: EntityReferenceLookupRequest,
) -> EntityReferenceLookupResponse:
    authorized = await authorize_entity_field(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        conversation_id=conversation_id,
        tool_name=payload.tool_name,
        field_key=payload.field_key,
    )
    dependent_args = {key: payload.dependent_args.get(key) for key in authorized.depends_on}
    if payload.exact_values is not None:
        choices = await _resolve_with_failure_audit(
            authorized,
            values=payload.exact_values,
            dependent_args=dependent_args,
        )
        return EntityReferenceLookupResponse(
            entity_kind=authorized.entity_kind,
            choices=list(choices),
        )

    page_size = min(payload.page_size, authorized.resolver.max_page_size)
    page = await _search_with_failure_audit(
        authorized,
        search=payload.search or "",
        dependent_args=dependent_args,
        page_size=page_size,
        cursor=payload.cursor,
    )
    return EntityReferenceLookupResponse(
        entity_kind=authorized.entity_kind,
        choices=list(page.choices),
        next_cursor=page.next_cursor,
    )


async def _search_with_failure_audit(
    authorized: AuthorizedEntityField,
    *,
    search: str,
    dependent_args: dict[str, Any],
    page_size: int,
    cursor: str | None,
):
    try:
        return await authorized.resolver.search(
            authorized.context,
            search,
            dependent_args,
            page_size,
            cursor,
        )
    except Exception as exc:
        await _audit_external_resolver_failure(authorized, operation="search", error=exc)
        raise


async def _resolve_with_failure_audit(
    authorized: AuthorizedEntityField,
    *,
    values: list[Any],
    dependent_args: dict[str, Any],
):
    try:
        return await authorized.resolver.resolve(
            authorized.context,
            values,
            dependent_args,
        )
    except Exception as exc:
        await _audit_external_resolver_failure(authorized, operation="resolve", error=exc)
        raise


async def _audit_external_resolver_failure(
    authorized: AuthorizedEntityField,
    *,
    operation: str,
    error: Exception,
) -> None:
    provider_key = authorized.resolver.provider_key
    if provider_key is None:
        return
    actor = authorized.context.actor
    await safe_record_independent_operation_audit_event(
        workspace_id=authorized.context.workspace.id,
        action=AuditAction.READ,
        resource_type=AuditResourceType.INTEGRATION_RESOURCE,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        status=AuditStatus.FAILURE,
        details={
            "provider_key": provider_key,
            "provider_operation": f"entity_reference_{operation}",
            "entity_kind": authorized.entity_kind,
            "error_code": error.__class__.__name__,
        },
        request=None,
    )


async def resolve_authorized_reference(
    authorized: AuthorizedEntityField,
    *,
    value: Any,
    dependent_args: dict[str, Any],
) -> EntityChoice:
    """Resolve one exact reference or fail closed with a field-specific error."""
    try:
        authorized.resolver.reference_adapter().validate_python(value)
    except ValueError as exc:
        raise AppValidationError(
            "Entity fields must use a selector-issued structured reference",
            field=authorized.field_key,
            details={"entity_kind": authorized.entity_kind},
        ) from exc
    choices = await _resolve_with_failure_audit(
        authorized,
        values=[value],
        dependent_args={key: dependent_args.get(key) for key in authorized.depends_on},
    )
    if len(choices) != 1:
        raise AppValidationError(
            "The selected target is unavailable or no longer accessible",
            field=authorized.field_key,
            details={"entity_kind": authorized.entity_kind},
        )
    return choices[0]


async def resolve_authorized_references(
    authorized: AuthorizedEntityField,
    *,
    values: list[Any],
    dependent_args: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate and canonically hydrate a bounded ordered reference list."""
    validated = []
    for value in values:
        try:
            validated.append(authorized.resolver.reference_adapter().validate_python(value))
        except ValueError as exc:
            raise AppValidationError(
                "Entity fields must use selector-issued structured references",
                field=authorized.field_key,
                details={"entity_kind": authorized.entity_kind},
            ) from exc
    identities = [reference.identity() for reference in validated]
    if len(identities) != len(set(identities)):
        raise AppValidationError(
            "Entity selections must not contain duplicates",
            field=authorized.field_key,
        )
    choices = await _resolve_with_failure_audit(
        authorized,
        values=[reference.model_dump(mode="json") for reference in validated],
        dependent_args={key: dependent_args.get(key) for key in authorized.depends_on},
    )
    by_identity: dict[tuple[str, ...], dict[str, Any]] = {}
    adapter = authorized.resolver.reference_adapter()
    for choice in choices:
        try:
            canonical = adapter.validate_python(choice.value)
        except ValueError:
            continue
        by_identity[canonical.identity()] = choice.value
    if any(identity not in by_identity for identity in identities):
        raise AppValidationError(
            "A selected target is unavailable or no longer accessible",
            field=authorized.field_key,
            details={"entity_kind": authorized.entity_kind},
        )
    return [by_identity[identity] for identity in identities]


async def authorize_entity_field(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    conversation_id: UUID,
    tool_name: str,
    field_key: str,
    run: AgentRun | None = None,
) -> AuthorizedEntityField:
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    if run is not None and (
        run.conversation_id != conversation.id or run.workspace_id != workspace.id or run.deleted
    ):
        raise AppValidationError(
            "Agent run is not available in this conversation",
            field="run_id",
            details={"run_id": str(run.id)},
        )
    if run is None:
        run = await db.scalar(
            select(AgentRun)
            .where(
                AgentRun.conversation_id == conversation.id,
                AgentRun.workspace_id == workspace.id,
                AgentRun.deleted == False,  # noqa: E712
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
    agent_id = run.agent_id if run is not None else conversation.active_agent_id
    if agent_id is None:
        raise NotFoundError("Conversation agent not found", resource_type="agent")
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if agent is None:
        raise NotFoundError(
            "Conversation agent not found",
            resource_type="agent",
            resource_id=str(agent_id),
        )
    active_context = (
        await resolve_active_context(db, run=run, user=actor, workspace=workspace)
        if run is not None
        else EMPTY_ACTIVE_CONTEXT
    )
    disabled = await get_disabled_tools(db, workspace)
    mounted = build_runtime_tools(
        agent,
        include_delegation=bool(agent.allowed_agent_ids),
        active_context=active_context,
        workspace=workspace,
        disabled_tool_names=disabled,
    )
    mounted_names = {tool.name for tool in mounted}
    if tool_name not in mounted_names:
        raise AppValidationError(
            "Tool is not available in this conversation",
            field="tool_name",
            details={"tool_name": tool_name},
        )
    definition = get_runtime_tool_definition(tool_name)
    if definition is None:
        raise AppValidationError("Unknown runtime tool", field="tool_name")
    field = next(
        (
            candidate
            for candidate in definition.presentation.arg_fields
            if candidate.key == field_key
        ),
        None,
    )
    if field is None or field.format not in {"entity", "entity_list"} or field.entity_kind is None:
        raise AppValidationError(
            "Tool field is not an entity reference",
            field="field_key",
            details={"tool_name": tool_name, "field_key": field_key},
        )
    resolver = get_entity_resolver(field.entity_kind)
    if resolver is None:
        raise AppValidationError(
            "Entity resolver is unavailable",
            field="field_key",
            details={"entity_kind": field.entity_kind},
        )
    if resolver.requires_active_context and active_context.is_empty:
        raise AppValidationError(
            "Select a compatible integration context before choosing a target",
            field="field_key",
            details={"entity_kind": field.entity_kind},
        )
    return AuthorizedEntityField(
        context=EntityResolverContext(
            db=db,
            actor=actor,
            workspace=workspace,
            membership=membership,
            conversation=conversation,
            agent=agent,
            run=run,
            active_context=active_context,
        ),
        resolver=resolver,
        field_key=field.key,
        entity_kind=field.entity_kind,
        depends_on=field.depends_on,
    )
