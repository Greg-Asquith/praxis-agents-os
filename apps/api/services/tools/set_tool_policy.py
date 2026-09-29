# apps/api/services/tools/set_tool_policy.py

"""Set the workspace default approval policy for one runtime tool."""

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace
from models.workspace_tool_settings import WorkspaceToolSetting
from services.agents.runtime.tools.contract import ToolPolicy
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.tools.schemas import ToolPolicyRead
from services.tools.utils import invalidate_tool_defaults_cache, require_configurable_tool


async def set_tool_policy(
    db: AsyncSession,
    *,
    workspace: Workspace,
    tool_name: str,
    policy: ToolPolicy | None,
    actor: User,
    request: Request | None,
) -> ToolPolicyRead:
    """Upsert one workspace tool policy; null restores the tool's own default."""
    definition = require_configurable_tool(tool_name)
    allowed_policies = definition.allowed_policies()
    if policy is not None and policy not in allowed_policies:
        raise AppValidationError(
            "This tool does not support that approval setting",
            field="policy",
            details={"tool_name": tool_name, "allowed_policies": sorted(allowed_policies)},
        )

    statement = (
        insert(WorkspaceToolSetting)
        .values(
            workspace_id=workspace.id,
            tool_name=tool_name,
            policy=policy,
            updated_by=actor.id,
        )
        .on_conflict_do_update(
            constraint="uq_workspace_tool_settings_workspace_tool",
            set_={
                "policy": policy,
                "updated_by": actor.id,
                "updated_at": func.now(),
            },
        )
    )
    await db.execute(statement)
    invalidate_tool_defaults_cache(db, workspace.id)
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.TOOL,
        resource_id=tool_name,
        actor=actor,
        details={"tool_name": tool_name, "policy": policy},
    )
    return ToolPolicyRead(
        tool_name=tool_name,
        policy=policy,
        effective_policy=policy or definition.default_policy,
    )
