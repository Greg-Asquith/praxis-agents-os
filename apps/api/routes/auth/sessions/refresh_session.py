# apps/api/routes/auth/refresh_session.py

"""Route for refreshing the current session."""

from fastapi import APIRouter, Request, Response

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import refresh_session as refresh_session_service
from services.auth.schemas import AuthResponse

router = APIRouter()


@router.post("/session/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
) -> AuthResponse:
    return await refresh_session_service(db, request=request, response=response, user=user)
