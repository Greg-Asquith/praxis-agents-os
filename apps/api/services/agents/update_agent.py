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
from services.agents.schemas import AgentRead, AgentUpdateRequest
from services.agents.utils import (
    get_agent_for_workspace,
    is_agent_slug_integrity_error,
    normalize_tool_configuration,
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

    candidate_tool_names = list(agent.tool_names or [])
    if "tool_names" in payload.model_fields_set:
        if payload.tool_names is None:
            raise AppValidationError("tool_names cannot be null", field="tool_names")
        candidate_tool_names = payload.tool_names

    candidate_tool_policies = dict(agent.tool_policies or {}) if agent.tool_policies else None
    if "tool_policies" in payload.model_fields_set:
        candidate_tool_policies = payload.tool_policies
    elif "tool_names" in payload.model_fields_set and candidate_tool_policies:
        candidate_tool_policies = {
            name: policy
            for name, policy in candidate_tool_policies.items()
            if name in set(candidate_tool_names)
        }
    candidate_tool_names, candidate_tool_policies = normalize_tool_configuration(
        tool_names=candidate_tool_names,
        tool_policies=candidate_tool_policies,
    )
    if candidate_tool_names != list(agent.tool_names or []):
        agent.tool_names = candidate_tool_names
        changed_fields.append("tool_names")
    if candidate_tool_policies != agent.tool_policies:
        agent.tool_policies = candidate_tool_policies
        changed_fields.append("tool_policies")

    candidate_skill_ids = [UUID(value) for value in (agent.skill_ids or [])]
    if "skill_ids" in payload.model_fields_set:
        if payload.skill_ids is None:
            raise AppValidationError("skill_ids cannot be null", field="skill_ids")
        candidate_skill_ids = payload.skill_ids

    candidate_allowed_agent_ids = [UUID(value) for value in (agent.allowed_agent_ids or [])]
    if "allowed_agent_ids" in payload.model_fields_set:
        if payload.allowed_agent_ids is None:
            raise AppValidationError(
                "allowed_agent_ids cannot be null",
                field="allowed_agent_ids",
            )
        candidate_allowed_agent_ids = payload.allowed_agent_ids

    skill_ids, allowed_agent_ids = await validate_agent_references(
        db,
        workspace=workspace,
        skill_ids=candidate_skill_ids,
        allowed_agent_ids=candidate_allowed_agent_ids,
        current_agent_id=agent.id,
    )
    if skill_ids != list(agent.skill_ids or []):
        agent.skill_ids = skill_ids
        changed_fields.append("skill_ids")
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

    return AgentRead.from_agent(agent)


def _set_if_changed(agent: Agent, field_name: str, value, changed_fields: list[str]) -> None:
    if getattr(agent, field_name) != value:
        setattr(agent, field_name, value)
        changed_fields.append(field_name)
