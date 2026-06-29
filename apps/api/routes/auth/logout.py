# apps/api/routes/auth/logout.py

"""Route for logout."""

from fastapi import APIRouter, Request, Response

from core.dependencies import AsyncDbSessionDep, OptionalUserDep
from services.auth import logout as logout_service
from services.auth.schemas import MessageResponse

router = APIRouter()


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    user: OptionalUserDep,
) -> MessageResponse:
    return await logout_service(db, request=request, response=response, user=user)
