# apps/api/routes/auth/login.py

"""Route for email/password login."""

from fastapi import APIRouter, Request, Response

from core.dependencies import AsyncDbSessionDep
from services.auth import login_with_password
from services.auth.schemas import AuthResponse, LoginRequest

router = APIRouter()


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    payload: LoginRequest,
) -> AuthResponse:
    return await login_with_password(db, request=request, response=response, payload=payload)
