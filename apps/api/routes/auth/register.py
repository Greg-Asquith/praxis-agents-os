# apps/api/routes/auth/register.py

"""Route for email/password registration."""

from fastapi import APIRouter, Request, Response, status

from core.dependencies import AsyncDbSessionDep
from services.auth import register_with_password
from services.auth.schemas import AuthResponse, RegisterRequest

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    payload: RegisterRequest,
) -> AuthResponse:
    return await register_with_password(db, request=request, response=response, payload=payload)
