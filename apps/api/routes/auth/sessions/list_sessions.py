# apps/api/routes/auth/list_sessions.py

"""Route for listing current-user sessions."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import list_sessions as list_sessions_service
from services.auth.schemas import SessionsResponse

router = APIRouter()


@router.get("/sessions")
async def list_sessions(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
) -> SessionsResponse:
    return await list_sessions_service(db, request=request, user=user)
