# apps/api/services/agents/create_agent.py

"""Create a workspace-scoped agent."""

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent import Agent
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agents.runtime.tools.workspace_tools import (
    load_workspace_tool_definitions,
    workspace_tool_names,
)
from services.agents.schemas import AgentCreateRequest, AgentRead
from services.agents.utils import (
    is_agent_slug_integrity_error,
    normalize_tool_configuration,
    require_agent_write_access,
    validate_agent_references,
    validate_model_configuration,
)
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from utils.slugify import slugify


async def create_agent(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: AgentCreateRequest,
) -> AgentRead:
    require_agent_write_access(membership)

    workspace_definitions = await load_workspace_tool_definitions(db, workspace)
    extra_tool_names = workspace_tool_names(workspace_definitions)

    tool_names, tool_policies = normalize_tool_configuration(
        tool_names=payload.tool_names,
        tool_policies=payload.tool_policies,
        extra_tool_names=extra_tool_names,
        extra_allowed_policies={
            definition.name: definition.allowed_policies() for definition in workspace_definitions
        },
    )
    model_provider = validate_model_configuration(
        model_provider=payload.model_provider,
        model=payload.model,
        azure_deployment=payload.azure_deployment,
    )
    skill_ids, allowed_agent_ids = await validate_agent_references(
        db,
        workspace=workspace,
        skill_ids=payload.skill_ids,
        allowed_agent_ids=payload.allowed_agent_ids,
    )

    base_slug = slugify(payload.slug or payload.name, max_length=100) or "agent"
    slug_was_supplied = payload.slug is not None
    agent: Agent | None = None

    for counter in range(1, 11):
        candidate_slug = base_slug if counter == 1 else f"{base_slug}-{counter}"
        candidate = Agent(
            name=payload.name,
            slug=candidate_slug,
            description=payload.description,
            instructions=payload.instructions,
            workspace_id=workspace.id,
            created_by=actor.id,
            tool_names=tool_names,
            tool_policies=tool_policies,
            code_mode_enabled=payload.code_mode_enabled,
            skill_ids=skill_ids,
            allowed_agent_ids=allowed_agent_ids,
            model_provider=model_provider,
            model=payload.model,
            model_settings=payload.model_settings,
            azure_deployment=payload.azure_deployment,
            max_steps=payload.max_steps,
            is_active=payload.is_active,
            is_favorite=payload.is_favorite,
            metadata_json=payload.metadata_json,
        )
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush([candidate])
        except IntegrityError as exc:
            if candidate in db:
                db.expunge(candidate)
            if not is_agent_slug_integrity_error(exc):
                raise
            if slug_was_supplied:
                raise ConflictError(
                    "An agent with that slug already exists",
                    conflicting_resource="agent",
                ) from exc
            continue
        agent = candidate
        break

    if agent is None:
        raise ConflictError(
            "Could not generate a unique agent slug",
            conflicting_resource="agent",
        )

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.AGENT,
        resource_id=agent.id,
        actor=actor,
        details={
            "slug": agent.slug,
            "model_provider": agent.model_provider,
            "model": agent.model,
            "tool_names": agent.tool_names,
            "code_mode_enabled": agent.code_mode_enabled,
            "skill_count": len(agent.skill_ids or []),
            "allowed_agent_count": len(agent.allowed_agent_ids or []),
        },
    )
    await db.refresh(agent)
    return AgentRead.from_agent(agent, extra_tool_names=extra_tool_names)
