# apps/api/routes/auth/revoke_sessions.py

"""Route for revoking current-user sessions."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import revoke_sessions as revoke_sessions_service
from services.auth.schemas import MessageResponse

router = APIRouter()


@router.delete("/sessions")
async def revoke_sessions(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    keep_current: Annotated[bool, Query()] = True,
) -> MessageResponse:
    return await revoke_sessions_service(
        db,
        request=request,
        response=response,
        user=user,
        keep_current=keep_current,
    )
