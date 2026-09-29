# apps/api/services/agents/update_agent.py

"""Update a workspace-scoped agent."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.agent import Agent
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agents.runtime.tools.workspace_tools import (
    RESERVED_WORKSPACE_TOOL_PREFIXES,
    load_workspace_tool_definitions,
    workspace_tool_names,
)
from services.agents.schemas import AgentRead, AgentUpdateRequest
from services.agents.utils import (
    ToolSelection,
    get_agent_for_workspace,
    is_agent_slug_integrity_error,
    normalize_tool_selection,
    require_agent_write_access,
    validate_agent_references,
    validate_model_configuration,
)
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from utils.slugify import slugify


async def update_agent(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    agent_id: UUID,
    payload: AgentUpdateRequest,
) -> AgentRead:
    require_agent_write_access(membership)
    agent = await get_agent_for_workspace(db, workspace=workspace, agent_id=agent_id)
    workspace_definitions = await load_workspace_tool_definitions(db, workspace)
    available_workspace_names = workspace_tool_names(workspace_definitions)

    changed_fields: list[str] = []

    if "name" in payload.model_fields_set:
        if payload.name is None:
            raise AppValidationError("name cannot be null", field="name")
        _set_if_changed(agent, "name", payload.name, changed_fields)

    if "description" in payload.model_fields_set:
        _set_if_changed(agent, "description", payload.description, changed_fields)

    if "instructions" in payload.model_fields_set:
        if payload.instructions is None:
            raise AppValidationError("instructions cannot be null", field="instructions")
        _set_if_changed(agent, "instructions", payload.instructions, changed_fields)

    if "slug" in payload.model_fields_set:
        if payload.slug is None:
            raise AppValidationError("slug cannot be null", field="slug")
        normalized_slug = slugify(payload.slug, max_length=100) or "agent"
        if normalized_slug != agent.slug:
            existing = await db.scalar(
                select(Agent.id).where(
                    Agent.slug == normalized_slug,
                    Agent.workspace_id == workspace.id,
                    Agent.id != agent.id,
                )
            )
            if existing is not None:
                raise ConflictError(
                    "An agent with that slug already exists",
                    conflicting_resource="agent",
                )
            agent.slug = normalized_slug
            changed_fields.append("slug")

    tool_selection = _candidate_tool_selection(
        agent,
        payload,
        available_workspace_names=available_workspace_names,
        extra_allowed_policies={
            definition.name: definition.allowed_policies() for definition in workspace_definitions
        },
    )
    for field_name, value in (
        ("all_tools", tool_selection.all_tools),
        ("tool_names", tool_selection.tool_names),
        ("excluded_tool_names", tool_selection.excluded_tool_names),
        ("tool_policies", tool_selection.tool_policies),
    ):
        _set_if_changed(agent, field_name, value, changed_fields)

    candidate_allowed_agent_ids = [UUID(value) for value in (agent.allowed_agent_ids or [])]
    if "allowed_agent_ids" in payload.model_fields_set:
        if payload.allowed_agent_ids is None:
            raise AppValidationError(
                "allowed_agent_ids cannot be null",
                field="allowed_agent_ids",
            )
        candidate_allowed_agent_ids = payload.allowed_agent_ids

    allowed_agent_ids = await validate_agent_references(
        db,
        workspace=workspace,
        allowed_agent_ids=candidate_allowed_agent_ids,
        current_agent_id=agent.id,
    )
    if allowed_agent_ids != list(agent.allowed_agent_ids or []):
        agent.allowed_agent_ids = allowed_agent_ids
        changed_fields.append("allowed_agent_ids")

    candidate_model_provider = (
        payload.model_provider
        if "model_provider" in payload.model_fields_set
        else agent.model_provider
    )
    candidate_model = payload.model if "model" in payload.model_fields_set else agent.model
    candidate_azure_deployment = (
        payload.azure_deployment
        if "azure_deployment" in payload.model_fields_set
        else agent.azure_deployment
    )
    normalized_candidate_model_provider = validate_model_configuration(
        workspace=workspace,
        model_provider=candidate_model_provider,
        model=candidate_model,
        azure_deployment=candidate_azure_deployment,
    )

    for field_name, value in (
        ("model_provider", normalized_candidate_model_provider),
        ("model", candidate_model),
        ("azure_deployment", candidate_azure_deployment),
    ):
        if field_name in payload.model_fields_set:
            _set_if_changed(agent, field_name, value, changed_fields)

    for field_name in (
        "model_settings",
        "max_steps",
        "is_active",
        "is_favorite",
        "metadata_json",
    ):
        if field_name in payload.model_fields_set:
            _set_if_changed(agent, field_name, getattr(payload, field_name), changed_fields)

    if changed_fields:
        try:
            await db.flush()
        except IntegrityError as exc:
            if not is_agent_slug_integrity_error(exc):
                raise
            raise ConflictError(
                "An agent with that slug already exists",
                conflicting_resource="agent",
            ) from exc
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.AGENT,
            resource_id=agent.id,
            actor=actor,
            details={
                "slug": agent.slug,
                "fields": changed_fields,
                "model_provider": agent.model_provider,
                "model": agent.model,
            },
        )
        await db.refresh(agent)

    return AgentRead.from_agent(agent, extra_tool_names=available_workspace_names)


def _candidate_tool_selection(
    agent: Agent,
    payload: AgentUpdateRequest,
    *,
    available_workspace_names: frozenset[str],
    extra_allowed_policies: dict[str, frozenset[str]],
) -> ToolSelection:
    fields_set = payload.model_fields_set
    for field_name in ("all_tools", "tool_names", "excluded_tool_names"):
        if field_name in fields_set and getattr(payload, field_name) is None:
            raise AppValidationError(f"{field_name} cannot be null", field=field_name)

    all_tools = payload.all_tools if "all_tools" in fields_set else bool(agent.all_tools)
    # Switching mode discards the stored lists unless the payload supplies them.
    keep_stored = all_tools == bool(agent.all_tools)
    tool_names = _supplied_or_stored_names(agent, payload, "tool_names", keep_stored)
    excluded_tool_names = _supplied_or_stored_names(
        agent, payload, "excluded_tool_names", keep_stored
    )
    policies_supplied = "tool_policies" in fields_set
    stale_tool_names = {
        name
        for name in (*(agent.tool_names or []), *(agent.excluded_tool_names or []))
        if name.startswith(RESERVED_WORKSPACE_TOOL_PREFIXES)
    }
    return normalize_tool_selection(
        all_tools=bool(all_tools),
        tool_names=tool_names,
        excluded_tool_names=excluded_tool_names,
        tool_policies=(
            payload.tool_policies if policies_supplied else dict(agent.tool_policies or {}) or None
        ),
        workspace_tool_names=available_workspace_names,
        stale_tool_names=stale_tool_names,
        extra_allowed_policies=extra_allowed_policies,
        drop_unselected_policies=not policies_supplied,
    )


def _supplied_or_stored_names(
    agent: Agent,
    payload: AgentUpdateRequest,
    field_name: str,
    keep_stored: bool,
) -> list[str]:
    if field_name in payload.model_fields_set:
        return list(getattr(payload, field_name) or [])
    return list(getattr(agent, field_name) or []) if keep_stored else []


def _set_if_changed(agent: Agent, field_name: str, value, changed_fields: list[str]) -> None:
    if getattr(agent, field_name) != value:
        setattr(agent, field_name, value)
        changed_fields.append(field_name)
