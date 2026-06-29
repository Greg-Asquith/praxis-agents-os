# apps/api/routes/auth/revoke_session.py

"""Route for revoking one current-user session."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import revoke_session_by_id
from services.auth.schemas import MessageResponse

router = APIRouter()


@router.delete("/sessions/{session_id}")
async def revoke_session(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    session_id: Annotated[UUID, Path()],
) -> MessageResponse:
    return await revoke_session_by_id(
        db,
        request=request,
        response=response,
        user=user,
        session_id=session_id,
    )
