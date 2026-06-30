# apps/api/routes/auth/oauth/start_oauth_link.py

"""Route for creating an OAuth link authorization URL for the current user."""

from typing import Annotated

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import start_oauth_link
from services.auth.schemas import OAuthAuthorizationUrlRequest, OAuthAuthorizationUrlResponse

router = APIRouter()


@router.post("/oauth/{provider_name}/link/authorization-url")
async def start_oauth_link_route(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    provider_name: Annotated[str, Path(min_length=1, max_length=50)],
    payload: OAuthAuthorizationUrlRequest,
) -> OAuthAuthorizationUrlResponse:
    return await start_oauth_link(
        db,
        request=request,
        user=user,
        provider_name=provider_name,
        payload=payload,
    )
