# apps/api/routes/tools/update_policy.py

"""Change the workspace default approval policy for one static tool."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_owner
from services.tools import set_tool_policy
from services.tools.schemas import ToolPolicyRead, ToolPolicyUpdateRequest

router = APIRouter(dependencies=[Depends(require_owner)])


@router.put("/{tool_name}/policy")
async def update_tool_policy(
    request: Request,
    payload: ToolPolicyUpdateRequest,
    tool_name: Annotated[str, Path(min_length=1, max_length=100)],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ToolPolicyRead:
    workspace, _membership = workspace_context
    return await set_tool_policy(
        db,
        workspace=workspace,
        tool_name=tool_name,
        policy=payload.policy,
        actor=actor,
        request=request,
    )
