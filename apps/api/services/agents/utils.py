# apps/api/services/agents/utils.py

"""Helpers specific to agent configuration services."""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from models.agent import Agent
from models.skills import Skill
from models.workspace import Workspace, WorkspaceMembership
from services.agents.models.domain import ALL_PROVIDERS, PROVIDER_AZURE
from services.agents.models.registry import find_model
from services.agents.runtime.tools.contract import VALID_TOOL_POLICIES
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.workspaces.utils import EDITOR_ROLES

AGENT_SLUG_UNIQUE_INDEX = "ix_agents_slug_workspace"


def require_agent_write_access(membership: WorkspaceMembership) -> None:
    if membership.role not in EDITOR_ROLES:
        raise AuthorizationError(
            "Requires workspace write access",
            details={
                "allowed_roles": sorted(EDITOR_ROLES),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(membership.workspace_id),
                "user_id": str(membership.user_id),
            },
        )


async def get_agent_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_id: UUID,
) -> Agent:
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if agent is None:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            resource_id=str(agent_id),
        )
    return agent


async def validate_agent_references(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_ids: list[UUID],
    allowed_agent_ids: list[UUID],
    current_agent_id: UUID | None = None,
) -> tuple[list[str], list[str]]:
    normalized_skill_ids = _dedupe_uuid_strings(skill_ids)
    normalized_agent_ids = _dedupe_uuid_strings(allowed_agent_ids)

    if current_agent_id is not None and str(current_agent_id) in normalized_agent_ids:
        raise AppValidationError(
            "Agent cannot delegate to itself",
            field="allowed_agent_ids",
        )

    if normalized_skill_ids:
        await _ensure_active_skills_exist(
            db,
            workspace=workspace,
            skill_ids=[UUID(value) for value in normalized_skill_ids],
        )
    if normalized_agent_ids:
        await _ensure_active_agents_exist(
            db,
            workspace=workspace,
            agent_ids=[UUID(value) for value in normalized_agent_ids],
        )

    return normalized_skill_ids, normalized_agent_ids


def validate_tool_configuration(
    *,
    tool_names: list[str],
    tool_policies: dict[str, str] | None,
) -> dict[str, str] | None:
    _tool_names, normalized_policies = normalize_tool_configuration(
        tool_names=tool_names,
        tool_policies=tool_policies,
    )
    return normalized_policies


def normalize_tool_configuration(
    *,
    tool_names: list[str],
    tool_policies: dict[str, str] | None,
) -> tuple[list[str], dict[str, str] | None]:
    unknown_tools = sorted({name for name in tool_names if name not in RUNTIME_TOOL_CATALOG})
    if unknown_tools:
        raise AppValidationError(
            "Agent references unknown runtime tools",
            field="tool_names",
            details={
                "unknown_tools": unknown_tools,
                "available_tools": _configurable_tool_names(),
            },
        )

    configurable_tool_names = [
        name for name in tool_names if RUNTIME_TOOL_CATALOG[name].configurable
    ]
    configurable_tool_name_set = set(configurable_tool_names)

    if tool_policies is None:
        return configurable_tool_names, None

    unknown_policy_catalog_tools = sorted(
        {name for name in tool_policies if name not in RUNTIME_TOOL_CATALOG}
    )
    if unknown_policy_catalog_tools:
        raise AppValidationError(
            "Tool policies reference unknown runtime tools",
            field="tool_policies",
            details={
                "unknown_policy_tools": unknown_policy_catalog_tools,
                "available_tools": _configurable_tool_names(),
            },
        )

    configurable_tool_policies = {
        name: policy
        for name, policy in tool_policies.items()
        if (
            name in RUNTIME_TOOL_CATALOG
            and RUNTIME_TOOL_CATALOG[name].configurable
        )
    }

    unknown_policy_tools = sorted(
        {
            name
            for name in configurable_tool_policies
            if name not in configurable_tool_name_set
        }
    )
    if unknown_policy_tools:
        raise AppValidationError(
            "Tool policies must reference enabled tools",
            field="tool_policies",
            details={"unknown_policy_tools": unknown_policy_tools},
        )

    invalid_policies = {
        name: policy
        for name, policy in configurable_tool_policies.items()
        if policy not in VALID_TOOL_POLICIES
    }
    if invalid_policies:
        raise AppValidationError(
            "Tool policies contain invalid values",
            field="tool_policies",
            details={
                "invalid_policies": invalid_policies,
                "valid_tool_policies": sorted(VALID_TOOL_POLICIES),
            },
        )

    unsupported_policies = {
        name: {
            "tool_policy": policy,
            "allowed_tool_policies": sorted(RUNTIME_TOOL_CATALOG[name].allowed_policies()),
        }
        for name, policy in configurable_tool_policies.items()
        if policy not in RUNTIME_TOOL_CATALOG[name].allowed_policies()
    }
    if unsupported_policies:
        raise AppValidationError(
            "Tool policies include unsupported values for enabled tools",
            field="tool_policies",
            details={"unsupported_tool_policies": unsupported_policies},
        )

    return configurable_tool_names, dict(configurable_tool_policies) or None


