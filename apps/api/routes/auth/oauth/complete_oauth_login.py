# apps/api/routes/auth/complete_oauth_login.py

"""Route for completing OAuth login."""

from typing import Annotated

from fastapi import APIRouter, Path, Request, Response

from core.dependencies import AsyncDbSessionDep
from services.auth import complete_oauth_login
from services.auth.schemas import AuthResponse, OAuthCallbackRequest

router = APIRouter()


@router.post("/oauth/{provider_name}/callback")
async def complete_oauth_login_route(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    provider_name: Annotated[str, Path(min_length=1, max_length=50)],
    payload: OAuthCallbackRequest,
) -> AuthResponse:
    return await complete_oauth_login(
        db,
        request=request,
        response=response,
        provider_name=provider_name,
        payload=payload,
    )
