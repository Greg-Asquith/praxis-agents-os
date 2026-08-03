# apps/api/services/tools/set_tool_enabled.py

"""Set workspace availability for one runtime tool."""

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.user import User
from models.workspace import Workspace
from models.workspace_tool_settings import WorkspaceToolSetting
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.audit_events import AuditAction, AuditResourceType, record_workspace_audit_event
from services.tools.schemas import ToolAvailabilityRead
from services.tools.utils import invalidate_disabled_tools_cache


async def set_tool_enabled(
    db: AsyncSession,
    *,
    workspace: Workspace,
    tool_name: str,
    enabled: bool,
    actor: User,
    request: Request | None,
) -> ToolAvailabilityRead:
    """Upsert one workspace tool setting and record the operator change."""
    if tool_name not in RUNTIME_TOOL_CATALOG:
        raise NotFoundError(
            "Runtime tool not found",
            resource_type="tool",
            resource_id=tool_name,
        )

    statement = (
        insert(WorkspaceToolSetting)
        .values(
            workspace_id=workspace.id,
            tool_name=tool_name,
            enabled=enabled,
            updated_by=actor.id,
        )
        .on_conflict_do_update(
            constraint="uq_workspace_tool_settings_workspace_tool",
            set_={
                "enabled": enabled,
                "updated_by": actor.id,
                "updated_at": func.now(),
            },
        )
    )
    await db.execute(statement)
    invalidate_disabled_tools_cache(db, workspace.id)
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.ENABLE if enabled else AuditAction.DISABLE,
        resource_type=AuditResourceType.TOOL,
        resource_id=tool_name,
        actor=actor,
        details={"tool_name": tool_name, "enabled": enabled},
    )
    return ToolAvailabilityRead(tool_name=tool_name, enabled=enabled)