def _configurable_tool_names() -> list[str]:
    return sorted(
        name
        for name, definition in RUNTIME_TOOL_CATALOG.items()
        if definition.configurable
    )


def normalize_model_provider(model_provider: str | None) -> str | None:
    if model_provider is None:
        return None

    normalized = model_provider.strip()
    if not normalized:
        return None
    return normalized.lower()


def validate_model_configuration(
    *,
    model_provider: str | None,
    model: str | None,
    azure_deployment: str | None,
) -> str | None:
    normalized_model_provider = normalize_model_provider(model_provider)
    provider = (
        normalized_model_provider
        or normalize_model_provider(settings.DEFAULT_MODEL_PROVIDER)
        or ""
    )
    selected_model = (model or settings.DEFAULT_MODEL or "").strip()

    if provider not in ALL_PROVIDERS:
        raise AppValidationError(
            "Unknown model provider",
            field="model_provider",
            details={"model_provider": provider, "valid_providers": sorted(ALL_PROVIDERS)},
        )

    if provider == PROVIDER_AZURE:
        if not selected_model and not azure_deployment:
            raise AppValidationError(
                "Azure agents require a model or azure_deployment",
                field="azure_deployment",
            )
        return normalized_model_provider

    if azure_deployment:
        raise AppValidationError(
            "azure_deployment can only be used with the azure provider",
            field="azure_deployment",
            details={"model_provider": provider},
        )

    model_info = find_model(provider, selected_model)
    if model_info is None:
        raise AppValidationError(
            "Unknown model",
            field="model",
            details={"model_provider": provider, "model": selected_model},
        )
    if model_info.deprecated:
        raise AppValidationError(
            "Deprecated models cannot be selected for agents",
            field="model",
            details={"model_provider": provider, "model": selected_model},
        )
    return normalized_model_provider


def is_agent_slug_integrity_error(exc: IntegrityError) -> bool:
    constraint_names = _integrity_constraint_names(exc)
    if AGENT_SLUG_UNIQUE_INDEX in constraint_names:
        return True

    return AGENT_SLUG_UNIQUE_INDEX in str(exc)


async def _ensure_active_skills_exist(
    db: AsyncSession,
    *,
    workspace: Workspace,
    skill_ids: list[UUID],
) -> None:
    found = set(
        await db.scalars(
            select(Skill.id).where(
                Skill.id.in_(skill_ids),
                Skill.workspace_id == workspace.id,
                Skill.deleted == False,  # noqa: E712
                Skill.is_active.is_(True),
            )
        )
    )
    missing = sorted(str(skill_id) for skill_id in skill_ids if skill_id not in found)
    if missing:
        raise NotFoundError(
            "Skill not found",
            resource_type="skill",
            details={"missing_skill_ids": missing},
        )


async def _ensure_active_agents_exist(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_ids: list[UUID],
) -> None:
    found = set(
        await db.scalars(
            select(Agent.id).where(
                Agent.id.in_(agent_ids),
                Agent.workspace_id == workspace.id,
                Agent.deleted == False,  # noqa: E712
                Agent.is_active.is_(True),
            )
        )
    )
    missing = sorted(str(agent_id) for agent_id in agent_ids if agent_id not in found)
    if missing:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            details={"missing_agent_ids": missing},
        )


def _dedupe_uuid_strings(values: Iterable[UUID]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value)
        if item not in seen:
            normalized.append(item)
            seen.add(item)
    return normalized


def _integrity_constraint_names(exc: IntegrityError) -> set[str]:
    names: set[str] = set()
    seen: set[int] = set()
    pending: list[object | None] = [exc, getattr(exc, "orig", None)]

    while pending:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))

        for attr_name in ("constraint_name", "constraint"):
            attr = getattr(item, attr_name, None)
            if isinstance(attr, str) and attr:
                names.add(attr)

        diag = getattr(item, "diag", None)
        if diag is not None:
            constraint_name = getattr(diag, "constraint_name", None)
            if isinstance(constraint_name, str) and constraint_name:
                names.add(constraint_name)

        pending.extend(
            (
                getattr(item, "orig", None),
                getattr(item, "__cause__", None),
                getattr(item, "__context__", None),
            )
        )

    return names
